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

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

import shared
from simulation import SimulationState, ZoneStatus, chebyshev, LOW_BATTERY_THRESHOLD

# ─── FastMCP Server ────────────────────────────────────────────────────────────
mcp = FastMCP("DroneCommandServer")

SIM_TICK = 0.7  # seconds between simulation steps


# ─── Simulation Tick Loop (Loop A) ────────────────────────────────────────────
async def run_simulation_loop():
    """Advances the simulation one step at a time. No AI logic — handled by agent via MCP."""
    while True:
        sim = shared.sim
        if sim.mission_active:
            sim.simulate_heartbeats()
            base_x, base_y = sim.base_station

            # Mission completion check
            survivors = sim.zone.survivors
            if survivors and all(s["rescued"] for s in survivors):
                sim.log("🏁 MISSION ACCOMPLISHED — All survivors extracted!", "SUCCESS")
                coverage = sim.get_status()["stats"]["coverage_pct"]
                sim.log(
                    f"📊 Final Stats: Coverage {coverage}% | "
                    f"Rescued {sim.total_rescued}/{len(survivors)} survivors",
                    "SUCCESS",
                )
                for drone in sim.drones.values():
                    drone.base_x, drone.base_y = base_x, base_y
                    if (drone.x, drone.y) != (base_x, base_y):
                        drone.target_x, drone.target_y = base_x, base_y
                        drone.returning_to_base = True
                        drone.mission_complete_rtb = True
                        drone.status = "RETURNING"
                        drone.status_label = "RTB — COMPLETE"
                sim.mission_active = False

            # Loop A: advance each drone one step
            if sim.mission_active:
                # Process pending commands if drones are available
                if hasattr(sim, 'pending_intel') and sim.pending_intel:
                    has_eligible = any(
                        not d.is_waiting_response and not d.is_charging and d.battery > 35
                        for d in sim.drones.values()
                    )
                    if has_eligible:
                        qi = sim.pending_intel[0]
                        success = _dispatch_drone_to_target(sim, qi["tx"], qi["ty"], qi["reason"], source_drone=None, label=qi["label"])
                        if success:
                            sim.pending_intel.pop(0)

                for d_id, drone in list(sim.drones.items()):
                    try:
                        drone.base_x, drone.base_y = base_x, base_y

                        # Skip logic if drone is not connected (Detection realism)
                        if not drone.is_connected:
                            continue

                        # Victim standby — drone waits for operator
                        if drone.is_waiting_response:
                            drone.status = "IDLE"
                            drone.status_label = "VICTIM STANDBY"
                            continue

                        # Auto-charge at base: If you are at base and not full, charge.
                        if (drone.x, drone.y) == (base_x, base_y) and drone.battery < 100:
                            if not drone.is_charging:
                                sim.log(f"🤖 {d_id} arrived at base. Commencing recharge.", "INFO", d_id)
                            sim.charge_step(d_id)
                            if not drone.is_charging:
                                drone.returning_to_base = False
                            else:
                                continue

                        # No target and empty path — awaiting zone assignment from agent
                        if drone.target_x is None and not drone.path_queue:
                            drone.status = "IDLE"
                            drone.status_label = "AWAITING ORDERS"
                            if drone.assigned_zone_id:
                                zid = drone.assigned_zone_id
                                if zid in sim.zone.zones:
                                    if sim.is_zone_fully_scanned(zid):
                                        sim.zone.zones[zid].status = ZoneStatus.COMPLETE
                                        sim.log(f"✅ Zone {zid} search complete.", "SUCCESS", d_id)
                                    else:
                                        # Zone not finished (e.g. low battery RTB or victim found)
                                        # Save whatever was left in the path as residual for next drone
                                        sim.zone.zones[zid].residual_path = list(drone.path_queue)
                                        sim.release_zone(zid)
                                        sim.log(f"🔄 Zone {zid} released for resumption — coverage partial.", "INFO", d_id)
                                drone.assigned_zone_id = None

                            # --- PASSIVE RECALL LOGIC ---
                            remaining_zones = sim.get_available_zones()
                            if drone.battery < 35.0 or not remaining_zones:
                                if (drone.x, drone.y) == (base_x, base_y):
                                    drone.status = "IDLE"
                                    drone.status_label = "STANDBY"
                                    drone.returning_to_base = False
                                    drone.target_x = None
                                    drone.target_y = None
                                else:
                                    drone.target_x, drone.target_y = base_x, base_y
                                    drone.returning_to_base = True
                                    drone.status = "RETURNING"
                                    drone.status_label = "AUTO-RECALL" if not remaining_zones else "PASSIVE RTB"
                                    sim.log(f"🔄 {d_id} auto-initiating RTB (Battery: {drone.battery:.1f}%, Missions: {len(remaining_zones)} left)", "INFO", d_id)
                            
                            continue

                        # Movement: use path_queue if available, else step toward target_x/y
                        tx, ty = drone.x, drone.y
                        if drone.path_queue:
                            # Safe pop to avoid race conditions with agent thread
                            if len(drone.path_queue) > 0:
                                nx, ny = drone.path_queue.pop(0)
                                tx, ty = nx, ny
                            else:
                                nx, ny = drone.x, drone.y
                        else:
                            tar_x, tar_y = drone.target_x, drone.target_y
                            nx, ny = drone.x, drone.y
                            # Check for None before movement calcs to avoid TypeError
                            if tar_x is not None and tar_y is not None:
                                if nx != tar_x:
                                    nx += 1 if tar_x > nx else -1
                                elif ny != tar_y:
                                    ny += 1 if tar_y > ny else -1
                                tx, ty = tar_x, tar_y
                            else:
                                nx, ny = drone.x, drone.y
                                tx, ty = nx, ny

                        # Arrived at current step target
                        if (drone.x, drone.y) == (nx, ny) and not drone.path_queue:
                            if nx == base_x and ny == base_y:
                                drone.returning_to_base = False
                                drone.target_x = None
                                drone.target_y = None
                                sim.log(f"🤖 {d_id} reached base station. Commencing recharge.", "INFO", d_id)
                                sim.charge_step(d_id)
                            else:
                                # Standard autonomous scan logic
                                result = sim.scan(d_id)
                                if "THERMAL MATCH" not in result and "VICTIM_DETECTED" not in result:
                                    drone.target_x = None
                                    drone.status_label = "SCANNED"
                                else:
                                    sim.log(f"🔍 {d_id} found something at ({drone.x},{drone.y})! Waiting for operator.", "INFO", d_id)
                                
                            if drone.voice_override:
                                sim.log(f"✅ {d_id} diversion complete. Treating as Free Agent to optimize battery.", "SUCCESS", d_id)
                                drone.voice_override = False
                                drone.original_pos = None
                                drone.target_x = None
                                drone.target_y = None
                                drone.status = "IDLE"
                                drone.status_label = "AWAITING ORDERS"
                                continue

                            # CRITICAL: If no path remains and we have no target, we MUST be IDLE
                            if not drone.path_queue and drone.target_x is None:
                                drone.status = "IDLE"
                                drone.status_label = "AWAITING ORDERS"
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

                        # Battery drain
                        drone.battery = max(0.0, drone.battery - 1.0)
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
                                sim.zone.zones[zid].residual_path = list(drone.path_queue)
                                sim.release_zone(zid)
                                sim.log(f"⚠️ {d_id} battery {drone.battery:.0f}%: Reserving {len(drone.path_queue)} points in {zid} for handle-off.", "WARN", d_id)
                                drone.assigned_zone_id = None

                            drone.path_queue = []
                            drone.target_x, drone.target_y = base_x, base_y
                            drone.returning_to_base = True
                            drone.status = "RETURNING"
                            sim.log(f"🪫 {d_id} battery {drone.battery:.0f}% critical. Initiating RTB.", "WARN", d_id)

                        # Opportunistic scan
                        if not sim.zone.scanned_cells[ny][nx] or drone.voice_override:
                            scan_res = sim.scan(d_id)
                            if "THERMAL MATCH" in scan_res or "VICTIM_DETECTED" in scan_res:
                                if drone.assigned_zone_id:
                                    zid = drone.assigned_zone_id
                                    sim.zone.zones[zid].residual_path = list(drone.path_queue)
                                    sim.log(f"🔍 {d_id} found victim at ({nx},{ny}). Saved residual path for zone {zid}.", "INTEL", d_id)

                                drone.path_queue = []
                                drone.target_x = None
                                drone.target_y = None
                    except Exception as e:
                        sim.log(f"❌ INTERNAL ERROR (DRONE {d_id}): {e}", "ERROR")

        await asyncio.sleep(SIM_TICK)

        await asyncio.sleep(SIM_TICK)


