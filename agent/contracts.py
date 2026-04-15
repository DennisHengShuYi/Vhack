"""
ContractChecker — self-monitoring rules for SENTINEL agent.

4 contracts evaluated each tick against /state data.
Returns alert strings injected into poll text before LLM or WeightedPlanner.

Hard constraint: only observable data used — no victim counts or unfound locations.
"""

# Zone row membership for row-gap contract
ROW_ZONES: dict[int, set[str]] = {
    0: {"Z0", "Z1", "Z2", "Z3"},
    1: {"Z4", "Z5", "Z6", "Z7"},
    2: {"Z8", "Z9", "Z10", "Z11"},
}

IDLE_THRESHOLD = 15
ZONE_UNASSIGNED_THRESHOLD = 15
HIGH_SCORE_THRESHOLD = 1.5
ROW_GAP_THRESHOLD = 20


class ContractChecker:

    def __init__(self) -> None:
        self.idle_since: dict[str, int] = {}
        self.zone_unassigned_since: dict[str, int] = {}
        self.row_gap_since: dict[int, int] = {}

    def reset(self) -> None:
        """Clear counters — call on MISSION START."""
        self.idle_since = {}
        self.zone_unassigned_since = {}
        self.row_gap_since = {}

    def check(self, state: dict, tick: int) -> list[str]:
        """
        Evaluate all contracts. Returns alert strings (empty list if none violated).
        state: dict from GET /state. tick: current agent tick counter.
        """
        if not state.get("stats", {}).get("mission_active", False):
            return []
        alerts: list[str] = []
        alerts.extend(self._coverage_pace(state, tick))
        alerts.extend(self._idle_drones(state, tick))
        alerts.extend(self._high_score_zones(state, tick))
        alerts.extend(self._row_gaps(state, tick))
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

    def _idle_drones(self, state: dict, tick: int) -> list[str]:
        alerts: list[str] = []
        active_ids: set[str] = set()
        for drone in state.get("drones", []):
            did = drone["id"]
            if not drone.get("is_active", True):
                continue
            active_ids.add(did)
            is_idle = (
                drone.get("status", "").lower() == "idle"
                and not drone.get("assigned_zone_id")
            )
            if is_idle:
                self.idle_since.setdefault(did, tick)
                if tick - self.idle_since[did] >= IDLE_THRESHOLD:
                    alerts.append(
                        f"⚠ CONTRACT: {did} idle {tick - self.idle_since[did]} ticks"
                        f" — must be assigned immediately"
                    )
            else:
                self.idle_since.pop(did, None)
        for gone in set(self.idle_since) - active_ids:
            del self.idle_since[gone]
        return alerts

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

    def _row_gaps(self, state: dict, tick: int) -> list[str]:
        alerts: list[str] = []
        assigned = {
            d.get("assigned_zone_id")
            for d in state.get("drones", [])
            if d.get("assigned_zone_id") and d.get("is_active", True)
        }
        for row, zone_set in ROW_ZONES.items():
            if any(z in assigned for z in zone_set):
                self.row_gap_since.pop(row, None)
            else:
                self.row_gap_since.setdefault(row, tick)
                if tick - self.row_gap_since[row] >= ROW_GAP_THRESHOLD:
                    alerts.append(
                        f"⚠ CONTRACT: Row {row} (zones {sorted(zone_set)})"
                        f" has no active drone — risk of missed cells"
                    )
        return alerts
