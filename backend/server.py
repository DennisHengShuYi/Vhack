"""
RescueSwarm Backend — FastMCP stdio + FastAPI REST server.

Architecture:
  - FastMCP stdio server (main thread): exposes MCP tools for the LangChain agent
  - FastAPI (background thread): REST endpoints polled by the React frontend
  - Shared state (shared.sim): single SimulationState instance used by both

Loop A (Simulation Ticker, every 0.7s — inside FastAPI event loop):
  - Moves drones along path queues / toward targets
  - Executes thermal scans on arrival
  - Manages charging, battery emergency RTB
  - Detects victim standby states

Loop B (AI Planning — handled externally by agent/agent.py via MCP):
  - Agent polls get_idle_drones(), invokes GPT-4o via LangChain
  - Calls assign_scan_zone() / return_to_base() MCP tools
"""
import asyncio
import os
import sys
import json
import time
import threading
from contextlib import asynccontextmanager
from typing import Optional, Any
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

import shared
from simulation import SimulationState, ZoneStatus, chebyshev, LOW_BATTERY_THRESHOLD, BATTERY_RETURN_RESERVE, GRID_W, GRID_H

# ─── FastMCP Server ────────────────────────────────────────────────────────────
mcp = FastMCP("DroneCommandServer")

SIM_TICK = 0.7  # seconds between simulation steps


# ─── WebSocket Broadcast Manager ───────────────────────────────────────────────
class StreamBroadcaster:
    """Manages all connected WebSocket clients for live token streaming."""
    def __init__(self):
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)

    async def broadcast(self, text: str):
        dead = set()
        for ws in self._clients:
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        self._clients -= dead


broadcaster = StreamBroadcaster()


