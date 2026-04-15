"""
ToolHooks — Pre/PostToolUse validation layer (Group B — not yet wired).

Pre-hooks validate tool parameters before the MCP call:
  - Battery gate: auto-convert low-battery assign_scan_zone → return_to_base
  - Zone conflict gate: reject IN_PROGRESS zone assignments early

Post-hooks update state after successful calls:
  - post_assign: update MissionMemory tier 1
  - post_detect: immediately log tier 0 survivor event

Wire into agent.py _parallel_execute() when implementing Group B Phase 2.
"""


class ToolHooks:
    """Stub — interfaces defined, not yet implemented."""

    def pre_assign(self, drone_id: str, zone_id: str, state: dict) -> tuple[str, str] | None:
        """Validate assign_scan_zone. Returns (drone_id, zone_id) or None to RTB instead."""
        return (drone_id, zone_id)

    def post_assign(self, drone_id: str, zone_id: str, result: str) -> None:
        """Called after successful assign_scan_zone."""
        pass

    def post_detect(self, drone_id: str, content: str, tick: int) -> None:
        """Called when tool result contains survivor detection."""
        pass