# ─── FastAPI App ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate LLM gateway at startup — surface bad API keys or model names immediately
    import sys
    try:
        import llm_gateway
        _, model_name = llm_gateway.get_client()
        print(f"[STARTUP] ✅ LLM gateway ready — model: {model_name}", file=sys.stderr, flush=True)
        shared.sim.log(f"🟢 LLM Gateway ready. Model: {model_name}", "AI")
    except Exception as e:
        print(f"[STARTUP] ⚠️ LLM gateway failed: {e}", file=sys.stderr, flush=True)
        print("[STARTUP] Voice commands will use rule-based fallback only.", file=sys.stderr, flush=True)
        shared.sim.log(f"🔴 LLM Gateway FAILED: {e}. Voice commands disabled.", "AI")

    loop_task = asyncio.create_task(run_simulation_loop())
    yield
    loop_task.cancel()


app = FastAPI(
    title="RescueSwarm API",
    description="First Responder Swarm Intelligence — MCP + FastAPI",
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
    sim.log("═══ RESCUE SWARM INTELLIGENCE ACTIVATED ═══", "SUCCESS")
    sim.log("📡 MCP channel open | 🛰️ Fleet online | 🧠 SENTINEL AI ready", "INFO")
    return {
        "status": "SWARM DEPLOYED — SENTINEL AI + MCP Active",
        "drones": list(sim.drones.keys()),
        "running": True,
    }


@app.post("/stop-mission")
async def stop_mission():
    """Halt the active search mission."""
    shared.sim.mission_active = False
    shared.sim.log("🛑 MISSION HALTED BY OPERATOR", "WARN")
    return {"status": "Mission stopped"}


@app.post("/reset")
async def reset_mission(num_victims: int = 0):
    """Reset simulation and reinitialize with new disaster layout."""
    shared.sim = SimulationState(num_victims=num_victims)
    return {"status": "Simulation reset — new disaster zone generated"}


@app.post("/log")
async def add_log(text: str, level: str = "AI", drone_id: Optional[str] = None):
    """Agent posts its reasoning here to appear in the mission log."""
    shared.sim.log(text, level, drone_id)
    return {"status": "Logged"}


@app.post("/victim-response")
async def victim_response(drone_id: str, operator_message: Optional[str] = None):
    """
    Operator confirms rescue and optionally sends triage message.
    UI is released immediately; AI parses intel in a background task.
    """
    sim = shared.sim
    drone = sim.drones.get(drone_id)
    if not drone:
        return {"error": f"Drone {drone_id} not found"}

    # 1. Capture the victim report before we clear it
    victim_ctx = drone.victim_report or "Unknown situation"

    # 2. Immediately execute rescue and release the "waiting" state
    # This ensures the frontend popup closes and the drone is technically 'available'
    result = sim.rescue_victim(drone_id)
    drone.is_waiting_response = False
    drone.victim_report = None
    
    # Release the drone's current target so it stays at the scene 
    # until the background intel processing (or Loop B) gives it a new one.
    if not drone.voice_override:
        drone.target_x = None
        drone.target_y = None
        drone.returning_to_base = False
        drone.status_label = "RESUMING"

    # 3. Process the operator message in the background if it exists
    if operator_message and operator_message.strip():
        asyncio.create_task(
            _background_victim_intel(drone_id, operator_message, victim_ctx)
        )

    return {"status": "Rescue confirmed; UI released", "result": result}


async def _background_victim_intel(drone_id: str, operator_message: str, victim_ctx: str):
    """Processes intel extracted from a survivor's conversation in the background."""
    import llm_gateway
    import json
    sim = shared.sim
    drone = sim.drones.get(drone_id)

    sim.log(
        f"🎙️ INTEL → STAGE 1: BACKGROUND PROCESSING\n"
        f"   Drone: {drone_id} | Message: '{operator_message}'",
        "VERBAL", drone_id
    )

    # --- PART A: COORDINATE EXTRACTION ---
    try:
        parse_prompt = (
            f"You are a rescue grid dispatcher AI.\n"
            f"An operator entered this message: '{operator_message}'\n"
            "\n"
            "TASK: Extract any grid coordinate reference from the message.\n"
            "The operator may be directing a drone to a location, OR reporting where\n"
            "another survivor is. Treat ALL coordinate patterns the same way.\n"
            "\n"
            "Grid is 20 wide (x: 0-19), 15 tall (y: 0-14).\n"
            "\n"
            "COORDINATE FORMAT RULES — apply strictly in order:\n"
            "1. PRIMARY: 'X and Y' → ALWAYS treat as coordinate [X, Y]\n"
            "   '19 and 14' → [19, 14]  |  '0 and 10' → [0, 10]  |  '5 and 3' → [5, 3]\n"
            "2. Two bare integers separated by space or comma: treat as [X, Y]\n"
            "   '19 14' → [19, 14]  |  '19,14' → [19, 14]\n"
            "3. 'grid N' (N is 0-299): x = N % 20, y = N // 20\n"
            "4. '(X,Y)' bracket notation: map directly\n"
            "5. Vague ('middle', 'sector N', 'north'): infer closest grid cell\n"
            "\n"
            "IMPORTANT: If the message contains ANY two numbers, extract them as coordinates.\n"
            "\n"
            "Return ONLY valid JSON:\n"
            "  {\"target\": [x, y], \"reason\": \"brief explanation\"}\n"
            "  {} (only if message contains NO number references at all)"
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
            
            sim.log(
                f"🧠 INTEL → STAGE 1 RESULT: Parsed '{operator_message}'\n"
                f"   → Coordinate: ({tx},{ty}) | Reason: {reason}",
                "AI", drone_id
            )
            # Dispatch (this will override whatever the drone is doing now)
            success = _dispatch_drone_to_target(sim, tx, ty, reason, source_drone=drone, label="INTEL")
            if not success:
                if not hasattr(sim, 'pending_intel'): sim.pending_intel = []
                sim.pending_intel.append({
                    "tx": tx, "ty": ty, "reason": reason, "label": "INTEL", 
                    "operator_message": operator_message
                })
                sim.log(f"📌 Task queued: ({tx},{ty}) added to pending list.", "INFO")
        else:
            sim.log(f"⚠️ INTEL: AI could not extract coordinates from '{operator_message}'.", "AI", drone_id)
    except Exception as e:
        sim.log(f"❌ **INTEL PARSING ERROR**: {type(e).__name__}: {e}", "AI", drone_id)

    # --- PART B: TRIAGE ANALYSIS ---
    try:
        triage_prompt = (
            f"EMERGENCY TRIAGE. Case: '{victim_ctx}'. Victim said: '{operator_message}'. "
            "Give exactly ONE sentence: triage priority (P1/P2/P3) and next action."
        )
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                llm_gateway.completion,
                messages=[{"role": "user", "content": triage_prompt}]
            ),
            timeout=40.0,
        )
        sim.log(f"🏥 TRIAGE AI: {resp.choices[0].message.content.strip()}", "AI", drone_id)
    except Exception as e:
        sim.log(f"❌ **TRIAGE AI ERROR**: {type(e).__name__}: {e}", "AI", drone_id)