# ─── Simulation Tick Loop (Loop A) ────────────────────────────────────────────
async def run_simulation_loop():
    """Advances the simulation one step at a time. No AI logic — handled by agent via MCP."""
    while True:
        sim = shared.sim
        if sim.mission_active:
            base_x, base_y = sim.base_station

            # Mission completion check
            all_zones_done = all(z.status == ZoneStatus.COMPLETE for z in sim.zone.zones.values())
            if all_zones_done:
                sim.log("🏁 MISSION ACCOMPLISHED — Full grid search complete!", "SUCCESS")
                coverage = sim.get_status()["stats"]["coverage_pct"]
                sim.log(
                    f"📊 Final Stats: Coverage {coverage}% | "
                    f"Survivors Found: {sim.total_victims_found} | "
                    f"Rescued: {sim.total_rescued}",
                    "SUCCESS",
                )
                for drone in sim.drones.values():
                    drone.base_x, drone.base_y = base_x, base_y
                    if (drone.x, drone.y) != (base_x, base_y):
                        drone.path_queue = sim.compute_path(drone.x, drone.y, base_x, base_y)
                        drone.target_x, drone.target_y = base_x, base_y
                        drone.returning_to_base = True
                        drone.mission_complete_rtb = True
                        drone.status = "RETURNING"
                        drone.status_label = "RTB — COMPLETE"
                sim.mission_active = False
                sim.mission_end_time = time.time()
                try:
                    try:
                        from backend.mission_flusher import flush_mission
                        from backend.supabase_client import get_client
                    except ModuleNotFoundError:
                        from mission_flusher import flush_mission
                        from supabase_client import get_client
                    _sb = get_client()
                    threading.Thread(
                        target=flush_mission, args=(sim, _sb), daemon=False
                    ).start()
                except EnvironmentError:
                    print("[FLUSH] Supabase env vars not set — skipping flush.", file=sys.stderr)

            # Heartbeat check — brings drones online in staggered order
            sim.tick_count += 1
            sim.simulate_heartbeats()

            if sim.mission_active:
                recent_events = [
                    e["text"] for e in sim.mission_log[-10:]
                    if e.get("level") in ("VICTIM_FOUND", "SUCCESS", "WARN")
                ]
                sim.append_replay_snapshot(events=recent_events)

            # Survivor mobility: move mobile survivors every 5 ticks
            if sim.tick_count % 5 == 0:
                sim.simulate_survivor_movement()

            # Loop A: advance each drone one step
            if sim.mission_active:
                for d_id, drone in list(sim.drones.items()):
                  try:
                    drone.base_x, drone.base_y = base_x, base_y

                    # Skip offline drones — not yet connected via heartbeat
                    if not drone.is_active:
                        continue

                    # Victim standby — drone waits for operator
                    if drone.is_waiting_response:
                        drone.status = "IDLE"
                        drone.status_label = "VICTIM STANDBY"
                        continue

                    # Auto-charge at base (adaptive — charge only to minimum needed)
                    if (drone.x, drone.y) == (base_x, base_y) and drone.battery < 100 and (
                        drone.returning_to_base or drone.is_charging or drone.battery < LOW_BATTERY_THRESHOLD
                    ):
                        charge_target = sim.smart_charge_target(d_id)
                        if not drone.is_charging:
                            sim.log(f"🤖 {d_id} arrived at base. Charging to {charge_target:.0f}%.", "INFO", d_id)
                        sim.charge_step(d_id)
                        # Stop charging early if we've reached the smart target
                        if drone.battery >= charge_target and drone.is_charging:
                            drone.is_charging = False
                            drone.charge_cycles += 1
                            drone.status = "IDLE"
                            drone.status_label = "READY"
                            drone.target_x = None
                            drone.target_y = None
                            drone.returning_to_base = False
                            drone.voice_override = False
                            sim.log(f"[BATTERY] {d_id} smart-charged to {drone.battery:.0f}%. Ready.", "CHARGE", d_id)
                        if not drone.is_charging:
                            drone.returning_to_base = False
                        continue

                    # No target and empty path — zone complete; check pending residual then go idle
                    if drone.target_x is None and not drone.path_queue:
                        # Zone completion bookkeeping
                        if drone.assigned_zone_id:
                            zid = drone.assigned_zone_id
                            drone.assigned_zone_id = None
                            # Only mark COMPLETE if no other drone is still scanning this zone
                            other_scanning = any(
                                d.assigned_zone_id == zid
                                for did2, d in sim.drones.items()
                                if did2 != d_id
                            )
                            if not other_scanning and zid in sim.zone.zones:
                                sim.zone.zones[zid].status = ZoneStatus.COMPLETE
                                sim.zone.zones[zid].completed_tick = sim.tick_count
                                sim.log(f"✅ Zone {zid} search complete.", "SUCCESS", d_id)

                        # RESIDUAL HANDOFF: if this drone was reserved to cover a residual zone, go there now
                        if drone.pending_zone_id and not drone.returning_to_base:
                            pending_zid = drone.pending_zone_id
                            drone.pending_zone_id = None
                            sim.reserved_zones.pop(pending_zid, None)
                            pzone = sim.zone.zones.get(pending_zid)
                            if pzone and pzone.status == ZoneStatus.UNSCANNED:
                                if sim.claim_zone(pending_zid, d_id):
                                    result = sim.assign_zone(d_id, pending_zid)
                                    if result.get("success"):
                                        sim.log(f"🔄 {d_id} covering residual zone {pending_zid}.", "INFO", d_id)
                                        continue

                        drone.status = "IDLE"
                        drone.status_label = "AWAITING ORDERS"
                        continue

                    # Movement: use path_queue if available, else step toward target_x/y
                    if drone.path_queue:
                        nx, ny = drone.path_queue.pop(0)
                        tx, ty = nx, ny
                    else:
                        tx, ty = drone.target_x, drone.target_y
                        nx, ny = drone.x, drone.y
                        if nx != tx:
                            nx += 1 if tx > nx else -1
                        if ny != ty:
                            ny += 1 if ty > ny else -1
                        # Safety: if direct step lands on a hazard (lake), try axis-only moves
                        if sim.zone.hazard_cells[ny][nx] and not (nx == tx and ny == ty):
                            ax = drone.x + (1 if tx > drone.x else -1 if tx < drone.x else 0)
                            bx, by = drone.x, drone.y + (1 if ty > drone.y else -1 if ty < drone.y else 0)
                            if 0 <= ax < GRID_W and not sim.zone.hazard_cells[drone.y][ax]:
                                nx, ny = ax, drone.y
                            elif 0 <= by < GRID_H and not sim.zone.hazard_cells[by][bx]:
                                nx, ny = bx, by
                            else:
                                nx, ny = drone.x, drone.y  # fully blocked — stay put

                    # Arrived at current step target
                    if drone.x == nx and drone.y == ny and not drone.path_queue:
                        if nx == base_x and ny == base_y:
                            drone.returning_to_base = False
                            drone.target_x = None
                            drone.target_y = None
                            sim.log(f"🤖 {d_id} reached base station. Commencing recharge.", "INFO", d_id)
                            sim.charge_step(d_id)
                        else:
                            # Standard autonomous scan logic
                            result = sim.scan(d_id)
                            if sim.metrics.first_find_tick is None and sim.total_victims_found > 0:
                                sim.metrics.record_first_find(sim.tick_count)
                            if "THERMAL MATCH" not in result and "VICTIM_DETECTED" not in result:
                                drone.target_x = None

                            # Voice diversion complete — release override and go free agent
                            if drone.voice_override and not drone.path_queue:
                                sim.log(f"✅ {d_id} diversion complete. Free agent — awaiting orders.", "SUCCESS", d_id)
                                drone.voice_override = False
                                drone.original_pos = None
                                drone.target_x = None
                                drone.target_y = None
                                drone.status = "IDLE"
                                drone.status_label = "AWAITING ORDERS"
                                continue

                            drone.status_label = "SCANNED"
                        continue

                    # Execute move
                    drone.x, drone.y = nx, ny

                    # Guide victim moves with drone
                    if drone.is_guiding and drone.guiding_victim_id:
                        for s in sim.zone.survivors:
                            if s["id"] == drone.guiding_victim_id:
                                s["x"], s["y"] = nx, ny
                                if (nx, ny) == (base_x, base_y):
                                    s["rescued"] = True
                                    drone.is_guiding = False
                                    drone.guiding_victim_id = None
                                    sim.total_rescued += 1
                                    sim.log(f"Survivor guided safely to base station!", "SUCCESS", d_id)

                    # Battery drain — forest costs 1.5% per cell, others 1.0%
                    terrain_at = sim.zone.terrain_types[ny][nx]
                    drain = 1.5 if terrain_at == 'forest' else 1.0
                    drone.battery = max(0.0, drone.battery - drain)
                    sim.metrics.battery_consumed_total += drain
                    drone.status = "ON_MISSION"
                    drone.status_label = f"→({tx},{ty})"

                    # Path history for trail visualization
                    drone.path_history.append([nx, ny])
                    while len(drone.path_history) > 12:
                        drone.path_history.pop(0)

                    # Low battery → force RTB
                    if sim.should_return_to_base(drone) and not drone.returning_to_base:
                        if drone.assigned_zone_id:
                            zid = drone.assigned_zone_id
                            if drone.path_queue and zid in sim.zone.zones:
                                sim.zone.zones[zid].residual_path = list(drone.path_queue)
                            sim.release_zone(zid)
                            sim.log(f"⚠️ {d_id} aborting zone {zid} — low battery. Residual path saved.", "WARN", d_id)
                            drone.assigned_zone_id = None
                        drone.path_queue = sim.compute_path(drone.x, drone.y, base_x, base_y)
                        drone.target_x, drone.target_y = base_x, base_y
                        drone.returning_to_base = True
                        drone.status = "RETURNING"
                        sim.log(f"🪫 {d_id} battery {drone.battery:.0f}% critical. Initiating RTB.", "WARN", d_id)

                    # Opportunistic scan while passing through unscanned cell OR if on high-priority intel mission
                    if not sim.zone.scanned_cells[ny][nx] or drone.voice_override:
                        sim.scan(d_id)

                  except Exception as e:
                    print(f"[TICK ERROR] {d_id}: {e}", file=sys.stderr)

        await asyncio.sleep(SIM_TICK)


