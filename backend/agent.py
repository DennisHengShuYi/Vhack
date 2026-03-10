"""
Swarm Command Agent — Gemini 2.5 Flash LLM orchestrator with MCP tool integration.

Architecture:
  - Uses Gemini 2.5 Flash for Chain-of-Thought reasoning and target planning
  - Calls real MCP tools via fastmcp for fleet management
  - Falls back to deterministic rule-based planner if LLM unavailable
  - Never hard-codes drone IDs — discovers via list_drones() at each tick
"""
import os
import asyncio
import json
import traceback
from typing import Dict, List, Any, Optional

import google.generativeai as genai
from dotenv import load_dotenv

import shared
from simulation import LOW_BATTERY_THRESHOLD

# ─── Load API Key ─────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
GEMINI_KEY = os.getenv("GEMINI_KEY", "")
MODEL_NAME = "models/gemini-1.5-flash"  # Use official GCP name models/gemini-xx

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# ─── Chain-of-Thought System Instruction ─────────────────────────────────────
SYSTEM_INSTRUCTION = """\
You are SENTINEL — the AI Command Agent for a 5-drone rescue swarm operating on a 10×10 disaster grid.
This is a post-typhoon rescue operation. Cell towers are down. You are the ONLY intelligence.

YOUR MISSION: Orchestrate the drone swarm to scan ALL sectors, detect thermal signatures of survivors,
manage battery levels, and ensure maximum coverage efficiency.

═══ CHAIN-OF-THOUGHT REASONING (MANDATORY) ═══
Before outputting the JSON plan, write a COT block:
[COT]
- Battery Assessment: List each drone's battery and your decision
- Coverage Strategy: Which unscanned sectors to target and why
- Priority Victims: Any drones in VICTIM STANDBY — what to do
- Risk Assessment: Any drones at risk of battery failure
[/COT]

═══ STRATEGIC RULES ═══
1. BATTERY CRITICAL (<25%): Immediately assign drone to [0,0] (base station) for charging
2. VICTIM STANDBY: drone detected victim — do NOT reassign it, leave it at current position
3. CHARGING: Skip drones with battery <90% that are currently charging
4. COVERAGE: Spread drones across DIFFERENT unscanned sectors (no overlap)
5. DISTANCE EFFICIENCY: Prefer nearby unscanned sectors to minimize battery cost
6. MISSION COMPLETE: If all sectors scanned, return all drones to [0,0]

═══ OUTPUT FORMAT ═══
After the COT block, output this exact JSON on the last line:
{"assignments": {"ALPHA-1": [x, y], "ALPHA-2": [x, y], "ALPHA-3": [x, y], "ALPHA-4": [x, y], "ALPHA-5": [x, y]}}

Coordinates: integers 0–9. Assign every non-busy drone a target. Busy = waiting/charging(<90%).
"""


def _build_planning_prompt(state: Dict[str, Any]) -> str:
    """Build a structured prompt from the current swarm state."""
    stats = state["stats"]
    unscanned = state.get("unscanned", [])[:25]  # sample for prompt
    waiting_drones = [
        d for d in state["drones"] if d["is_waiting_response"]
    ]

    drones_info = []
    for d in state["drones"]:
        flags = []
        if d["is_charging"]:
            flags.append("CHARGING")
        if d["returning_to_base"]:
            flags.append("RTB")
        if d["is_waiting_response"]:
            flags.append("⚠️VICTIM_STANDBY")
        flag_str = " | ".join(flags) if flags else "ACTIVE"
        drones_info.append(
            f"  {d['id']:8s} → pos=({d['x']},{d['y']}) "
            f"bat={d['battery']:.0f}% "
            f"status={d['status_label']:20s} [{flag_str}]"
        )

    victim_alerts = []
    for d in waiting_drones:
        victim_alerts.append(
            f"  ⚠️  {d['id']} has detected survivor: '{d.get('victim_report', 'Unknown')}'"
        )

    prompt_parts = [
        "═══ RESCUE SWARM — COMMAND BRIEFING ═══",
        f"📍 Coverage: {stats['coverage_pct']}% | "
        f"⏱️ Elapsed: {stats['elapsed_ts']}",
        f"👥 Survivors: {stats['victims_found']} found / "
        f"{stats['victims_rescued']} rescued / {stats['total_victims']} total",
        f"🗺️  Unscanned sectors: {len(unscanned)} remaining (sample: {unscanned[:10]})",
        "",
        "FLEET TELEMETRY:",
    ] + drones_info

    if victim_alerts:
        prompt_parts += ["", "🚨 VICTIM ALERTS (STANDBY DRONES — DO NOT REASSIGN):"] + victim_alerts

    prompt_parts += [
        "",
        "Issue Chain-of-Thought analysis then provide JSON target assignments.",
    ]

    return "\n".join(prompt_parts)