@app.post("/guide-victim")
async def guide_victim(drone_id: str):
    """Command a drone to guide the mobile survivor at its location to base."""
    result = shared.sim.guide_victim(drone_id)
    return {"status": "Guide command issued", "result": result}


def _dispatch_drone_to_target(sim, tx: int, ty: int, reason: str, source_drone=None, label: str = "VOICE"):
    """
    Shared dispatch helper — selects the best drone and reroutes it to (tx, ty).

    Implements the full Dynamic Dispatch spec:
      A) Proximity Rule: if source_drone is ≤7 cells away AND battery >30% → use it directly
      B) Global Nearest: otherwise find closest drone with battery >35%, not busy/charging
      - Handoff Protocol: preserve zone residual_path before diverting
      - State Restoration (Option B): save Resume Point; drone auto-returns after scan
      - Push to Front: path_queue is replaced entirely, giving voice/intel absolute priority
      - High-Intensity Scanning: voice_override=True makes drone scan EVERY step of diversion
    """
    selected_drone = None
    all_candidates = []

    # Snapshot every drone for the selection log
    for d in sim.drones.values():
        dist = chebyshev(d.x, d.y, tx, ty)
        eligible = (
            not d.is_waiting_response
            and not d.is_charging
            and d.battery > 35
        )
        all_candidates.append((d, dist, eligible))

    # --- A) Proximity Rule ---
    if source_drone is not None:
        dist_src = chebyshev(source_drone.x, source_drone.y, tx, ty)
        if (dist_src <= 7
                and source_drone.battery > 30
                and not source_drone.is_waiting_response
                and not source_drone.is_charging):
            selected_drone = source_drone
            sim.log(
                f"🎯 {label} → STAGE 2: PROXIMITY RULE triggered.\n"
                f"   Discovering drone {selected_drone.id} is only {dist_src} cells away  "
                f"and has {selected_drone.battery:.0f}% battery (>30%). Assigning directly.",
                "AI", selected_drone.id
            )

    # --- B) Global Nearest ---
    if selected_drone is None:
        min_dist = 9999
        for d in sim.drones.values():
            if d.is_waiting_response or d.is_charging:
                continue
            if d.battery <= 35:
                continue
            dist = chebyshev(d.x, d.y, tx, ty)
            if dist < min_dist:
                min_dist = dist
                selected_drone = d

        # Log full candidate comparison table
        table_rows = []
        for d, dist, eligible in sorted(all_candidates, key=lambda x: x[1]):
            chosen = "✓ SELECTED" if (selected_drone and d.id == selected_drone.id) else ""
            reason_skip = ""
            if not eligible:
                if d.battery <= 35: reason_skip = "LOW BATT"
                elif d.is_charging: reason_skip = "CHARGING"
                elif d.is_waiting_response: reason_skip = "VICTIM STANDBY"
            table_rows.append(
                f"   {'>>>' if chosen else '   '} {d.id}: dist={dist} cells, batt={d.battery:.0f}%, "
                f"status={d.status_label!r}  {reason_skip} {chosen}"
            )
        table_str = "\n".join(table_rows)

        if selected_drone:
            sim.log(
                f"🧠 {label} → STAGE 2: GLOBAL NEAREST SEARCH\n"
                f"   Candidate comparison for target ({tx},{ty}):\n"
                f"{table_str}",
                "AI"
            )
        else:
            sim.log(
                f"🧠 {label} → STAGE 2: GLOBAL NEAREST SEARCH  (ALL FAILED)\n"
                f"   Candidate comparison for target ({tx},{ty}):\n"
                f"{table_str}",
                "AI"
            )

    if selected_drone is None:
        sim.log(
            f"⚠️ {label} DISPATCH FAILED: No drone available (battery ≥35%, not busy) "
            f"to reach target ({tx},{ty}).",
            "WARN"
        )
        return False

    # --- Handoff Protocol: release zone and save residual path ---
    if selected_drone.assigned_zone_id:
        zid = selected_drone.assigned_zone_id
        zone_obj = sim.zone.zones.get(zid)
        if zone_obj:
            zone_obj.residual_path = list(selected_drone.path_queue)
            sim.release_zone(zid)
            sim.log(
                f"🔄 HANDOFF: {selected_drone.id} released zone {zid}. "
                f"{len(zone_obj.residual_path)} cells saved — zone re-queued for resumption.",
                "AI", selected_drone.id
            )
        selected_drone.assigned_zone_id = None
        selected_drone.path_queue = []

    # --- State Restoration (Option B): bookmark current position as Resume Point ---
    selected_drone.original_pos = [int(selected_drone.x), int(selected_drone.y)]

    # --- Tactical Path Generation: 3x3 Tactical Expansion ---
    curr_x, curr_y = int(selected_drone.x), int(selected_drone.y)
    to_target_path = []
    
    # Phase 1: Transit to target
    while (curr_x, curr_y) != (tx, ty):
        if curr_x < tx:   curr_x += 1
        elif curr_x > tx: curr_x -= 1
        if curr_y < ty:   curr_y += 1
        elif curr_y > ty: curr_y -= 1
        to_target_path.append([curr_x, curr_y])
    
    # Phase 2: 3x3 Box Scan around (tx, ty) for "Tactical Expansion"
    # Spiral/Box offsets (skipping center (0,0) as it's the target)
    offsets = [(-1,-1), (0,-1), (1,-1), (1,0), (1,1), (0,1), (-1,1), (-1,0)]
    for dx, dy in offsets:
        nx, ny = tx + dx, ty + dy
        if 0 <= nx < sim.zone.width and 0 <= ny < sim.zone.height:
            if not sim.is_inaccessible(nx, ny):
                to_target_path.append([nx, ny])

    # --- Push to Front: override current mission entirely ---
    selected_drone.path_queue = to_target_path
    selected_drone.target_x = tx
    selected_drone.target_y = ty
    selected_drone.voice_override = True    # enables High-Intensity Scanning on every step
    selected_drone.returning_to_base = False
    selected_drone.is_charging = False
    selected_drone.is_waiting_response = False
    selected_drone.status = "ON_MISSION"
    selected_drone.status_label = f"{label} → ({tx},{ty})"

    rp = selected_drone.original_pos
    sim.log(
        f"🚁 {label} → STAGE 3: DEPLOY (3x3 Expansion)\n"
        f"   Drone: {selected_drone.id} | Target: ({tx},{ty}) | Total Steps: {len(to_target_path)}\n"
        f"   Strategy: Tactical Expansion active. High-Intensity Thermal Scan: ACTIVE",
        "AI", selected_drone.id
    )
    return True
    return True