# ─── FastAPI App ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    loop_task = asyncio.create_task(run_simulation_loop())
    yield
    loop_task.cancel()


app = FastAPI(
    title="RescueSwarm API",
    description="AI Drone Search & Rescue Simulation — MCP + FastAPI",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


from history import router as history_router
app.include_router(history_router)


@app.get("/state")
async def get_state():
    """Return full simulation state: drones, zone, log, stats."""
    return shared.sim.get_status()


@app.post("/run-mission")
async def run_mission():
    """Activate the swarm — simulation tick loop starts moving drones."""
    sim = shared.sim
    if sim.mission_active:
        return {"status": "Mission already active", "running": True}
    sim.mission_active = True
    sim.mission_start_time = time.time()
    sim.log("🚀 MISSION ACTIVE: Swarm deployed. Awaiting SENTINEL directives.", "SUCCESS")
    return {"status": "Mission started", "running": True}


@app.post("/stop-mission")
async def stop_mission():
    """Halt mission immediately."""
    sim = shared.sim
    sim.mission_active = False
    sim.mission_end_time = time.time()
    sim.log("🛑 MISSION HALTED by operator command.", "WARN")
    try:
        try:
            from backend.mission_flusher import flush_mission
            from backend.supabase_client import get_client
        except ModuleNotFoundError:
            from mission_flusher import flush_mission
            from supabase_client import get_client
        _sb = get_client()
        threading.Thread(
            target=flush_mission, args=(sim, _sb), daemon=True
        ).start()
    except EnvironmentError:
        print("[FLUSH] Supabase env vars not set — skipping flush.", file=sys.stderr)
    return {"status": "Mission stopped"}


@app.post("/reset")
async def reset_mission(num_victims: int = 10):
    """Reinitialize the simulation with a fresh disaster layout."""
    shared.sim = SimulationState(num_victims=num_victims)
    shared.sim.log(f"🔄 SIMULATION RESET — New disaster layout with {num_victims} survivors.", "INFO")
    return {"status": "Reset complete", "num_victims": num_victims}


@app.post("/log")
async def post_log(text: str, level: str = "AI"):
    """Agent posts its reasoning / tool results to the mission log."""
    shared.sim.log(text, level)
    return {"status": "logged"}


@app.post("/log/stream")
async def post_log_stream(text: str = ""):
    """Agent posts live LLM token chunks — stored for poll fallback + pushed to WS clients."""
    shared.sim.streaming_text = text
    await broadcaster.broadcast(text)
    return {"status": "ok"}


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket):
    """WebSocket endpoint — pushes live agent token chunks to the frontend."""
    await broadcaster.connect(websocket)
    try:
        while True:
            # Keep connection alive; frontend sends nothing, but we need to detect disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)


