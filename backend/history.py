"""
Mission History REST endpoints — mounted on FastAPI app in server.py.

GET /missions               List of mission summaries (no heavy fields)
GET /missions/insights      Agent cross-mission learning text block
GET /missions/{id}          Full mission detail
GET /missions/{id}/replay   Tick array for replay
"""
import sys
from fastapi import APIRouter, HTTPException
from supabase_client import get_client

router = APIRouter(prefix="/missions", tags=["history"])

_SUMMARY_COLS = (
    "id,started_at,ended_at,status,total_victims,"
    "victims_found,victims_rescued,avg_time_to_find_s"
)


@router.get("")
def list_missions():
    """Return all missions newest-first, summary fields only."""
    try:
        result = (
            get_client()
            .table("missions")
            .select(_SUMMARY_COLS)
            .order("started_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        print(f"[HISTORY] list_missions error: {exc}", file=sys.stderr)
        raise HTTPException(status_code=500, detail="Failed to fetch missions")


@router.get("/insights")
def get_insights():
    """
    Return historical intel text block for the agent's load_insights() fallback.
    """
    try:
        result = (
            get_client()
            .table("mission_ticks")
            .select("ticks")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        rows = result.data or []
        missions = [r["ticks"] for r in rows if r.get("ticks")]
        if not missions:
            return {"insights": ""}
        from agent.session_log import SessionLog
        insights = SessionLog()._compute_insights(missions)
        if not insights:
            return {"insights": ""}
        lines = [f"=== HISTORICAL INTEL (last {len(missions)} mission(s)) ==="]
        lines.extend(f"• {i}" for i in insights)
        lines.append("=== END HISTORICAL INTEL ===")
        return {"insights": "\n".join(lines)}
    except Exception as exc:
        print(f"[HISTORY] get_insights error: {exc}", file=sys.stderr)
        return {"insights": ""}


@router.get("/{mission_id}")
def get_mission(mission_id: str):
    """Return full mission detail including zone_times, per_drone, survivors."""
    try:
        result = (
            get_client()
            .table("missions")
            .select("*")
            .eq("id", mission_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Mission not found")
        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[HISTORY] get_mission error: {exc}", file=sys.stderr)
        raise HTTPException(status_code=500, detail="Failed to fetch mission")


@router.get("/{mission_id}/replay")
def get_replay(mission_id: str):
    """Return the downsampled tick array for replay."""
    try:
        result = (
            get_client()
            .table("mission_ticks")
            .select("ticks")
            .eq("mission_id", mission_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Replay data not found")
        return result.data.get("ticks", [])
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[HISTORY] get_replay error: {exc}", file=sys.stderr)
        raise HTTPException(status_code=500, detail="Failed to fetch replay data")