@app.post("/voice-command")
async def voice_command(message: str):
    """
    Global voice command endpoint.
    Returns immediately; processing happens in the background.
    """
    sim = shared.sim

    # Auto-activate mission so drones actually move
    if not sim.mission_active:
        sim.mission_active = True
        sim.mission_start_time = time.time()
        sim.log("🔔 Mission auto-activated by voice command.", "INFO")

    asyncio.create_task(_background_voice_command(message))
    return {"status": "Command received; processing in background"}


async def _background_voice_command(message: str):
    """Processes global voice commands in the background."""
    import llm_gateway
    import json
    sim = shared.sim

    sim.log(
        f"🎙️ VOICE → STAGE 1: BACKGROUND PROCESSING\n"
        f"   Raw input: '{message}'",
        "VERBAL"
    )

    try:
        parse_prompt = (
            f"You are a rescue dispatcher AI. The operator said: '{message}'.\n"
            "Extract the target grid coordinates.\n"
            "Grid: 20 wide (x: 0-19), 15 tall (y: 0-14).\n"
            "\n"
            "COORDINATE FORMAT RULES — apply in order:\n"
            "1. PRIMARY FORMAT — 'X and Y': first number = X, second number = Y.\n"
            "   '0 and 10' → [0, 10]   '10 and 0' → [10, 0]   '5 and 12' → [5, 12]\n"
            "2. 'grid N' (N is 0-299): x = N % 20, y = N // 20\n"
            "3. '(X,Y)' or 'X,Y' or 'X Y' (two numbers): map directly to [X, Y]\n"
            "4. Vague ('middle', 'sector', 'north'): infer best [x, y]\n"
            "\n"
            "If coordinates found: return JSON {\"target\": [x, y], \"reason\": \"brief explanation\"}\n"
            "If no coordinates: return {}"
        )
        p_resp = await asyncio.wait_for(
            asyncio.to_thread(
                llm_gateway.completion,
                messages=[{"role": "user", "content": parse_prompt}]
            ),
            timeout=30.0,
        )
        resp_content = p_resp.choices[0].message.content.strip()
        json_str = resp_content.replace("```json", "").replace("```", "").strip()
        data = json.loads(json_str)

        if data.get("target"):
            tx, ty = int(data["target"][0]), int(data["target"][1])
            tx = max(0, min(sim.zone.width - 1, tx))
            ty = max(0, min(sim.zone.height - 1, ty))

            # Hazard redirect
            if sim.is_inaccessible(tx, ty):
                accessible_cells = sim.get_unscanned_cells()
                if accessible_cells:
                    nearest_safe = min(
                        accessible_cells,
                        key=lambda c: chebyshev(c[0], c[1], tx, ty),
                    )
                    old_tx, old_ty = tx, ty
                    tx, ty = nearest_safe[0], nearest_safe[1]
                    sim.log(f"⚠️ ({old_tx},{old_ty}) is a hazard. Redirecting to nearest safe cell ({tx},{ty}).", "WARN")

            reason = data.get("reason", "Voice instruction")
            sim.log(
                f"🧠 VOICE → STAGE 1 RESULT: Parsed '{message}'\n"
                f"   → Target coordinate: ({tx},{ty}) | Reason: {reason}",
                "AI"
            )
            success = _dispatch_drone_to_target(sim, tx, ty, reason, source_drone=None, label="VOICE")
            if not success:
                if not hasattr(sim, 'pending_intel'): sim.pending_intel = []
                sim.pending_intel.append({
                    "tx": tx, "ty": ty, "reason": reason, "label": "VOICE", 
                    "operator_message": message
                })
                sim.log(f"📌 Task queued: ({tx},{ty}) added to pending list.", "INFO")
        else:
            sim.log(f"⚠️ VOICE: AI could not extract coordinates from: '{message}'", "WARN")

    except Exception as e:
        sim.log(f"❌ **VOICE COMMAND AI ERROR**: {type(e).__name__}: {e}", "AI")

        return {"error": str(e)}