# ─── Drone Dispatch Helper ────────────────────────────────────────────────────
def _dispatch_drone_to_target(sim, tx: int, ty: int, reason: str,
                               source_drone=None, label: str = "VOICE") -> bool:
    """
    Select best drone and reroute it to (tx, ty) with full zone handoff.

    Selection priority:
      A) Proximity Rule: source_drone ≤7 cells away AND battery >30% → use directly
      B) Global Nearest: closest active drone with battery >35%, not busy/charging

    Then:
      - Saves zone residual_path and releases the zone (so another drone can resume)
      - Builds diagonal transit path + 3×3 box scan around target
      - Sets voice_override=True for high-intensity thermal scanning on every step
    """
    selected_drone = None
    all_candidates = []

    for d in sim.drones.values():
        if not d.is_active:
            continue
        dist = chebyshev(d.x, d.y, tx, ty)
        eligible = not d.is_waiting_response and not d.is_charging and d.battery > 35
        all_candidates.append((d, dist, eligible))

    # --- A) Proximity Rule ---
    if source_drone is not None:
        dist_src = chebyshev(source_drone.x, source_drone.y, tx, ty)
        if (dist_src <= 7
                and source_drone.battery > 30
                and not source_drone.is_waiting_response
                and not source_drone.is_charging
                and source_drone.is_active):
            selected_drone = source_drone
            sim.log(
                f"🎯 {label} → STAGE 2: PROXIMITY RULE — {selected_drone.id} is "
                f"{dist_src} cells away ({selected_drone.battery:.0f}% battery). Assigning directly.",
                "AI", selected_drone.id
            )

    # --- B) Global Nearest ---
    if selected_drone is None:
        min_dist = 9999
        for d, dist, eligible in all_candidates:
            if eligible and dist < min_dist:
                min_dist = dist
                selected_drone = d

        # Log candidate comparison table
        table_rows = []
        for d, dist, eligible in sorted(all_candidates, key=lambda x: x[1]):
            chosen = "✓ SELECTED" if (selected_drone and d.id == selected_drone.id) else ""
            skip = ""
            if not eligible:
                if d.battery <= 35: skip = "LOW BATT"
                elif d.is_charging: skip = "CHARGING"
                elif d.is_waiting_response: skip = "VICTIM STANDBY"
            table_rows.append(
                f"   {'>>>' if chosen else '   '} {d.id}: dist={dist} batt={d.battery:.0f}% "
                f"status={d.status_label!r}  {skip} {chosen}"
            )
        sim.log(
            f"🧠 {label} → STAGE 2: GLOBAL NEAREST SEARCH\n"
            f"   Candidates for target ({tx},{ty}):\n" + "\n".join(table_rows),
            "AI"
        )

    if selected_drone is None:
        sim.log(
            f"⚠️ {label} DISPATCH FAILED: No eligible drone (battery >35%, not busy) "
            f"for target ({tx},{ty}).", "WARN"
        )
        return False

    # --- Zone Handoff: save residual path and release zone ---
    released_zone_id: Optional[str] = None
    if selected_drone.assigned_zone_id:
        zid = selected_drone.assigned_zone_id
        released_zone_id = zid
        zone_obj = sim.zone.zones.get(zid)
        if zone_obj:
            zone_obj.residual_path = list(selected_drone.path_queue)
            sim.release_zone(zid)
            sim.log(
                f"🔄 HANDOFF: {selected_drone.id} releasing zone {zid}. "
                f"{len(zone_obj.residual_path)} cells saved for resumption.",
                "AI", selected_drone.id
            )
        selected_drone.assigned_zone_id = None
        selected_drone.path_queue = []

    # --- Residual Reservation: assign the released zone to the nearest available drone ---
    if released_zone_id and released_zone_id not in sim.reserved_zones:
        rel_zone = sim.zone.zones.get(released_zone_id)
        if rel_zone and rel_zone.residual_path:
            zone_cx = (rel_zone.sx + rel_zone.ex) // 2
            zone_cy = (rel_zone.sy + rel_zone.ey) // 2
            best_id, best_dist = None, float("inf")
            for cand_id, cand in sim.drones.items():
                if (cand_id == selected_drone.id
                        or not cand.is_active
                        or cand.voice_override
                        or cand.pending_zone_id is not None
                        or cand.is_waiting_response
                        or cand.returning_to_base):
                    continue
                d = chebyshev(cand.x, cand.y, zone_cx, zone_cy)
                if d < best_dist:
                    best_dist, best_id = d, cand_id
            if best_id:
                sim.drones[best_id].pending_zone_id = released_zone_id
                sim.reserved_zones[released_zone_id] = best_id
                sim.log(
                    f"📋 Zone {released_zone_id} residual reserved for {best_id} "
                    f"(covers after finishing current job).",
                    "INFO", best_id
                )

    # Save original position (bookmark for reference)
    selected_drone.original_pos = [int(selected_drone.x), int(selected_drone.y)]

    # --- Build path: diagonal transit to target + 3×3 box scan ---
    curr_x, curr_y = int(selected_drone.x), int(selected_drone.y)
    path: list[list[int]] = []

    # Phase 1: BFS transit to (tx, ty) — avoids lake/hazard cells
    transit = sim.compute_path(curr_x, curr_y, tx, ty)
    path.extend(transit)
    curr_x, curr_y = tx, ty

    # Phase 2: 3×3 box scan around (tx, ty) — 8 surrounding cells clockwise
    for dx, dy in [(-1,-1),(0,-1),(1,-1),(1,0),(1,1),(0,1),(-1,1),(-1,0)]:
        nx, ny = tx + dx, ty + dy
        if 0 <= nx < sim.zone.width and 0 <= ny < sim.zone.height:
            if not sim.is_inaccessible(nx, ny):
                path.append([nx, ny])

    # --- Apply: override current mission entirely ---
    selected_drone.path_queue = path
    selected_drone.target_x = tx
    selected_drone.target_y = ty
    selected_drone.voice_override = True   # high-intensity scan on every step
    selected_drone.returning_to_base = False
    selected_drone.is_charging = False
    selected_drone.is_waiting_response = False
    selected_drone.status = "ON_MISSION"
    selected_drone.status_label = f"{label}→({tx},{ty})"

    sim.log(
        f"🚁 {label} → STAGE 3: DEPLOY (3×3 Expansion)\n"
        f"   Drone: {selected_drone.id} | Target: ({tx},{ty}) | "
        f"Steps: {len(path)} | High-Intensity Scan: ACTIVE",
        "AI", selected_drone.id
    )
    return True


