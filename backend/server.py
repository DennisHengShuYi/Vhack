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
                        elif ny != ty:
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
                            sim.release_zone(drone.assigned_zone_id)
                            sim.log(f"⚠️ {d_id} aborting zone {drone.assigned_zone_id} — low battery.", "WARN", d_id)
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
    AI parses any location intel in the message via llm_gateway.
    """
    import llm_gateway
    sim = shared.sim
    drone = sim.drones.get(drone_id)
    if not drone:
        return {"error": f"Drone {drone_id} not found"}

    if operator_message and operator_message.strip():
        sim.log(f"🎙️ VERBAL INPUT: \"{operator_message}\"", "VERBAL", drone_id)
        try:
            parse_prompt = (
                f"You are a rescue dispatcher. Victim at current position said: '{operator_message}'. "
                "Task: If they mention a location of OTHER survivors (e.g. 'family at (5,6)', 'grid 10', '10,10' or 'sector 2-3'), "
                "extract the coordinates [x, y] as integers. "
                "Instructions: "
                "1. Grid is 20x15 (x: 0-19, y: 0-14). "
                "2. If they say '10,10' map to (10,10). "
                "3. If they say 'Grid N' (0-299), x = N % 20, y = N // 20. "
                "4. If they say 'middle' infer (10,7). "
                "Output JSON: {\"target\": [x, y], \"reason\": \"...\"}  or if no location mentioned, output {}."
            )
            p_resp = await asyncio.wait_for(
                asyncio.to_thread(
                    llm_gateway.completion,
                    messages=[{"role": "user", "content": parse_prompt}]
                ),
                timeout=12.0,
            )
            json_str = p_resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(json_str)
            if data.get("target"):
                tx, ty = data["target"]
                reason = data.get("reason", "Reported coordinate")
                sim.add_victim(tx, ty, f"Survivor intel: {reason}")
                sim.log(f"AI INTEL PARSED: Target ({tx},{ty}) identified from speech. Reason: {reason}", "AI", drone_id)
                
                # Dispatch Logic: "Intel-Driven Interrupt"
                dist_current = chebyshev(drone.x, drone.y, tx, ty)
                selected_drone = None
                
                # Selection Criteria A: The "Discovering" Drone
                if dist_current <= 7 and drone.battery > 30:
                    selected_drone = drone
                    sim.log(f"🎯 INTEL DISPATCH: Discovering drone {drone.id} is within radius ({dist_current} cells). Assigning.", "AI", drone_id)
                else:
                    # Selection Criteria B: The "Nearest" Drone
                    min_dist = 999
                    for d in sim.drones.values():
                        if d.battery > 35 and not d.is_waiting_response and not d.is_charging:
                            dist = chebyshev(d.x, d.y, tx, ty)
                            if dist < min_dist:
                                min_dist = dist
                                selected_drone = d
                    if selected_drone and selected_drone != drone:
                        sim.log(f"🎯 INTEL DISPATCH: Closest available drone {selected_drone.id} assigned to far-away target ({min_dist} cells).", "AI", selected_drone.id)

                if selected_drone:
                    # Handoff Protocol: Release current zone with progress
                    if selected_drone.assigned_zone_id:
                        zid = selected_drone.assigned_zone_id
                        zone = sim.zone.zones.get(zid)
                        if zone:
                            # Save remaining path for the next drone
                            zone.residual_path = selected_drone.path_queue
                            sim.release_zone(zid)
                            sim.log(f"🔄 HANDOFF: {selected_drone.id} released zone {zid} with {len(zone.residual_path)} cells remaining.", "AI", selected_drone.id)
                        selected_drone.assigned_zone_id = None
                        selected_drone.path_queue = []

                    # Save current position (not for return, but as reference)
                    selected_drone.original_pos = [selected_drone.x, selected_drone.y]
                    selected_drone.voice_override = True
                    
                    # Generate path to intel target
                    curr_x, curr_y = selected_drone.x, selected_drone.y
                    to_intel_path = []
                    while (curr_x, curr_y) != (tx, ty):
                        if curr_x < tx: curr_x += 1
                        elif curr_x > tx: curr_x -= 1
                        if curr_y < ty: curr_y += 1
                        elif curr_y > ty: curr_y -= 1
                        to_intel_path.append([curr_x, curr_y])
                    
                    # Implementation Strategy: Push to Front
                    selected_drone.path_queue = to_intel_path
                    selected_drone.status = "ON_MISSION"
                    selected_drone.status_label = "INTEL INTERRUPT"
                    sim.log(f"🧠 AI INTERRUPT: Drone {selected_drone.id} diverted to ({tx},{ty}). Zone progress preserved for handoff.", "AI", selected_drone.id)
                else:
                    sim.log(f"⚠️ INTEL DISPATCH FAILED: No drone available with sufficient battery for target ({tx},{ty}).", "WARN", drone_id)
        except Exception as e:
            sim.log(f"Intel parsing error: {e}", "ERROR", drone_id)

        try:
            victim_ctx = drone.victim_report or "Unknown situation"
            triage_prompt = (
                f"EMERGENCY TRIAGE. Case: '{victim_ctx}'. Victim said: '{operator_message}'. "
                "Give exactly ONE sentence: triage priority (P1/P2/P3) and next action."
            )
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    llm_gateway.completion,
                    messages=[{"role": "user", "content": triage_prompt}]
                ),
                timeout=10.0,
            )
            sim.log(f"TRIAGE AI: {resp.choices[0].message.content.strip()}", "AI", drone_id)
        except Exception as e:
            sim.log(f"Triage AI error: {e}", "ERROR", drone_id)

    result = sim.rescue_victim(drone_id)
    if drone:
        drone.is_waiting_response = False
        drone.victim_report = None
        drone.target_x = None
        drone.status_label = "RESUMING"

    return {"status": "Drone resumed", "result": result}


@app.post("/guide-victim")
async def guide_victim(drone_id: str):
    """Command a drone to guide the mobile survivor at its location to base."""
    result = shared.sim.guide_victim(drone_id)
    return {"status": "Guide command issued", "result": result}


@app.post("/voice-command")
async def voice_command(message: str):
    """
    Handle global voice commands — AI parses target coordinates and reroutes nearest drone.
    Example: 'Move closest drone to grid 10'
    """
    import llm_gateway
    sim = shared.sim
    sim.log(f"🎙️ GLOBAL VOICE: '{message}'", "VERBAL")

    try:
        parse_prompt = (
            f"You are a rescue dispatcher. Command: '{message}'. "
            "Grid is 20x15 (x: 0-19, y: 0-14). "
            "Rules: "
            "1. If user says 'grid N' (0-299), x = N % 20, y = N // 20. "
            "2. If user says 'coordinate (X,Y)', map directly. "
            "3. If user says 'sector' or vague location, infer best [x, y]. "
            "Return JSON: {\"target\": [x, y], \"reason\": \"...\"} "
            "or {} if the message is not a movement command."
        )
        p_resp = await asyncio.wait_for(
            asyncio.to_thread(
                llm_gateway.completion,
                messages=[{"role": "user", "content": parse_prompt}]
            ),
            timeout=12.0,
        )
        json_str = p_resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(json_str)

        if data.get("target"):
            tx, ty = data["target"]
            tx = max(0, min(sim.zone.width - 1, tx))
            ty = max(0, min(sim.zone.height - 1, ty))
            if sim.is_inaccessible(tx, ty):
                accessible_cells = sim.get_unscanned_cells()
                if accessible_cells:
                    nearest_safe = min(
                        accessible_cells,
                        key=lambda c: abs(c[0] - tx) + abs(c[1] - ty),
                    )
                    tx, ty = nearest_safe[0], nearest_safe[1]
            reason = data.get("reason", "Voice instruction")

            best_drone: Optional[Any] = None
            min_dist = 999
            for drone in sim.drones.values():
                if drone.is_waiting_response or drone.is_charging:
                    continue
                dist = abs(drone.x - tx) + abs(drone.y - ty)
                if dist < min_dist:
                    min_dist = dist
                    best_drone = drone

            if best_drone:
                target_drone = best_drone
                target_id = target_drone.id
                # Handoff Protocol: Release current zone with progress
                current_zone_id = target_drone.assigned_zone_id
                if current_zone_id:
                    z = sim.zone.zones.get(current_zone_id)
                    if z:
                        # Save remaining path for the next drone
                        z.residual_path = target_drone.path_queue
                        sim.release_zone(current_zone_id)
                        sim.log(f"🔄 HANDOFF (Voice): {target_id} released zone {current_zone_id} with {len(z.residual_path)} cells remaining.", "AI", target_id)
                    target_drone.assigned_zone_id = None
                    target_drone.path_queue = []

                target_drone.original_pos = [target_drone.x, target_drone.y]
                target_drone.target_x, target_drone.target_y = tx, ty
                target_drone.voice_override = True
                target_drone.status = "ON_MISSION"
                target_drone.status_label = "VOICE OVERRIDE"
                sim.log(f"🧠 AI DISPATCH: Re-routing {target_id} to ({tx},{ty}). Reason: {reason}", "AI", target_id)
                return {"status": "Command executed", "drone": target_id, "target": [tx, ty]}
            else:
                return {"status": "No drones available for override"}

    except Exception as e:
        sim.log(f"Voice processing error: {e}", "ERROR")
        return {"error": str(e)}

    return {"status": "Command analyzed but no action taken"}


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
        return (f"MISSION COMPLETE: Grid fully searched. "
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

    zone = sim.zone.zones.get(zone_id)
    if not zone:
        return f"Error: Zone {zone_id} does not exist. Use get_grid_state() to see valid IDs."
    if zone.status != ZoneStatus.UNSCANNED:
        return f"Error: Zone {zone_id} is already {zone.status.value}. Pick a different zone."

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
