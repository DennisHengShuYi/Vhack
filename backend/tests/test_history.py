import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

def _make_app_and_client(mock_client):
    patcher = patch("backend.history.get_client", return_value=mock_client)
    patcher.start()
    import importlib
    import backend.history as h
    importlib.reload(h)
    # re-patch after reload so the reloaded module's name is replaced
    patcher.stop()
    patcher2 = patch("backend.history.get_client", return_value=mock_client)
    patcher2.start()
    app = FastAPI()
    app.include_router(h.router)
    client = TestClient(app)
    return client, patcher2

MOCK_MISSION = {
    "id": "abc-123", "started_at": "2026-04-14T21:34:00+00:00",
    "ended_at": "2026-04-14T21:38:12+00:00", "status": "COMPLETE",
    "total_victims": 10, "victims_found": 8, "victims_rescued": 7,
    "avg_time_to_find_s": 38.0,
}


def test_list_missions_returns_list():
    mc = MagicMock()
    mc.table.return_value.select.return_value.order.return_value.execute.return_value.data = [MOCK_MISSION]
    client, patcher = _make_app_and_client(mc)
    try:
        resp = client.get("/missions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert resp.json()[0]["id"] == "abc-123"
    finally:
        patcher.stop()


def test_get_mission_detail():
    mc = MagicMock()
    mc.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = MOCK_MISSION
    client, patcher = _make_app_and_client(mc)
    try:
        resp = client.get("/missions/abc-123")
        assert resp.status_code == 200
        assert resp.json()["id"] == "abc-123"
    finally:
        patcher.stop()


def test_get_replay():
    mc = MagicMock()
    mc.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "ticks": [{"tick": 0}, {"tick": 5}]
    }
    client, patcher = _make_app_and_client(mc)
    try:
        resp = client.get("/missions/abc-123/replay")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
    finally:
        patcher.stop()