@app.post("/victim-response")
async def victim_response(drone_id: str, operator_message: Optional[str] = None):
    """
    Operator confirms rescue. Returns immediately; intel + triage run in background.
    If operator_message contains coordinates, a second drone is dispatched to that location.
    """
    sim = shared.sim
    drone = sim.drones.get(drone_id)
    if not drone:
        return {"error": f"Drone {drone_id} not found"}

    # Capture victim context before clearing
    victim_ctx = drone.victim_report or "Unknown situation"

    # Immediately rescue and release the drone so the frontend popup closes
    result = sim.rescue_victim(drone_id)
    drone.is_waiting_response = False
    drone.victim_report = None

    # Keep drone at scene until agent or intel gives it a new assignment
    if not drone.voice_override:
        drone.target_x = None
        drone.target_y = None
        drone.returning_to_base = False
        drone.status_label = "RESUMING"

    # Process operator message in background (coord extraction + triage)
    if operator_message and operator_message.strip():
        asyncio.create_task(_background_victim_intel(drone_id, operator_message, victim_ctx))

    return {"status": "Rescue confirmed", "result": result}


async def _background_victim_intel(drone_id: str, operator_message: str, victim_ctx: str):
    """
    Background task: parse operator message for coordinates and run triage.
    Part A — Extract coordinates → dispatch nearest drone via _dispatch_drone_to_target()
    Part B — Run triage AI in parallel
    """
    import llm_gateway
    sim = shared.sim
    drone = sim.drones.get(drone_id)

    sim.log(
        f"🎙️ INTEL → STAGE 1: BACKGROUND PROCESSING\n"
        f"   Drone: {drone_id} | Message: '{operator_message}'",
        "VERBAL", drone_id
    )

    # --- Part A: Coordinate Extraction ---
    try:
        parse_prompt = (
            f"You are a rescue grid dispatcher AI.\n"
            f"An operator entered this message: '{operator_message}'\n"
            "\n"
            "TASK: Extract any grid coordinate reference from the message.\n"
            "Grid is 20 wide (x: 0-19), 15 tall (y: 0-14).\n"
            "\n"
            "COORDINATE FORMAT RULES — apply strictly in order:\n"
            "1. PRIMARY: 'X and Y' → treat as coordinate [X, Y]\n"
            "   '19 and 14' → [19,14]  |  '0 and 10' → [0,10]\n"
            "2. Two bare integers separated by space or comma: [X, Y]\n"
            "   '19 14' → [19,14]  |  '19,14' → [19,14]\n"
            "3. 'grid N' (N is 0-299): x = N % 20, y = N // 20\n"
            "4. '(X,Y)' bracket notation: map directly\n"
            "5. Vague ('middle', 'north', 'sector N'): infer closest grid cell\n"
            "\n"
            "Return ONLY valid JSON:\n"
            "  {\"target\": [x, y], \"reason\": \"brief explanation\"}\n"
            "  {} if message contains NO number references at all"
        )
        p_resp = await asyncio.wait_for(
            asyncio.to_thread(
                llm_gateway.completion,
                messages=[{"role": "user", "content": parse_prompt}]
            ),
            timeout=30.0,
        )
        json_str = p_resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(json_str)

        if data.get("target"):
            tx, ty = int(data["target"][0]), int(data["target"][1])
            tx = max(0, min(sim.zone.width - 1, tx))
            ty = max(0, min(sim.zone.height - 1, ty))
            reason = data.get("reason", "Operator-reported coordinate")

            # Redirect if target is a hazard cell
            if sim.is_inaccessible(tx, ty):
                accessible = sim.get_unscanned_cells()
                if accessible:
                    nearest_safe = min(accessible, key=lambda c: chebyshev(c[0], c[1], tx, ty))
                    old_tx, old_ty = tx, ty
                    tx, ty = nearest_safe[0], nearest_safe[1]
                    sim.log(f"⚠️ ({old_tx},{old_ty}) is a hazard — redirecting to ({tx},{ty}).", "WARN")

            sim.log(
                f"🧠 INTEL → STAGE 1 RESULT: Parsed '{operator_message}'\n"
                f"   → Target: ({tx},{ty}) | Reason: {reason}",
                "AI", drone_id
            )
            _dispatch_drone_to_target(sim, tx, ty, reason, source_drone=drone, label="INTEL")
        else:
            sim.log(f"⚠️ INTEL: No coordinates found in '{operator_message}'.", "AI", drone_id)

    except Exception as e:
        sim.log(f"❌ INTEL PARSE ERROR: {type(e).__name__}: {e}", "AI", drone_id)

    # --- Part B: Triage Analysis ---
    try:
        triage_prompt = (
            f"EMERGENCY TRIAGE. Case: '{victim_ctx}'. Operator said: '{operator_message}'. "
            "Give exactly ONE sentence: triage priority (P1/P2/P3) and recommended next action."
        )
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                llm_gateway.completion,
                messages=[{"role": "user", "content": triage_prompt}]
            ),
            timeout=30.0,
        )
        sim.log(f"🏥 TRIAGE AI: {resp.choices[0].message.content.strip()}", "AI", drone_id)
    except Exception as e:
        sim.log(f"❌ TRIAGE AI ERROR: {type(e).__name__}: {e}", "AI", drone_id)


