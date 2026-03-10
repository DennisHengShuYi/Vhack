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

        step = 0
        max_steps = 3000  # hard cap

        while sim.mission_active and step < max_steps:
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
                            if not drone.is_waiting_response:
                                drone.target_x = int(target[0])
                                drone.target_y = int(target[1])
                                if target != [0, 0]:
                                    drone.returning_to_base = False
                                    drone.mission_complete_rtb = False
                except Exception as e:
                    sim.log(f"Planning error: {str(e)[:80]}", "ERROR")

            # ── Loop A: Simulation Tick ───────────────────────────────────
            for d_id, drone in list(sim.drones.items()):

                # --- Victim standby: do not move ---
                if drone.is_waiting_response:
                    drone.status_label = "VICTIM STANDBY"
                    continue

                # --- Auto-charge at base ---
                if (drone.x, drone.y) == (0, 0) and drone.battery < 100 and (
                    drone.returning_to_base or drone.is_charging or drone.battery < LOW_BATTERY_THRESHOLD
                ):
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
                        sim.charge_step(d_id)
                    else:
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

                # Battery gate before move
                if drone.battery <= BATTERY_DRAIN_MOVE:
                    sim.log(f"⚡ {d_id} critically low — emergency RTB!", "WARN", d_id)
                    drone.target_x, drone.target_y = 0, 0
                    drone.returning_to_base = True
                    continue

                drone.x, drone.y = nx, ny
                drone.battery = max(0.0, drone.battery - BATTERY_DRAIN_MOVE)
                drone.status_label = f"→({tx},{ty})"

                # Track path history
                drone.path_history.append([nx, ny])
                if len(drone.path_history) > 12:
                    drone.path_history = drone.path_history[-12:]

                # Low battery threshold — force RTB
                if drone.battery < LOW_BATTERY_THRESHOLD and not drone.returning_to_base:
                    drone.target_x, drone.target_y = 0, 0
                    drone.returning_to_base = True
                    sim.log(
                        f"🪫 {d_id} battery {drone.battery:.0f}% — RTB forced!", "WARN", d_id
                    )

                # Opportunistic scan while passing through
                if not sim.zone.scanned_cells[ny][nx]:
                    sim.scan(d_id)

            await asyncio.sleep(SIM_TICK)
            step += 1

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
        sim.log(f"COMMS FROM {drone_id}: '{operator_message}'", "COMMS", drone_id)
        try:
            import google.generativeai as genai
            import json
            
            p_model = genai.GenerativeModel("models/gemini-1.5-flash")
            
            # Request parsing of coordinates or location clues
            parse_prompt = (
                f"You are a rescue dispatcher. Victim at current position said: '{operator_message}'. "
                "Task: If they mention a location of OTHER survivors (e.g. 'family at (5,6)' or 'my son is at sector 2-3'), "
                "extract the coordinates [x, y] as integers 0-9. "
                "Current Grid is 10x10. If they say 'south-east corner' infer (9,9). "
                "If they say 'middle' infer (4,4). "
                "Output JSON: {\"target\": [x, y], \"reason\": \"...\"} or if no location mentioned, output {}."
            )
            
            p_resp = await asyncio.wait_for(
                asyncio.to_thread(lambda: p_model.generate_content(parse_prompt)),
                timeout=12.0,
            )
            
            try:
                # Basic JSON cleaning (Gemini 1.5 might include markdown blocks)
                json_str = p_resp.text.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(json_str)
                if data.get("target"):
                    tx, ty = data["target"]
                    reason = data.get("reason", "Reported by survivor")
                    sim.add_victim(tx, ty, f"Survivor intel: {reason}")
                    sim.log(f"AI EXTRACTED NEW TARGET: ({tx},{ty}) from comms.", "AI", drone_id)
            except Exception as je:
                print(f"JSON Parse error from speech extraction: {je}")

            # Also do standard medical triage for the CURRENT victim
            triage_model = genai.GenerativeModel("models/gemini-1.5-flash")
            victim_ctx = drone.victim_report or "Unknown situation"
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: triage_model.generate_content(
                        f"EMERGENCY TRIAGE. Case: '{victim_ctx}'. Victim said: '{operator_message}'. "
                        "Give exactly ONE sentence: triage priority (P1/P2/P3) and next action."
                    )
                ),
                timeout=10.0,
            )
            sim.log(f"TRIAGE AI: {resp.text.strip()}", "AI", drone_id)
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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8005, log_level="info")
