import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from unittest.mock import patch, MagicMock
from agent.session_log import SessionLog


def test_load_insights_falls_back_to_api_when_no_local_files(tmp_path, monkeypatch):
    sl = SessionLog()
    monkeypatch.setattr("agent.session_log.REPORTS_DIR", tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"insights": "=== HISTORICAL INTEL ===\n• Battery avg drain 12%\n=== END HISTORICAL INTEL ==="}
    with patch("agent.session_log.requests.get", return_value=mock_resp) as mock_get:
        result = sl.load_insights()
    assert "HISTORICAL INTEL" in result
    mock_get.assert_called_once()


def test_load_insights_skips_api_when_local_files_exist(tmp_path, monkeypatch):
    (tmp_path / "2026-04-15-10-00.jsonl").write_text(
        '{"tick":0,"coverage_pct":0,"drones":{},"events":[],"decision":{"type":"AUTO","assignments":[],"tokens":0},"contract_alerts":[],"errors":[]}\n',
        encoding="utf-8"
    )
    monkeypatch.setattr("agent.session_log.REPORTS_DIR", tmp_path)
    with patch("agent.session_log.requests.get") as mock_get:
        SessionLog().load_insights()
    mock_get.assert_not_called()