@app.post("/guide-victim")
async def guide_victim(drone_id: str):
    """Command a drone to guide a mobile survivor to base."""
    result = shared.sim.guide_victim(drone_id)
    return {"status": "ok", "result": result}


@app.post("/timeline")
async def post_timeline(
    tick: int,
    kind: str,
    brain: str = "CLOUD",
    duration_ms: float = 0.0,
    payload: str = "{}"
):
    """Agent posts structured timeline events."""
    import json as _json
    from datetime import datetime
    from simulation import TimelineEvent
    sim = shared.sim
    sim._timeline_counter += 1
    ev = TimelineEvent(
        id=f"T{sim._timeline_counter:05d}",
        tick=tick,
        ts=datetime.utcnow().isoformat(),
        kind=kind,
        brain=brain,
        duration_ms=duration_ms,
        payload=_json.loads(payload) if payload else {},
    )
    sim.timeline.append(ev)
    if len(sim.timeline) > sim._timeline_cap:
        sim.timeline = sim.timeline[-sim._timeline_cap:]
    return {"status": "ok", "id": ev.id}


@app.post("/metrics/planning-latency")
async def record_planning_latency(ms: float):
    shared.sim.metrics.record_planning_latency(ms)
    return {"status": "ok"}


@app.post("/radio-intel")
async def radio_intel(lang: str, text: str):
    """
    Field responder relays natural-language survivor intel.
    Translates + grounds asynchronously; returns lead_id immediately.
    """
    sim = shared.sim
    sim._lead_counter += 1
    lead_id = f"L{sim._lead_counter:04d}"
    # Store as PENDING_GROUND immediately so frontend can show it
    from simulation import Lead
    lead = Lead(
        id=lead_id,
        tick=sim.tick_count,
        lang=lang,
        raw=text,
        english="",
        x=None,
        y=None,
        urgency="STABLE",
        status="PENDING_GROUND",
    )
    sim.leads.append(lead)
    asyncio.create_task(_background_ground_lead(lead_id, lang, text))
    return {"status": "received", "lead_id": lead_id}


