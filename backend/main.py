"""
Main FastAPI server — Split-loop swarm orchestration:

  Loop A (Simulation Ticker, every 0.7s):
    - Steps each drone one cell toward its assigned target
    - Executes thermal scans on arrival
    - Manages charging, battery emergency RTB
    - ALWAYS runs — never blocked by AI latency

  Loop B (AI Planning, every 6s):
    - Queries Gemini 2.5 Flash for Chain-of-Thought target assignments
    - Applies AI plan to drone targets
    - Falls back to rule-based if LLM is slow/offline

Result: Drones always animate. UI is always live. AI adds intelligence, not blocking.
"""
import os
import asyncio
import time
from typing import Optional

import uvicorn
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

if os.getenv("GEMINI_KEY") and not os.getenv("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_KEY", "")

import shared
from agent import CommandAgent
from simulation import BATTERY_DRAIN_MOVE, LOW_BATTERY_THRESHOLD, SimulationState


# ─── Mission Manager ───────────────────────────────────────────────────────────
class MissionManager:
    def __init__(self):
        self.agent = CommandAgent()

    async def run_swarm_orchestration(self):
        """Main orchestration coroutine — runs the full mission lifecycle."""
        sim = shared.sim
        if sim.mission_active:
            return

        sim.mission_active = True
        sim.mission_start_time = time.time()
        sim.log("═══ RESCUE SWARM INTELLIGENCE ACTIVATED ═══", "SUCCESS")
        sim.log("📡 MCP channel open | 🛰️ Fleet online | 🧠 SENTINEL AI ready", "INFO")

        last_plan_time = 0.0
        AI_PLAN_INTERVAL = 6.0   # Gemini planning every 6s
        SIM_TICK = 0.7            # Simulation physics every 0.7s

        step_count: int = 0
        max_steps = 3000  # hard cap

        while sim.mission_active:
            if step_count >= max_steps:
               break
            sim = shared.sim  # re-reference after potential reset

            # ── Mission Completion ────────────────────────────────────────
            survivors = sim.zone.survivors
            if survivors and all(s["rescued"] for s in survivors):
                sim.log("🏁 MISSION ACCOMPLISHED — All survivors extracted!", "SUCCESS")
                sim.log(
                    f"📊 Final Stats: Coverage {sim.get_status()['stats']['coverage_pct']}% | "
                    f"Rescued {sim.total_rescued}/{len(survivors)} survivors",
                    "SUCCESS",
                )
                for drone in sim.drones.values():
                    if (drone.x, drone.y) != (0, 0):
                        drone.target_x, drone.target_y = 0, 0
                        drone.returning_to_base = True
                        drone.mission_complete_rtb = True
                        drone.status_label = "RTB — COMPLETE"
                sim.mission_active = False
                break

            now = time.time()

            # ── Loop B: AI Planning ───────────────────────────────────────
            if (now - last_plan_time) >= AI_PLAN_INTERVAL:
                last_plan_time = now
                try:
                    plan = await self.agent.plan()
                    for drone_id, target in plan.items():
                        if drone_id in sim.drones:
                            drone = sim.drones[drone_id]
                            # Only assign if not in waiting/voice override
                            if not drone.is_waiting_response and not drone.voice_override:
                                drone.target_x = int(target[0])
                                drone.target_y = int(target[1])
                                if target != [0, 0]:
                                    drone.returning_to_base = False
                                    drone.mission_complete_rtb = False
                except Exception as e:
                    err_str = str(e)
                    err_trunc = "".join(err_str[k] for k in range(min(80, len(err_str))))
                    sim.log(f"Planning error: {err_trunc}", "ERROR")

            # ── Loop A: Simulation Tick ───────────────────────────────────
            # Always run the network heartbeat first
            sim.simulate_heartbeats()

            for d_id, drone in list(sim.drones.items()):

                # --- Freeze offline/disconnected drones so they don't move ---
                if not getattr(drone, 'is_active', True):
                    continue

                # --- Victim standby: do not move ---
                if drone.is_waiting_response:
                    drone.status_label = "VICTIM STANDBY"
                    continue

                # --- Auto-charge at base ---
                if (drone.x, drone.y) == (0, 0) and drone.battery is not None and drone.battery < 100 and (
                    drone.returning_to_base or drone.is_charging or drone.battery < LOW_BATTERY_THRESHOLD
                ):
                    if not drone.is_charging:
                         sim.log(f"🤖 [SYSTEM LOGIC] {d_id} arrived at base. Commencing autonomous recharge sequence.", "INFO", d_id)
                    sim.charge_step(d_id)
                    if not drone.is_charging:
                        drone.returning_to_base = False
                    continue

                # --- No target: wait for AI ---
                if drone.target_x is None:
                    drone.status_label = "AWAITING ORDERS"
                    continue

                tx, ty = drone.target_x, drone.target_y

                # --- Arrived at target ---
                if drone.x == tx and drone.y == ty:
                    if tx == 0 and ty == 0:
                        drone.returning_to_base = True
                        sim.log(f"🤖 [SYSTEM LOGIC] {d_id} returned to base safely. Switching to standby/charge.", "INFO", d_id)
                        sim.charge_step(d_id)
                    else:
                        # If reached voice target, now return if needed
                        if drone.voice_override and drone.original_pos and (tx, ty) != tuple(drone.original_pos):
                             sim.log(f"✅ {d_id} reached voice target ({tx},{ty}). Scanning then returning to original position.", "SUCCESS", d_id)
                             sim.scan(d_id)
                             drone.target_x, drone.target_y = drone.original_pos
                        elif drone.voice_override and drone.original_pos and (tx, ty) == tuple(drone.original_pos):
                             sim.log(f"🏠 {d_id} returned to original position. Resuming autonomous mission.", "INFO", d_id)
                             drone.voice_override = False
                             drone.original_pos = None
                             drone.target_x = None
                        else:
                            sim.log(f"🤖 [SYSTEM LOGIC] {d_id} reached target ({tx},{ty}). Executing thermal sweep.", "INFO", d_id)
                            # Perform thermal scan
                            result = sim.scan(d_id)
                            if "THERMAL MATCH" not in result and "VICTIM_DETECTED" not in result:
                                drone.target_x = None  # Free for next assignment
                        drone.status_label = "SCANNED"
                    continue

                # --- Move one step toward target (Manhattan) ---
                nx, ny = drone.x, drone.y
                if nx != tx:
                    nx += 1 if tx > nx else -1
                elif ny != ty:
                    ny += 1 if ty > ny else -1

                old_x, old_y = drone.x, drone.y
                drone.x, drone.y = nx, ny
                
                # If guiding, victim moves with drone
                if drone.is_guiding and drone.guiding_victim_id:
                    for s in sim.zone.survivors:
                        if s["id"] == drone.guiding_victim_id:
                            s["x"], s["y"] = nx, ny
                            if (nx, ny) == (0, 0):
                                s["rescued"] = True
                                drone.is_guiding = False
                                drone.guiding_victim_id = None
                                sim.total_rescued += 1
                                sim.log(f"Survivor {s['id']} guided safely to base station!", "SUCCESS", d_id)

                # --- Post-Move Updates (Battery & History) ---
                if drone.battery is not None:
                    drone.battery = max(0.0, drone.battery - BATTERY_DRAIN_MOVE)
                    drone.status_label = f"→({tx},{ty})"

                    # Track path history
                    drone.path_history.append([nx, ny])
                    while len(drone.path_history) > 12:
                        drone.path_history.pop(0)

                    # Low battery threshold — force RTB
                    if drone.battery < LOW_BATTERY_THRESHOLD and not drone.returning_to_base:
                        drone.target_x, drone.target_y = 0, 0
                        drone.returning_to_base = True
                        sim.log(
                            f"🪫 [SYSTEM LOGIC] {d_id} battery {drone.battery:.0f}% below threshold. Initiating safety RTB protocol.", "WARN", d_id
                        )

                    # Opportunistic scan while passing through
                    if not sim.zone.scanned_cells[ny][nx]:
                        sim.scan(d_id)

            await asyncio.sleep(SIM_TICK)
            step_count += 1

        sim.mission_active = False
        sim.log("═══ SWARM DISENGAGED ═══", "INFO")


