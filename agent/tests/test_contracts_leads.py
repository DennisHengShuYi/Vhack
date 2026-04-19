import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.contracts import ContractChecker

def _state_with_lead(status, tick_added=0):
    return {
        "stats": {"coverage_pct": 50.0, "mission_active": True},
        "drones": [{"id": "ALPHA-1", "status": "scanning", "assigned_zone_id": "Z0", "is_active": True}],
        "zone": {"zones": {"Z0": {"status": "IN_PROGRESS", "score": 1.0}}},
        "leads": [{"id": "L0001", "status": status, "x": 4, "y": 7, "urgency": "CRITICAL", "tick": tick_added}],
    }

def test_unaddressed_lead_alert_after_10_ticks():
    checker = ContractChecker()
    for t in range(1, 12):
        alerts = checker.check(_state_with_lead("GROUNDED", tick_added=0), tick=t)
    assert any("lead" in a.lower() for a in alerts)

def test_investigating_lead_no_alert():
    checker = ContractChecker()
    for t in range(1, 20):
        alerts = checker.check(_state_with_lead("INVESTIGATING"), tick=t)
    assert not any("lead" in a.lower() for a in alerts)