async def _background_ground_lead(lead_id: str, lang: str, text: str):
    """Ground the lead asynchronously and update shared state."""
    import radio as radio_mod
    sim = shared.sim
    lead = next((l for l in sim.leads if l.id == lead_id), None)
    if lead is None:
        return
    try:
        result = await asyncio.to_thread(radio_mod.translate_and_ground, lang, text)
        lead.english = result["english"]
        lead.x = result["x"]
        lead.y = result["y"]
        lead.urgency = result["urgency"]
        lead.status = result["status"]
        sim.log(
            f"📻 RADIO INTEL [{lead_id}] [{lang}] → {result['status']}: "
            f"'{result['english']}' @ ({result['x']},{result['y']}) [{result['urgency']}]",
            "AI"
        )
    except Exception as e:
        lead.status = "UNGROUNDED"
        print(f"[RADIO] Grounding error for {lead_id}: {e}", file=sys.stderr)


@app.get("/export-mission")
async def export_mission():
    """Return path and size of latest mission JSONL report."""
    reports_dir = Path(__file__).parent.parent / "mission_reports"
    if not reports_dir.exists():
        return {"status": "no_reports", "path": None}
    files = sorted(reports_dir.glob("*.jsonl"))
    if not files:
        return {"status": "no_reports", "path": None}
    latest = files[-1]
    return {"status": "ok", "path": str(latest), "size_bytes": latest.stat().st_size}


@app.get("/missions/current/export")
async def export_current_mission():
    """Download the current mission JSONL tick log."""
    from pathlib import Path
    from fastapi.responses import FileResponse
    reports_dir = Path(__file__).parent.parent / "mission_reports"
    files = sorted(reports_dir.glob("*.jsonl")) if reports_dir.exists() else []
    if not files:
        return {"error": "No mission reports available"}
    latest = files[-1]
    return FileResponse(
        path=str(latest),
        media_type="application/jsonlines",
        filename=latest.name,
    )


# ─── MCP Tools ────────────────────────────────────────────────────────────────
from mcp_tools import register_tools
register_tools(mcp)


# ─── FastAPI background thread runner ─────────────────────────────────────────
def run_fastapi():
    """Runs the FastAPI server in a daemon thread with its own event loop."""
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Start FastAPI in a background daemon thread
    api_thread = threading.Thread(target=run_fastapi, daemon=True)
    api_thread.start()
    print("[SENTINEL] FastAPI running on http://127.0.0.1:8000", file=sys.stderr)
    print("[SENTINEL] FastMCP listening on stdio...", file=sys.stderr)

    # Run FastMCP on main thread (uses stdio for MCP protocol)
    mcp.run()
