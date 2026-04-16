"""
SessionLog — JSONL tick logger and cross-mission learning reader.

Write path: appends one JSON line per tick to mission_reports/<timestamp>.jsonl
Read path:  load_insights() reads last N JSONL files and returns a
            HISTORICAL INTEL prompt block injected at mission start.
"""
import json
import os
import re
import requests
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent / "mission_reports"
MAX_MISSIONS = 5
API_BASE = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")


class SessionLog:

    def __init__(self) -> None:
        self._path: Path | None = None
        self._file = None

    def start(self) -> None:
        """Open a new JSONL file. Call on MISSION START."""
        REPORTS_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d-%H-%M")
        self._path = REPORTS_DIR / f"{ts}.jsonl"
        self._file = open(self._path, "a", encoding="utf-8")

    def log_tick(
        self,
        tick: int,
        state: dict,
        events: list[str],
        decision_type: str,
        assignments: list[list[str]],
        tokens: int = 0,
        contract_alerts: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        """Append one tick entry. No-ops if start() was not called."""
        if self._file is None:
            return
        entry = {
            "tick": tick,
            "coverage_pct": state.get("stats", {}).get("coverage_pct", 0.0),
            "drones": {
                d["id"]: {
                    "battery": d.get("battery", 0),
                    "zone": d.get("assigned_zone_id"),
                    "status": d.get("status", ""),
                }
                for d in state.get("drones", [])
            },
            "events": events,
            "decision": {"type": decision_type, "assignments": assignments, "tokens": tokens},
            "contract_alerts": contract_alerts or [],
            "errors": errors or [],
        }
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def close(self) -> None:
        """Close file on MISSION COMPLETE."""
        if self._file:
            self._file.close()
            self._file = None

    def load_insights(self, n: int = MAX_MISSIONS) -> str:
        """
        Read last N JSONL files and return a HISTORICAL INTEL prompt block.
        Falls back to GET /missions/insights when no local files exist (cloud deploy).
        """
        if not REPORTS_DIR.exists() or not list(REPORTS_DIR.glob("*.jsonl")):
            return self._load_insights_from_api()

        files = sorted(REPORTS_DIR.glob("*.jsonl"))[-n:]
        missions = []
        for f in files:
            ticks = []
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        ticks.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if ticks:
                missions.append(ticks)
        if not missions:
            return self._load_insights_from_api()
        insights = self._compute_insights(missions)
        if not insights:
            return ""
        lines = [f"=== HISTORICAL INTEL (last {len(missions)} mission(s)) ==="]
        lines.extend(f"• {i}" for i in insights)
        lines.append("=== END HISTORICAL INTEL ===")
        return "\n".join(lines)

    def _load_insights_from_api(self) -> str:
        """Call backend GET /missions/insights when no local JSONL files exist."""
        try:
            resp = requests.get(f"{API_BASE}/missions/insights", timeout=3)
            if resp.status_code == 200:
                return resp.json().get("insights", "")
        except Exception:
            pass
        return ""

    def _compute_insights(self, missions: list[list[dict]]) -> list[str]:
        insights: list[str] = []

        # Battery drain per zone-tick
        drains = []
        for mission in missions:
            for i in range(1, len(mission)):
                prev, curr = mission[i - 1], mission[i]
                for did, data in curr["drones"].items():
                    prev_d = prev["drones"].get(did)
                    if prev_d and data["zone"] == prev_d["zone"]:
                        d = prev_d["battery"] - data["battery"]
                        if 0 < d < 50:
                            drains.append(d)
        if drains:
            avg = sum(drains) / len(drains)
            insights.append(
                f"Battery: avg drain {avg:.0f}% per zone — "
                f"assign drones with >{avg * 2:.0f}% battery to avoid mid-zone RTB"
            )

        # LLM vs fallback usage ratio
        llm = sum(1 for m in missions for t in m if t["decision"]["type"] == "LLM")
        fb  = sum(1 for m in missions for t in m if t["decision"]["type"] in ("SMART-FALLBACK", "AUTO"))
        if llm + fb > 0:
            pct = llm / (llm + fb) * 100
            insights.append(f"LLM usage: {pct:.0f}% of ticks used LLM reasoning vs weighted fallback")

        # Contract violation frequency
        all_alerts = [a for m in missions for t in m for a in t.get("contract_alerts", [])]
        cov = sum(1 for a in all_alerts if "Coverage pace" in a)
        idle = sum(1 for a in all_alerts if "idle" in a.lower())
        if cov > len(missions):
            insights.append(
                f"Contracts: coverage pace fired {cov}x across {len(missions)} missions — "
                f"spread drones across all rows at mission start"
            )
        if idle > len(missions):
            insights.append(f"Contracts: idle drone alert fired {idle}x — review assignment latency")

        # Zone conflict errors
        errors = [e for m in missions for t in m for e in t.get("errors", [])]
        conflicts = sum(1 for e in errors if "IN_PROGRESS" in e)
        if conflicts > 0:
            insights.append(
                f"Errors: zone IN_PROGRESS conflict appeared {conflicts}x — "
                f"zone conflict pre-check in hooks.py recommended"
            )

        # Drone utilisation — flag drones idle >25% of ticks
        util: dict[str, dict] = {}
        for mission in missions:
            for tick in mission:
                for did, data in tick["drones"].items():
                    util.setdefault(did, {"idle": 0, "total": 0})
                    util[did]["total"] += 1
                    if data.get("status", "").lower() == "idle":
                        util[did]["idle"] += 1
        for did, counts in util.items():
            if counts["total"] > 0:
                pct = counts["idle"] / counts["total"] * 100
                if pct > 25:
                    insights.append(
                        f"Utilisation: {did} idle {pct:.0f}% of ticks — "
                        f"assignment strategy may have a systematic gap"
                    )

        return insights
