import sys, os, json, tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.simulation import SimulationState
import backend.mission_flusher as flusher


def _make_sim(found=True):
    sim = SimulationState(num_victims=2)
    sim.mission_start_time = 1_000_000.0
    sim.mission_end_time  = 1_000_252.0
    sim.tick_count = 360
    if found:
        sim.zone.survivors[0]["found"] = True
        sim.zone.survivors[0]["found_tick"] = 30
        sim.zone.survivors[0]["found_by_drone"] = "ALPHA-1"
        sim.zone.survivors[0]["triage_priority"] = "P1-CRITICAL"
        sim.zone.survivors[0]["condition"] = "CRITICAL_INJURY"
        sim.metrics.victims_found = 1
    sim._replay_buffer = [
        {"tick": 0, "coverage_pct": 0.0, "drones": {}, "zones": {}, "events": []},
        {"tick": 5, "coverage_pct": 3.1, "drones": {}, "zones": {}, "events": ["ALPHA-1→Z0"]},
    ]
    return sim


def _make_jsonl(tmp_dir: Path) -> Path:
    p = tmp_dir / "2026-04-15-10-00.jsonl"
    entries = [
        {"tick": i, "coverage_pct": i * 0.5,
         "drones": {}, "events": [],
         "decision": {"type": "LLM" if i % 3 == 0 else "AUTO", "assignments": [], "tokens": 0},
         "contract_alerts": ["Coverage pace" if i == 5 else ""],
         "errors": []}
        for i in range(10)
    ]
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return p


def test_build_summary_fields():
    sim = _make_sim()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _make_jsonl(tmp_path)
        summary = flusher._build_summary("test-uuid", sim, tmp_path)
    assert summary["id"] == "test-uuid"
    assert summary["status"] == "COMPLETE"
    assert summary["victims_found"] == 1
    assert summary["avg_time_to_find_s"] == round(30 * 0.7, 1)
    assert len(summary["survivors"]) == 1
    assert summary["survivors"][0]["priority"] == "P1-CRITICAL"
    assert summary["llm_ticks"] >= 0
    assert "ALPHA-1" in summary["per_drone"] or summary["per_drone"] == {}


def test_flush_calls_supabase(monkeypatch):
    sim = _make_sim()
    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _make_jsonl(tmp_path)
        monkeypatch.setattr(flusher, "REPORTS_DIR", tmp_path)
        result = flusher.flush_mission(sim, mock_client)

    assert result is not None
    assert mock_client.table.call_count == 2  # missions + mission_ticks


def test_flush_survives_supabase_error(monkeypatch):
    sim = _make_sim()
    mock_client = MagicMock()
    mock_client.table.side_effect = RuntimeError("connection failed")

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(flusher, "REPORTS_DIR", Path(tmp))
        result = flusher.flush_mission(sim, mock_client)

    assert result is None
