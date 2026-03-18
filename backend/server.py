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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

import shared
from simulation import SimulationState, ZoneStatus, chebyshev, LOW_BATTERY_THRESHOLD, BATTERY_RETURN_RESERVE

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
                        drone.target_x, drone.target_y = base_x, base_y
                        drone.returning_to_base = True
                        drone.mission_complete_rtb = True
                        drone.status = "RETURNING"
                        drone.status_label = "RTB — COMPLETE"
                sim.mission_active = False
                sim.mission_end_time = time.time()

            # Loop A: advance each drone one step
            if sim.mission_active:
                for d_id, drone in list(sim.drones.items()):
                    drone.base_x, drone.base_y = base_x, base_y

                    # Victim standby — drone waits for operator
                    if drone.is_waiting_response:
                        drone.status = "IDLE"
                        drone.status_label = "VICTIM STANDBY"
                        continue

                    # Auto-charge at base
                    if (drone.x, drone.y) == (base_x, base_y) and drone.battery < 100 and (
                        drone.returning_to_base or drone.is_charging or drone.battery < LOW_BATTERY_THRESHOLD
                    ):
                        if not drone.is_charging:
                            sim.log(f"🤖 {d_id} arrived at base. Commencing recharge.", "INFO", d_id)
                        sim.charge_step(d_id)
                        if not drone.is_charging:
                            # Charging just completed — clear RTB flag and wait for agent assignment
                            drone.returning_to_base = False
                        continue  # Always skip movement logic while at base charging/post-charge

                    # No target and empty path — awaiting zone assignment from agent
                    if drone.target_x is None and not drone.path_queue:
                        drone.status = "IDLE"
                        drone.status_label = "AWAITING ORDERS"
                        if drone.assigned_zone_id:
                            zid = drone.assigned_zone_id
                            if zid in sim.zone.zones:
                                sim.zone.zones[zid].status = ZoneStatus.COMPLETE
                                sim.log(f"✅ Zone {zid} search complete.", "SUCCESS", d_id)
                            drone.assigned_zone_id = None
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
                            if "THERMAL MATCH" not in result and "VICTIM_DETECTED" not in result:
                                drone.target_x = None

                            # If we just reached the end of an intel interrupt path, log completion
                            if drone.voice_override and not drone.path_queue:
                                sim.log(f"✅ {d_id} completed intel search. Awaiting new orders.", "INFO", d_id)
                                drone.voice_override = False
                                drone.original_pos = None
                                drone.status = "IDLE"

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
                        drone.path_queue = []
                        drone.target_x, drone.target_y = base_x, base_y
                        drone.returning_to_base = True
                        drone.status = "RETURNING"
                        sim.log(f"🪫 {d_id} battery {drone.battery:.0f}% critical. Initiating RTB.", "WARN", d_id)

                    # Opportunistic scan while passing through unscanned cell OR if on high-priority intel mission
                    if not sim.zone.scanned_cells[ny][nx] or drone.voice_override:
                        sim.scan(d_id)

        await asyncio.sleep(SIM_TICK)


# ─── FastAPI App ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
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
    sim.log("🚀 MISSION ACTIVE: Swarm deployed. Awaiting SENTINEL directives.", "SUCCESS")
    return {"status": "Mission started", "running": True}


@app.post("/stop-mission")
async def stop_mission():
    """Halt mission immediately."""
    sim = shared.sim
    sim.mission_active = False
    sim.mission_end_time = time.time()
    sim.log("🛑 MISSION HALTED by operator command.", "WARN")
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