# ─── MCP Tools (used by agent/agent.py via LangChain) ─────────────────────────

@mcp.tool()
def list_drones() -> str:
    """Returns a list of all active drone IDs on the network."""
    drones = list(shared.sim.drones.keys())
    return f"Active Drones: {', '.join(drones)}"


@mcp.tool()
def get_status(drone_id: str) -> str:
    """Gets the current status (battery, location, state) of a specific drone."""
    drone = shared.sim.drones.get(drone_id)
    if not drone:
        return f"Error: Drone {drone_id} not found."
    return (
        f"Status of {drone_id}: Battery={drone.battery:.1f}%, "
        f"Location=({drone.x},{drone.y}), Status={drone.status_label}, "
        f"Charging={drone.is_charging}, Returning={drone.returning_to_base}, "
        f"VictimStandby={drone.is_waiting_response}"
    )


@mcp.tool()
def get_grid_state() -> str:
    """Returns available (unscanned, unclaimed) zones for drone assignment."""
    sim = shared.sim
    available = sim.get_available_zones()
    unscanned_count = len(sim.get_unscanned_cells())
    survivors_found = sim.total_victims_found
    total_survivors = len(sim.zone.survivors)

    if not available:
        return (f"ALL ZONES COMPLETE. Grid {sim.zone.width}x{sim.zone.height}. "
                f"Unscanned cells: {unscanned_count}. "
                f"Survivors Found: {survivors_found}/{total_survivors}.")

    zone_list = []
    for z in available:
        zone_list.append(
            f"  {z['zone_id']}: ({z['sx']},{z['sy']})->({z['ex']},{z['ey']}) "
            f"scan_cost={z['scan_cost']} priority={z['priority']}"
        )
    header = (f"Grid {sim.zone.width}x{sim.zone.height}. Unscanned cells: {unscanned_count}. "
              f"Survivors Found: {survivors_found}/{total_survivors}.\n"
              f"Available Zones ({len(available)}):\n")
    return header + "\n".join(zone_list)


