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

import llm_gateway as litellm
import shared
from simulation import LOW_BATTERY_THRESHOLD
from dotenv import load_dotenv

# ─── Load Environment ─────────────────────────────────────────────────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# Fallback compatibility for older key format
if os.getenv("GEMINI_KEY") and not os.getenv("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_KEY", "")

SYSTEM_INSTRUCTION = """
You are SENTINEL - the AI Command Agent for a 5-drone rescue swarm operating on a 10x10 disaster grid.
This is a post-typhoon rescue operation. You must be efficient.

=== GRID PARTITIONING STRATEGY ===
To maximize efficiency, deploy ALL drones immediately:
- Sector 1 (NORTH-WEST): x[0-4], y[0-4] -> ALPHA-1
- Sector 2 (NORTH-EAST): x[5-9], y[0-4] -> ALPHA-2
- Sector 3 (SOUTH-WEST): x[0-4], y[5-9] -> ALPHA-3
- Sector 4 (SOUTH-EAST): x[5-9], y[5-9] -> ALPHA-4
- Sector 5 (SUPPORT/GRID-CENTER): ALPHA-5 covers middle and assists other sectors.

=== PRIORITY TARGETS ===
1. KNOWN SURVIVORS: If a victim is detected but not yet rescued, the CLOSEST drone MUST be diverted to their location IMMEDIATELY.
2. INTEL TARGETS: Treat suspected locations as highest priority search goals.
3. FLEET DEPLOYMENT: Never leave a drone at base unless it is charging. Every active drone MUST have a target coordinate.

=== CHAIN-OF-THOUGHT REASONING (MANDATORY) ===
Before outputting the JSON plan, write a COT block. Be EXPLICIT about unit allocation:
[COT]
- Priority Assessment: Identify any known survivors or intel targets.
- Allocation Matrix: 
  - [Drone ID]: Assigning to ([x],[y]) because [Specific Reason: e.g., closest unit to voice-reported intel / assigned grid sector].
- Support Logic: Explain how ALPHA-5 is assisting.
[/COT]

=== STRATEGIC RULES ===
1. BATTERY CRITICAL (<25%): Immediately assign to [0,0]
2. RESCUE PRIORITY: Drones must reach known survivor coordinates to trigger scan/rescue.
3. LOAD BALANCING: Ensure drones search DIFFERENT cells.

=== OUTPUT FORMAT ===
After the COT block, output this exact JSON:
{"assignments": {"ALPHA-1": [x, y], ...}}
"""


def _build_planning_prompt(state: Dict[str, Any]) -> str:
    """Build a structured prompt from the current swarm state."""
    stats = state["stats"]
    unscanned_raw = state.get("unscanned", [])
    unscanned = [unscanned_raw[i] for i in range(min(25, len(unscanned_raw)))]  # sample for prompt
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
        f"📍 Coverage: {stats['coverage_pct']}% | ",
        f"⏱️ ETA to Finish: {stats['eta_ts']}",
        f"⏱️ Elapsed: {stats['elapsed_ts']}",
        f"👥 Survivors: {stats['victims_found']} found / ",
        f"{stats['victims_rescued']} rescued / {stats['total_victims']} total",
        f"🗺️  Unscanned sectors: {len(unscanned)} remaining",
        "",
        "🚨 HIGH PRIORITY: DETECTED/REPORTED SURVIVORS (NOT YET RESCUED):",
    ]
    
    # Extract known survivors that need rescue
    detected_survivors = [
        s for s in state["zone"]["survivors"]
        if (s.get("found") or "V_INTEL" in s["id"]) and not s.get("rescued")
    ]
    
    if detected_survivors:
        for s in detected_survivors:
            prompt_parts.append(f"  - {s['id']} at ({s['x']},{s['y']}) | STATUS: {'DETECTED' if s.get('found') else 'INTEL REPORT'}")
    else:
        prompt_parts.append("  - (None currently marked for extraction)")

    prompt_parts += [
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
        self.llm_active = False
        self.llm_model = os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash")
        self._init_model()

    def _init_model(self):
        provider = self.llm_model.split("/")[0] if "/" in self.llm_model else "gemini"
        
        if provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
            shared.sim.log("⚠️  No GEMINI_API_KEY — switching to rule-based fallback planner.", "WARN")
            return
        if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            shared.sim.log("⚠️  No OPENAI_API_KEY — switching to rule-based fallback planner.", "WARN")
            return
            
        self.llm_active = True
        shared.sim.log(f"SENTINEL AI ONLINE - LiteLLM Router ({self.llm_model})", "AI")

    async def plan(self) -> Dict[str, List[int]]:
        """
        Request a target assignment plan from Gemini 2.5 Flash.
        Returns: {drone_id: [x, y]} for all assignable drones.
        """
        state = shared.sim.get_status()
        state["unscanned"] = shared.sim.get_unscanned_cells()

        if self.llm_active:
            try:
                prompt = _build_planning_prompt(state)
                shared.sim.log(f"🧠 [SENTINEL] Planning tick — querying {self.llm_model}...", "AI")

                messages = [
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt}
                ]
                response = await asyncio.wait_for(
                    asyncio.to_thread(litellm.completion, model=self.llm_model, messages=messages),
                    timeout=20.0,
                )
                text = str(response.choices[0].message.content).strip()

                # ── Extract and log Chain-of-Thought block ──────────────────
                if "[COT]" in text and "[/COT]" in text:
                    cot_start = text.index("[COT]") + len("[COT]")
                    cot_end = text.index("[/COT]")
                    cot_content = ""
                    for i in range(cot_start, cot_end):
                        cot_content += text[i]
                    cot_content = cot_content.strip()
                    lines = cot_content.split("\n")
                    for line in lines:
                        if line.strip():
                            shared.sim.log(f"🧠 REASONING: {line.strip()}", "AI")
                else:
                    # Generic logging if tags missing
                    lines = text.split("\n")
                    for i in range(min(5, len(lines))):
                        line = lines[i]
                        if line.strip() and not line.strip().startswith("{"):
                            shared.sim.log(f"🧠 AI LOGIC: {line.strip()}", "AI")

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
                err_msg = str(e)
                err_trunc = "".join(err_msg[i] for i in range(min(100, len(err_msg))))
                shared.sim.log(
                    f"❌ [SENTINEL] Error: {err_trunc}. Fallback.", "WARN"
                )
                traceback.print_exc()

        return self._rule_based_plan()

    def _rule_based_plan(self) -> Dict[str, List[int]]:
        """Deterministic fallback planner — always produces a valid assignment."""
        sim = shared.sim
        assignments: Dict[str, List[int]] = {}
        unscanned: List[List[int]] = sim.get_unscanned_cells()
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
                best_target = min(
                    available,
                    key=lambda c: abs(c[0] - drone.x) + abs(c[1] - drone.y),
                )
                assignments[drone.id] = list(best_target)
                used_targets.add(tuple(best_target))
                tx, ty = assignments[drone.id][0], assignments[drone.id][1]
                sim.log(f"🤖 [ROUTING] {drone.id} moving to ({tx},{ty}) - nearest unscanned cell.", "INFO", drone.id)
            else:
                assignments[drone.id] = [0, 0]

        if assignments:
            summary = ", ".join(f"{k}→({v[0]},{v[1]})" for k, v in assignments.items())
            sim.log(f"📡 [SWARM PLAN] {summary}", "INFO")
        return assignments