@app.post("/victim-response")
async def victim_response(drone_id: str, operator_message: str = ""):
    """Operator confirms rescue + optional AI triage via llm_gateway."""
    sim = shared.sim
    drone = sim.drones.get(drone_id)
    if not drone:
        return {"status": "error", "message": f"Drone {drone_id} not found"}

    triage_response = ""
    if operator_message.strip():
        try:
            from llm_gateway import completion
            resp = completion(messages=[
                {"role": "system", "content": (
                    "You are a tactical rescue coordinator. Given a survivor report and operator message, "
                    "output a 1-sentence triage assessment and rescue priority (P1/P2/P3). Be concise."
                )},
                {"role": "user", "content": (
                    f"Survivor report: {drone.victim_report or 'Unknown'}. "
                    f"Operator: {operator_message}"
                )},
            ])
            triage_response = resp.choices[0].message.content.strip()
            sim.log(f"🏥 TRIAGE AI: {triage_response}", "INFO", drone_id)
        except Exception as e:
            print(f"[LLM Gateway] Triage failed: {e}", file=sys.stderr)

    result = sim.rescue_victim(drone_id)
    return {"status": "ok", "result": result, "triage": triage_response}


@app.post("/guide-victim")
async def guide_victim(drone_id: str):
    """Command a drone to guide a mobile survivor to base."""
    result = shared.sim.guide_victim(drone_id)
    return {"status": "ok", "result": result}


@app.post("/voice-command")
async def voice_command(text: str):
    """AI parses voice command and reroutes nearest eligible drone."""
    sim = shared.sim
    try:
        from llm_gateway import completion
        grid_desc = f"20×15 grid, base at (0,0). Drones: " + ", ".join(
            f"{d.id} at ({d.x},{d.y}) battery {d.battery:.0f}%"
            for d in sim.drones.values()
        )
        resp = completion(messages=[
            {"role": "system", "content": (
                "You are a rescue coordinator parsing operator voice commands into JSON actions.\n"
                "Extract the target location and urgency. Output ONLY valid JSON:\n"
                "{\"x\": int, \"y\": int, \"priority\": \"P1|P2|P3\", \"report\": \"brief description\"}\n"
                "If no location mentioned, output {\"error\": \"no_location\"}"
            )},
            {"role": "user", "content": f"Grid: {grid_desc}\nCommand: {text}"},
        ])
        raw = resp.choices[0].message.content.strip()
        # Extract JSON block if wrapped in markdown
        if "```" in raw:
            raw = raw.split("```")[1].strip().lstrip("json").strip()
        parsed = json.loads(raw)
        if "error" in parsed:
            return {"status": "error", "message": "No location found in command", "raw": text}

        x, y = int(parsed.get("x", 0)), int(parsed.get("y", 0))
        priority = parsed.get("priority", "P2-URGENT")
        report = parsed.get("report", text[:60])

        if not priority.startswith("P"):
            priority = f"{priority}-URGENT"

        # Add victim intel
        intel_result = sim.add_victim(x, y, report, priority)
        sim.log(f"🎙️ VOICE CMD: '{text}' → target ({x},{y}) | {intel_result}", "VERBAL")

        # Reroute nearest idle/on-mission drone
        best_drone = None
        best_dist = float("inf")
        for d in sim.drones.values():
            if d.is_waiting_response or d.is_charging or d.returning_to_base:
                continue
            dist = chebyshev(d.x, d.y, x, y)
            if dist < best_dist:
                best_dist = dist
                best_drone = d

        if best_drone:
            if best_drone.assigned_zone_id:
                zid = best_drone.assigned_zone_id
                if best_drone.path_queue:
                    sim.zone.zones[zid].residual_path = list(best_drone.path_queue)
                sim.release_zone(zid)
                best_drone.assigned_zone_id = None
            best_drone.path_queue = []
            best_drone.target_x, best_drone.target_y = x, y
            best_drone.voice_override = True
            best_drone.status = "ON_MISSION"
            best_drone.status_label = f"INTEL→({x},{y})"
            sim.log(f"📡 {best_drone.id} rerouted to intel target ({x},{y}).", "AI", best_drone.id)
            return {"status": "ok", "drone": best_drone.id, "target": [x, y], "intel": intel_result}

        return {"status": "ok", "intel": intel_result, "drone": None, "message": "No available drone"}

    except Exception as e:
        print(f"[Voice Command] Error: {e}", file=sys.stderr)
        return {"status": "error", "message": str(e)}


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