@mcp.tool()
def get_idle_drones() -> str:
    """
    Returns a 'Mission Options Menu' for all idle drones.
    The agent evaluates these options based on battery, priority, and risk,
    then executes the chosen assignments using assign_scan_zone() or return_to_base().
    """
    sim = shared.sim

    # A drone is idle if it has no active assignment and is not in a special state
    idle_drones = [
        (d_id, d) for d_id, d in sim.drones.items()
        if (d.target_x is None
            and not d.path_queue
            and not d.returning_to_base
            and not d.is_charging
            and not d.is_waiting_response)
    ]

    if not idle_drones:
        return "NO_IDLE_DRONES: No drones currently need orders."

    available = sim.get_available_zones()
    survivors_found = sim.total_victims_found
    total_survivors = len(sim.zone.survivors)

    if not available:
        drone_names = ", ".join(d_id for d_id, _ in idle_drones)
        coverage_pct = sim.get_status()["stats"]["coverage_pct"]
        status_msg = "Grid fully searched" if coverage_pct >= 95 else f"Search concluded with {coverage_pct}% coverage"
        return (f"MISSION COMPLETE: {status_msg}. "
                f"Found {survivors_found}/{total_survivors} survivors. "
                f"Drones available for recall: {drone_names}")

    base_x, base_y = sim.base_station
    report = [f"--- MISSION OPTIONS MENU (Found: {survivors_found}/{total_survivors}) ---"]

    for d_id, drone in idle_drones:
        report.append(f"\n[DRONE: {d_id}] Battery: {drone.battery:.1f}% @ ({drone.x},{drone.y})")

        options = []
        for z in available:
            transit = chebyshev(drone.x, drone.y, z["sx"], z["sy"])
            return_cost = abs(z["ex"] - base_x) + abs(z["ey"] - base_y)
            total_needed = transit + z["scan_cost"] + return_cost
            score = (100 if z["priority"] == "HIGH" else 50) - (transit * 1.5)
            options.append({
                "zone_id": z["zone_id"],
                "transit": transit,
                "scan": z["scan_cost"],
                "return": return_cost,
                "total": total_needed,
                "priority": z["priority"],
                "score": score
            })

        options.sort(key=lambda x: x["score"], reverse=True)
        valid_options = [o for o in options if o["total"] <= drone.battery][:3]

        if not valid_options:
            report.append("  * REC: return_to_base() | Battery too low for any zone.")
        else:
            for i, opt in enumerate(valid_options):
                remaining = drone.battery - opt["total"]
                risk = "LOW" if remaining > 20 else ("MEDIUM" if remaining > 10 else "HIGH")
                report.append(
                    f"  Opt {i+1}: assign_scan_zone(\"{d_id}\", \"{opt['zone_id']}\") "
                    f"- Priority={opt['priority']}, Cost={opt['total']}, Risk={risk}"
                )

    return "\n".join(report)


