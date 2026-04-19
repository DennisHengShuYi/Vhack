import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.contracts import ContractChecker


def _state(coverage=50.0, drones=None, zones=None):
    return {
        "stats": {"coverage_pct": coverage, "mission_active": True},
        "drones": drones or [
            {"id": "ALPHA-1", "status": "scanning", "assigned_zone_id": "Z0", "is_active": True},
            {"id": "ALPHA-2", "status": "scanning", "assigned_zone_id": "Z5", "is_active": True},
            {"id": "ALPHA-3", "status": "scanning", "assigned_zone_id": "Z9", "is_active": True},
        ],
        "zone": {"zones": zones or {
            "Z0": {"status": "IN_PROGRESS", "score": 2.5},
            "Z5": {"status": "IN_PROGRESS", "score": 1.2},
            "Z9": {"status": "IN_PROGRESS", "score": 0.8},
        }},
    }


def test_no_alerts_when_healthy():
    checker = ContractChecker()
    # coverage 30% at tick 80 — expected (80/300)*100 = 26.7% — OK
    assert checker.check(_state(coverage=30.0), tick=80) == []


def test_coverage_pace_alert():
    checker = ContractChecker()
    # coverage 5% at tick 150 — expected 50% — too slow
    alerts = checker.check(_state(coverage=5.0), tick=150)
    assert any("Coverage pace" in a for a in alerts)


def test_high_score_zone_unassigned_alert():
    checker = ContractChecker()
    zones = {"Z0": {"status": "UNSCANNED", "score": 2.8}, "Z5": {"status": "IN_PROGRESS", "score": 1.0}}
    drones = [{"id": "ALPHA-1", "status": "scanning", "assigned_zone_id": "Z5", "is_active": True}]
    for t in range(1, 17):
        alerts = checker.check(_state(drones=drones, zones=zones), tick=t)
    assert any("Z0" in a for a in alerts)


def test_high_score_zone_no_alert_when_assigned():
    checker = ContractChecker()
    zones = {"Z0": {"status": "IN_PROGRESS", "score": 2.8}}
    drones = [{"id": "ALPHA-1", "status": "scanning", "assigned_zone_id": "Z0", "is_active": True}]
    for t in range(1, 20):
        alerts = checker.check(_state(drones=drones, zones=zones), tick=t)
    assert not any("Z0" in a for a in alerts)


def test_reset_clears_counters():
    checker = ContractChecker()
    # High-score zone unassigned for 16 ticks triggers alert
    zones = {"Z0": {"status": "UNSCANNED", "score": 2.8}}
    drones = [{"id": "ALPHA-1", "status": "scanning", "assigned_zone_id": "Z5", "is_active": True}]
    for t in range(1, 17):
        checker.check(_state(drones=drones, zones=zones), tick=t)
    checker.reset()
    # After reset, counter clears — no alert on next tick
    alerts = checker.check(_state(drones=drones, zones=zones), tick=17)
    assert not any("Z0" in a for a in alerts)