# ─── FastAPI Application ───────────────────────────────────────────────────────
app = FastAPI(
    title="RescueSwarm API",
    description="First Responder Swarm Intelligence — Decentralised MCP Architecture",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = MissionManager()


@app.get("/state")
async def get_state():
    """Return full simulation state: drones, zone, log, stats."""
    return shared.sim.get_status()


@app.post("/run-mission")
async def run_mission(background_tasks: BackgroundTasks):
    """Start the AI-orchestrated rescue mission."""
    if shared.sim.mission_active:
        return {"status": "Mission already active", "running": True}
    background_tasks.add_task(manager.run_swarm_orchestration)
    return {
        "status": "SWARM DEPLOYED — SENTINEL AI + MCP Active",
        "drones": list(shared.sim.drones.keys()),
        "running": True,
    }


@app.post("/stop-mission")
async def stop_mission():
    """Halt the active search mission."""
    shared.sim.mission_active = False
    shared.sim.log("🛑 MISSION HALTED BY OPERATOR", "WARN")
    return {"status": "Mission stopped"}


@app.post("/reset")
async def reset_mission():
    """Reset simulation and reinitialize with new disaster layout."""
    shared.sim = SimulationState()
    global manager
    manager = MissionManager()
    return {"status": "Simulation reset — new disaster zone generated"}


@app.post("/victim-response")
async def victim_response(drone_id: str, operator_message: Optional[str] = None):
    """
    Operator confirms rescue and optionally sends triage message to drone.
    The AI performs medical triage prioritization via Gemini if message is provided.
    """
    sim = shared.sim
    drone = sim.drones.get(drone_id)
    if not drone:
        return {"error": f"Drone {drone_id} not found"}

    # Log operator message and run AI triage / extraction if provided
    if operator_message and operator_message.strip():
        sim.log(f"🎙️ VERBAL INPUT: \"{operator_message}\"", "VERBAL", drone_id)
        try:
            import llm_gateway as litellm
            import json
            
            # Request parsing of coordinates or location clues
            parse_prompt = (
                f"You are a rescue dispatcher. Victim at current position said: '{operator_message}'. "
                "Task: If they mention a location of OTHER survivors (e.g. 'family at (5,6)', 'grid 10', '10,10' or 'sector 2-3'), "
                "extract the coordinates [x, y] as integers 0-9. "
                "Instructions: "
                "1. Grid is 10x10. If they say '10,10' map to (9,9). "
                "2. If they say 'Grid N' (0-99), N%10 is x, N//10 is y. "
                "3. If they say 'middle' infer (4,4). "
                "Output JSON: {\"target\": [x, y], \"reason\": \"string summarize why this unit is moving there\"} or if no location mentioned, output {}."
            )
            
            p_resp = await asyncio.wait_for(
                asyncio.to_thread(
                    litellm.completion, 
                    model=os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash"), 
                    messages=[{"role": "user", "content": parse_prompt}]
                ),
                timeout=12.0,
            )
            
            try:
                # Basic JSON cleaning
                json_str = p_resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(json_str)
                if data.get("target"):
                    tx, ty = data["target"]
                    reason = data.get("reason", "Reported coordinate")
                    sim.add_victim(tx, ty, f"Survivor intel: {reason}")
                    sim.log(f"AI INTEL PARSED: Target ({tx},{ty}) identified from speech. Reason: {reason}", "AI", drone_id)
            except Exception as je:
                print(f"JSON Parse error from speech extraction: {je}")

            # Also do standard medical triage for the CURRENT victim
            victim_ctx = drone.victim_report or "Unknown situation"
            triage_prompt = f"EMERGENCY TRIAGE. Case: '{victim_ctx}'. Victim said: '{operator_message}'. Give exactly ONE sentence: triage priority (P1/P2/P3) and next action."
            
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    litellm.completion,
                    model=os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash"),
                    messages=[{"role": "user", "content": triage_prompt}]
                ),
                timeout=10.0,
            )
            sim.log(f"TRIAGE AI: {resp.choices[0].message.content.strip()}", "AI", drone_id)
        except Exception as e:
            sim.log(f"Comms processing error: {e}", "ERROR", drone_id)

    # Execute rescue
    result = sim.rescue_victim(drone_id)
    if drone:
        drone.is_waiting_response = False
        drone.victim_report = None
        drone.target_x = None  # Force AI reassignment
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
    Handle global voice commands via Gemini 2.5 Flash.
    Example: "Move closest drone to grid 10"
    """
    sim = shared.sim
    sim.log(f"🎙️ GLOBAL VOICE: '{message}'", "VERBAL")
    
    try:
        import llm_gateway as litellm
        import json
        
        # Grid is 10x10 (0-9, 0-9). 
        # Help Gemini understand the user might say "grid 10" or "sector 5"
        parse_prompt = (
            f"You are a rescue dispatcher. Command: '{message}'. "
            "The search area is a 10x10 grid where x and y are 0-9. (0,0) is the base station. "
            "Rules: "
            "1. If user says 'grid N' (where N is 0-99), map it to x = N % 10, y = N // 10. "
            "2. If user says 'coordinate (X,Y)', map directly. "
            "3. If user says 'sector' or vague location, infer best [x, y]. "
            "Return JSON: {\"target\": [x, y], \"reason\": \"...\"} "
            "or {} if the message is not a movement command."
        )
        
        p_resp = await asyncio.wait_for(
            asyncio.to_thread(
                litellm.completion, 
                model=os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash"), 
                messages=[{"role": "user", "content": parse_prompt}]
            ),
            timeout=12.0,
        )
        
        json_str = p_resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(json_str)
        
        if data.get("target"):
            tx, ty = data["target"]
            tx = max(0, min(9, tx))
            ty = max(0, min(9, ty))
            reason = data.get("reason", "Voice instruction")
            
            # Find closest available drone
            best_drone: Optional[Any] = None
            min_dist = 999
            
            for drone in sim.drones.values():
                # Skip drones in specialized states
                if drone.is_waiting_response or drone.is_charging:
                    continue
                dist = abs(drone.x - tx) + abs(drone.y - ty)
                if dist < min_dist:
                    min_dist = dist
                    best_drone = drone
            
            if best_drone is not None:
                best_drone.original_pos = [best_drone.x, best_drone.y]
                best_drone.target_x, best_drone.target_y = tx, ty
                best_drone.voice_override = True
                sim.log(f"🧠 AI DISPATCH: Re-routing {best_drone.id} to ({tx},{ty}) target. Reason: {reason}", "AI", best_drone.id)
                return {"status": "Command executed", "drone": best_drone.id, "target": [tx, ty]}
            else:
                return {"status": "No drones available for override"}
                
    except Exception as e:
        sim.log(f"Voice processing error: {e}", "ERROR")
        return {"error": str(e)}
        
    return {"status": "Command analyzed but no action taken"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8005, log_level="info")
