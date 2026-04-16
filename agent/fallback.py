"""
WeightedPlanner — scored rule-based drone assignment.

Replaces greedy _rule_based_assignments() in agent.py.
Parses all options from get_idle_drones() poll text — no extra MCP calls.

Score = (zone_score × 3.0) + (1/transit × 2.0) + (gap_row × 1.0) + (partial × 0.5)
"""
import re
from typing import Optional


class WeightedPlanner:

    _DRONE_RE = re.compile(r'\[DRONE:\s*(\S+)\]')
    _OPT_RE = re.compile(
        r'Opt\s+\d+:\s*assign_scan_zone\(\"([^\"]+)\",\s*\"([^\"]+)\"\)'
        r'.*?Score[=:]\s*([\d.]+).*?Transit[=:]\s*(\d+)'
    )
    _RTB_RE = re.compile(r'return_to_base\(\).*?Battery too low', re.IGNORECASE)
    _IDLE_RE = re.compile(r'Idle drones \[([^\]]+)\]')

    def assign(self, poll_text: str) -> list[tuple[str, str, Optional[str]]]:
        """
        Parse poll text and return assignments.
        Returns [("assign", drone_id, zone_id) | ("return", drone_id, None)].
        Caller logs with [SMART-FALLBACK] tag.
        """
        if "NO_ZONES_AVAILABLE" in poll_text:
            return self._rtb_idle_drones(poll_text)
        return self._greedy_assign(self._parse_options(poll_text))

    def _parse_options(self, poll_text: str) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        current_drone: Optional[str] = None
        current_opts: list[dict] = []

        for line in poll_text.splitlines():
            drone_match = self._DRONE_RE.search(line)
            if drone_match:
                if current_drone is not None and current_opts:
                    result[current_drone] = sorted(
                        current_opts, key=self._score, reverse=True
                    )
                current_drone = drone_match.group(1)
                current_opts = []
                continue

            if current_drone is None:
                continue

            if self._RTB_RE.search(line):
                result[current_drone] = [{"rtb": True}]
                current_drone = None
                current_opts = []
                continue

            m = self._OPT_RE.search(line)
            if m:
                current_opts.append({
                    "zone": m.group(2),
                    "score": float(m.group(3)),
                    "transit": int(m.group(4)),
                    "gap_row": "[GAP-ROW" in line,
                    "partial": "[PARTIAL-resume]" in line,
                    "rtb": False,
                })

        if current_drone is not None and current_opts:
            result[current_drone] = sorted(current_opts, key=self._score, reverse=True)

        return result

    def _score(self, opt: dict) -> float:
        if opt.get("rtb"):
            return -1.0
        return (
            opt["score"] * 3.0
            + (1.0 / max(opt["transit"], 1)) * 2.0
            + (1.0 if opt["gap_row"] else 0.0)
            + (0.5 if opt["partial"] else 0.0)
        )

    def _greedy_assign(
        self, options_by_drone: dict[str, list[dict]]
    ) -> list[tuple[str, str, Optional[str]]]:
        claimed: set[str] = set()
        actions: list[tuple[str, str, Optional[str]]] = []
        for drone_id, opts in options_by_drone.items():
            if not opts or opts[0].get("rtb"):
                actions.append(("return", drone_id, None))
                continue
            assigned = False
            for opt in opts:
                if opt["zone"] not in claimed:
                    actions.append(("assign", drone_id, opt["zone"]))
                    claimed.add(opt["zone"])
                    assigned = True
                    break
            if not assigned:
                actions.append(("return", drone_id, None))
        return actions

    def _rtb_idle_drones(self, poll_text: str) -> list[tuple[str, str, Optional[str]]]:
        m = self._IDLE_RE.search(poll_text)
        if not m:
            return []
        return [("return", d, None) for d in re.findall(r'ALPHA-\d+', m.group(1))]
