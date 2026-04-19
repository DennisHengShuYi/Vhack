"""
ContractChecker — self-monitoring rules for SENTINEL agent.

Evaluated each tick against /state data.
Returns alert strings injected into poll text before LLM or WeightedPlanner.

Hard constraint: only observable data used — no victim counts or unfound locations.
"""

ZONE_UNASSIGNED_THRESHOLD = 15
HIGH_SCORE_THRESHOLD = 1.5


class ContractChecker:

    def __init__(self) -> None:
        self.zone_unassigned_since: dict[str, int] = {}
        self.lead_unaddressed_since: dict[str, int] = {}

    def reset(self) -> None:
        """Clear counters — call on MISSION START."""
        self.zone_unassigned_since = {}
        self.lead_unaddressed_since = {}

    def check(self, state: dict, tick: int) -> list[str]:
        """
        Evaluate all contracts. Returns alert strings (empty list if none violated).
        state: dict from GET /state. tick: current agent tick counter.
        """
        if not state.get("stats", {}).get("mission_active", False):
            return []
        alerts: list[str] = []
        alerts.extend(self._coverage_pace(state, tick))
        alerts.extend(self._high_score_zones(state, tick))
        alerts.extend(self._unaddressed_leads(state, tick))
        return alerts

    def _coverage_pace(self, state: dict, tick: int) -> list[str]:
        coverage = state["stats"].get("coverage_pct", 0.0)
        expected = (tick / 300.0) * 100.0
        if coverage < expected:
            return [
                f"⚠ CONTRACT: Coverage pace too slow "
                f"({coverage:.0f}% actual vs {expected:.0f}% expected) — redistribute drones"
            ]
        return []

    def _high_score_zones(self, state: dict, tick: int) -> list[str]:
        alerts: list[str] = []
        zones = state.get("zone", {}).get("zones", {})
        assigned = {d.get("assigned_zone_id") for d in state.get("drones", []) if d.get("assigned_zone_id")}
        active_ids: set[str] = set()
        for zid, zone in zones.items():
            score = zone.get("score", 0.0)
            status = zone.get("status", "")
            if score <= HIGH_SCORE_THRESHOLD or status == "COMPLETE":
                self.zone_unassigned_since.pop(zid, None)
                continue
            active_ids.add(zid)
            if status == "UNSCANNED" and zid not in assigned:
                self.zone_unassigned_since.setdefault(zid, tick)
                if tick - self.zone_unassigned_since[zid] >= ZONE_UNASSIGNED_THRESHOLD:
                    alerts.append(
                        f"⚠ CONTRACT: Zone {zid} (Score {score:.1f}) unassigned"
                        f" {tick - self.zone_unassigned_since[zid]} ticks — assign immediately"
                    )
            else:
                self.zone_unassigned_since.pop(zid, None)
        for gone in set(self.zone_unassigned_since) - active_ids:
            del self.zone_unassigned_since[gone]
        return alerts

    LEAD_UNADDRESSED_THRESHOLD = 10

    def _unaddressed_leads(self, state: dict, tick: int) -> list[str]:
        alerts: list[str] = []
        active_ids: set[str] = set()
        for lead in state.get("leads", []):
            lid = lead.get("id", "")
            if lead.get("status") not in ("GROUNDED", "PENDING_GROUND"):
                self.lead_unaddressed_since.pop(lid, None)
                continue
            if lead.get("urgency") != "CRITICAL":
                continue
            active_ids.add(lid)
            self.lead_unaddressed_since.setdefault(lid, tick)
            age = tick - self.lead_unaddressed_since[lid]
            if age >= self.LEAD_UNADDRESSED_THRESHOLD:
                x, y = lead.get("x", "?"), lead.get("y", "?")
                alerts.append(
                    f"⚠ CONTRACT: CRITICAL lead [{lid}] at ({x},{y}) unaddressed"
                    f" {age} ticks — dispatch investigate_lead immediately"
                )
        for gone in set(self.lead_unaddressed_since) - active_ids:
            del self.lead_unaddressed_since[gone]
        return alerts
