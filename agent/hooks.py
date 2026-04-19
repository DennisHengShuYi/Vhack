"""
ToolHooks — Pre/PostToolUse validation layer (Group B).

Pre-hooks validate tool parameters before the MCP call:
  - Battery gate: auto-convert low-battery assign_scan_zone → return_to_base
  - Zone conflict gate: reject IN_PROGRESS zone assignments early

Post-hooks update MissionMemory immediately after successful calls:
  - post_assign: tier 1 event on every successful assignment
  - post_detect: tier 0 event the moment a survivor is detected

Wire into agent.py _parallel_execute() — pass the current tick and shared
MissionMemory instance so hooks can write directly to memory.
"""

import sys

# Minimum battery a drone must have AFTER zone cost estimate to accept assignment.
# Set conservatively — real cost check is already done in get_idle_drones(),
# this gate catches LLM assignments that ignore the battery constraint.
BATTERY_FLOOR = 30.0   # % remaining after assignment (rough guard)
MIN_BATTERY_TO_ASSIGN = 35.0  # never assign a drone below this absolute level


class ToolHooks:

    def __init__(self, memory) -> None:
        """
        Args:
            memory: MissionMemory instance shared with AgentOrchestrator.
        """
        self.memory = memory

    # ── Pre-hooks ─────────────────────────────────────────────────────────────

    def pre_assign(
        self, drone_id: str, zone_id: str, state: dict
    ) -> tuple[str, str] | None:
        """
        Validate assign_scan_zone before the MCP call.

        Returns (drone_id, zone_id) to proceed, or None to RTB instead.

        Gate 1 — Zone conflict: zone already IN_PROGRESS → skip (prevents
        the "zone already IN_PROGRESS" MCP errors that pollute the session log).

        Gate 2 — Battery floor: drone battery below MIN_BATTERY_TO_ASSIGN →
        convert to RTB rather than sending a near-dead drone to a zone.
        """
        zones = state.get("zone", {}).get("zones", {})
        zone = zones.get(zone_id)
        if zone is not None:
            status = zone.get("status", "")
            # Normalise to uppercase string — handles both enum and plain str
            if isinstance(status, str):
                status_upper = status.upper()
            else:
                status_upper = str(status).upper()
            if "IN_PROGRESS" in status_upper:
                print(
                    f"  [HOOK] pre_assign blocked: {zone_id} already IN_PROGRESS"
                    f" — converting {drone_id} to RTB",
                    file=sys.stderr,
                )
                return None  # → RTB

        drones_by_id = {d["id"]: d for d in state.get("drones", [])}
        drone = drones_by_id.get(drone_id)
        if drone is not None:
            battery = drone.get("battery", 100.0)
            if battery < MIN_BATTERY_TO_ASSIGN:
                print(
                    f"  [HOOK] pre_assign blocked: {drone_id} battery {battery:.1f}%"
                    f" < {MIN_BATTERY_TO_ASSIGN}% floor — converting to RTB",
                    file=sys.stderr,
                )
                return None  # → RTB

        return (drone_id, zone_id)

    def pre_investigate_lead(
        self, drone_id: str, x: int, y: int, state: dict
    ) -> bool:
        """Returns True to proceed, False to block (drone RTBs instead)."""
        drones_by_id = {d["id"]: d for d in state.get("drones", [])}
        drone = drones_by_id.get(drone_id)
        if drone is not None:
            battery = drone.get("battery", 100.0)
            if battery < MIN_BATTERY_TO_ASSIGN:
                print(
                    f"  [HOOK] pre_investigate_lead blocked: {drone_id} battery {battery:.1f}%"
                    f" < {MIN_BATTERY_TO_ASSIGN}% — converting to RTB",
                    file=sys.stderr,
                )
                return False
        return True

    # ── Post-hooks ────────────────────────────────────────────────────────────

    def post_assign(
        self, drone_id: str, zone_id: str, result_text: str, tick: int
    ) -> None:
        """
        Called immediately after a successful assign_scan_zone MCP call.
        Writes a tier 1 memory event so the LLM sees it on the very next tick
        rather than waiting for extract() to run at tick end.
        """
        self.memory._append(1, f"Tick {tick}: {drone_id}→{zone_id} assigned [hook]")

    def post_detect(self, drone_id: str, content: str, tick: int) -> None:
        """
        Called when a tool result contains survivor detection language.
        Writes a tier 0 memory event immediately — critical intel is never
        delayed by a full tick.
        """
        self.memory._append(
            0,
            f"Tick {tick}: Survivor detected by {drone_id} — {content[:80].strip()}",
        )