@mcp.tool()
def assign_scan_zone(drone_id: str, zone_id: str) -> str:
    """
    Commands a drone to sweep a pre-defined zone by its zone_id.
    Use get_idle_drones() to see available options first.
    Args:
        drone_id: The ID of the drone (e.g. 'ALPHA-1').
        zone_id: The zone ID to assign (e.g. 'Z0', 'Z1', 'Z2', 'Z3').
    """
    sim = shared.sim
    drone = sim.drones.get(drone_id)
    if not drone:
        return f"Error: Drone {drone_id} not found."

    if drone.is_waiting_response:
        return f"Error: {drone_id} is on VICTIM STANDBY. Cannot reassign."
    if drone.is_charging and drone.battery < 90:
        return f"Error: {drone_id} is charging ({drone.battery:.0f}%). Wait until charged."

    # --- SANITIZE: Strip (RESIDUAL HANDOFF) suffix if it exists ---
    real_zid = zone_id.split(" (RESIDUAL")[0].strip()

    zone = sim.zone.zones.get(real_zid)
    if not zone:
        return f"Error: Zone {zone_id} does not exist (parsed as {real_zid}). Use get_idle_drones() for correct IDs."
    if zone.status != ZoneStatus.UNSCANNED:
        return f"Error: Zone {real_zid} is already {zone.status.value}. Pick a different zone."

    # Use the real ZID for all subsequent logic
    zone_id = real_zid

    # Pre-flight battery validation
    base_x, base_y = sim.base_station
    transit_cost = chebyshev(drone.x, drone.y, zone.sx, zone.sy)
    scan_cost = (zone.ex - zone.sx + 1) * (zone.ey - zone.sy + 1)
    return_cost = abs(zone.ex - base_x) + abs(zone.ey - base_y)
    total_estimated = transit_cost + scan_cost + return_cost

    if drone.battery < total_estimated:
        return (f"Error: {drone_id} has {drone.battery:.1f}% battery but zone {zone_id} "
                f"requires ~{total_estimated:.0f}%. REJECTED. "
                f"Pick a closer zone or call return_to_base(\"{drone_id}\").")

    # Claim zone and generate path queue
    if not sim.claim_zone(zone_id, drone_id):
        return f"Error: Zone {zone_id} was just claimed by another drone. Pick a different zone."

    result = sim.assign_zone(drone_id, zone_id)
    if "error" in result:
        sim.release_zone(zone_id)
        return f"Error: {result['error']}"

    sim.log(f"📡 AGENT DISPATCH: {drone_id} assigned to zone {zone_id}.", "AI", drone_id)
    return f"SUCCESS: {result['message']} (Zone {zone_id} claimed)"