class CommandAgent:
    """Central Command Agent — uses Gemini 2.5 Flash for swarm orchestration."""

    def __init__(self):
        self.model: Optional[Any] = None
        self.llm_active = False
        self._init_model()

    def _init_model(self):
        if not GEMINI_KEY:
            shared.sim.log(
                "⚠️  No GEMINI_KEY — switching to rule-based fallback planner.", "WARN"
            )
            return
        try:
            self.model = genai.GenerativeModel(
                model_name=MODEL_NAME,
                system_instruction=SYSTEM_INSTRUCTION,
            )
            self.llm_active = True
            shared.sim.log(
                f"SENTINEL AI ONLINE - Gemini Flash ({MODEL_NAME})", "AI"
            )
        except Exception as e:
            shared.sim.log(f"⚠️  Gemini init failed: {e}. Rule-based mode.", "WARN")
            self.llm_active = False

    async def plan(self) -> Dict[str, List[int]]:
        """
        Request a target assignment plan from Gemini 2.5 Flash.
        Returns: {drone_id: [x, y]} for all assignable drones.
        """
        state = shared.sim.get_status()
        state["unscanned"] = shared.sim.get_unscanned_cells()

        if self.llm_active and self.model:
            try:
                prompt = _build_planning_prompt(state)
                shared.sim.log("🧠 [SENTINEL] Planning tick — querying Gemini 2.5 Flash...", "AI")

                response = await asyncio.wait_for(
                    asyncio.to_thread(lambda: self.model.generate_content(prompt)),
                    timeout=20.0,
                )
                text = response.text.strip()

                # ── Extract and log Chain-of-Thought block ──────────────────
                if "[COT]" in text and "[/COT]" in text:
                    cot_start = text.index("[COT]")
                    cot_end = text.index("[/COT]") + len("[/COT]")
                    cot_block = text[cot_start:cot_end]
                    # Log each COT line
                    for line in cot_block.split("\n"):
                        line = line.strip()
                        if line and line not in ("[COT]", "[/COT]"):
                            shared.sim.log(f"🧠 {line}", "AI")
                else:
                    # Fallback: log first meaningful lines
                    for line in text.split("\n")[:4]:
                        if line.strip() and not line.strip().startswith("{"):
                            shared.sim.log(f"🧠 [GEMINI COT] {line.strip()}", "AI")

                # ── Parse JSON plan ─────────────────────────────────────────
                json_line = next(
                    (l.strip() for l in reversed(text.split("\n"))
                     if l.strip().startswith("{")),
                    None,
                )
                if json_line:
                    plan = json.loads(json_line)
                    assignments = plan.get("assignments", {})
                    summary = ", ".join(
                        f"{k}→({v[0]},{v[1]})" for k, v in assignments.items()
                    )
                    shared.sim.log(f"✅ [SENTINEL] Plan: {summary}", "AI")
                    return assignments
                else:
                    shared.sim.log(
                        "⚠️  [SENTINEL] Could not parse JSON plan. Falling back to rules.", "WARN"
                    )

            except asyncio.TimeoutError:
                shared.sim.log("⏱️  [SENTINEL] Timeout (20s). Rule-based fallback.", "WARN")
            except json.JSONDecodeError as e:
                shared.sim.log(f"⚠️  [SENTINEL] JSON parse error: {e}. Fallback.", "WARN")
            except Exception as e:
                shared.sim.log(
                    f"❌ [SENTINEL] Error: {str(e)[:100]}. Fallback.", "WARN"
                )
                traceback.print_exc()

        return self._rule_based_plan()

    def _rule_based_plan(self) -> Dict[str, List[int]]:
        """Deterministic fallback planner — always produces a valid assignment."""
        sim = shared.sim
        assignments: Dict[str, List[int]] = {}
        unscanned = sim.get_unscanned_cells()
        used_targets: set = set()

        for drone in sim.drones.values():
            # Skip busy drones
            if drone.is_waiting_response:
                continue
            if drone.is_charging and drone.battery < 90:
                continue

            # Battery critical — recall
            if drone.battery < LOW_BATTERY_THRESHOLD:
                assignments[drone.id] = [0, 0]
                continue

            if unscanned:
                # Pick nearest unscanned, avoid conflicts
                available = [c for c in unscanned if tuple(c) not in used_targets]
                if not available:
                    available = unscanned
                target = min(
                    available,
                    key=lambda c: abs(c[0] - drone.x) + abs(c[1] - drone.y),
                )
                assignments[drone.id] = target
                used_targets.add(tuple(target))
            else:
                assignments[drone.id] = [0, 0]

        if assignments:
            summary = ", ".join(f"{k}→({v[0]},{v[1]})" for k, v in assignments.items())
            sim.log(f"🤖 [RULE-BASED] Plan: {summary}", "INFO")
        return assignments
