"""
MissionFlusher — reads completed sim state + JSONL, writes to Supabase.

Called once per mission in a background thread from server.py.
Never raises — errors are logged to stderr.
"""
import json
import sys
import uuid as uuid_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPORTS_DIR = Path(__file__).parent.parent / "mission_reports"


def flush_mission(sim, client) -> Optional[str]:
    """
    Build summary from sim state + latest JSONL and insert to Supabase.
    Returns the new mission_id (uuid str) or None on any error.
    """
    mission_id = str(uuid_mod.uuid4())
    try:
        summary = _build_summary(mission_id, sim, REPORTS_DIR)
        client.table("missions").insert(summary).execute()
        client.table("mission_ticks").insert({
            "mission_id": mission_id,
            "ticks": sim._replay_buffer,
        }).execute()
        print(f"[FLUSH] Mission {mission_id} persisted to Supabase.", file=sys.stderr)
        return mission_id
    except Exception as exc:
        print(f"[FLUSH] Supabase flush failed — {exc}", file=sys.stderr)
        return None


def _build_summary(mission_id: str, sim, reports_dir: Path) -> dict:
    metrics = sim.metrics.to_dict()
    ticks = _load_latest_jsonl(reports_dir)

    llm = sum(1 for t in ticks if t.get("decision", {}).get("type") == "LLM")
    auto = sum(1 for t in ticks if t.get("decision", {}).get("type") == "AUTO")
    fallback = sum(1 for t in ticks if t.get("decision", {}).get("type") == "SMART-FALLBACK")
    violations = sum(
        1 for t in ticks for a in t.get("contract_alerts", []) if a
    )

    # Zone completion times
    zone_times: dict = {}
    for zid, zone in sim.zone.zones.items():
        if getattr(zone, "completed_tick", None) is not None and zone.assigned_to:
            start_t = getattr(zone, "started_tick", 0) or 0
            duration_ticks = max(1, zone.completed_tick - start_t)
            zone_times[zid] = {
                "drone": zone.assigned_to,
                "duration_s": round(duration_ticks * 0.7, 1),
            }

    # Survivor discovery list
    survivors_data = []
    for s in sim.zone.survivors:
        if s.get("found"):
            found_tick = s.get("found_tick", 0)
            survivors_data.append({
                "tick": found_tick,
                "priority": s.get("triage_priority", "P3-STABLE"),
                "condition": s.get("condition", "UNKNOWN"),
                "drone": s.get("found_by_drone", ""),
                "rescue_s": round(max(0, (s.get("rescue_tick", found_tick) - found_tick)) * 0.7, 1),
            })

    avg_time = 0.0
    if survivors_data:
        avg_time = round(
            sum(s["tick"] * 0.7 for s in survivors_data) / len(survivors_data), 1
        )

    total_ticks = max(sim.tick_count, 1)
    per_drone: dict = {}
    for d_id, dm in metrics.get("per_drone", {}).items():
        per_drone[d_id] = {
            **dm,
            "utilisation_pct": round((1 - dm.get("idle_ticks", 0) / total_ticks) * 100, 1),
        }

    started_at = datetime.fromtimestamp(
        sim.mission_start_time or 0, tz=timezone.utc
    ).isoformat()
    ended_at = datetime.fromtimestamp(
        sim.mission_end_time or 0, tz=timezone.utc
    ).isoformat()

    return {
        "id": mission_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "status": "COMPLETE" if sim.mission_end_time and not sim.mission_active else "PARTIAL",
        "total_victims": metrics.get("total_victims", 0),
        "victims_found": metrics.get("victims_found", 0),
        "victims_rescued": metrics.get("victims_rescued", 0),
        "coverage_pct": metrics.get("coverage_percent", 0.0),
        "detection_rate_pct": metrics.get("detection_rate_percent", 0.0),
        "false_positives": metrics.get("false_positives", 0),
        "avg_time_to_find_s": avg_time,
        "llm_ticks": llm,
        "auto_ticks": auto,
        "fallback_ticks": fallback,
        "contract_violations": violations,
        "zone_times": zone_times,
        "per_drone": per_drone,
        "survivors": survivors_data,
    }


def _load_latest_jsonl(reports_dir: Path) -> list:
    if not reports_dir.exists():
        return []
    files = sorted(reports_dir.glob("*.jsonl"))
    if not files:
        return []
    result = []
    with open(files[-1], encoding="utf-8") as fh:
        for line in fh:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return result