@mcp.tool()
def return_to_base(drone_id: str) -> str:
    """Forces a drone to abort its current mission and return to base."""
    sim = shared.sim
    drone = sim.drones.get(drone_id)
    if not drone:
        return f"Error: Drone {drone_id} not found."

    base_x, base_y = sim.base_station
    if drone.assigned_zone_id:
        sim.release_zone(drone.assigned_zone_id)
        drone.assigned_zone_id = None

    drone.path_queue = []
    drone.target_x, drone.target_y = base_x, base_y
    drone.returning_to_base = True
    drone.status = "RETURNING"
    drone.status_label = "RTB"
    sim.log(f"🔁 AGENT: {drone_id} recalled to base.", "INFO", drone_id)
    return f"Drone {drone_id} is returning to base ({base_x},{base_y})."


# ─── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import copy

    def run_api_server():
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        print("Starting FastAPI server on http://127.0.0.1:8000", file=sys.stderr, flush=True)
        try:
            log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
            log_config["handlers"]["default"]["stream"] = "ext://sys.stderr"
            log_config["handlers"]["access"]["stream"] = "ext://sys.stderr"
            uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info", log_config=log_config)
        except OSError as e:
            if e.errno == 10048:
                print("\n[ERROR] Port 8000 already in use.", file=sys.stderr, flush=True)
            else:
                print(f"[ERROR] {e}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr, flush=True)

    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()

    print("Starting FastMCP stdio server...", file=sys.stderr, flush=True)
    mcp.run()
