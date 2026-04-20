import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.memory import MissionMemory

def test_critical_grounded_lead_goes_tier0():
    m = MissionMemory()
    class FakeMsg:
        type = "tool"
        content = "Lead grounded at (4,7) — CRITICAL urgency"
    m.extract([FakeMsg()], tick=10)
    assert any("CRITICAL lead" in e for e in m.tier0)

def test_investigate_lead_goes_tier1():
    m = MissionMemory()
    class FakeMsg:
        type = "tool"
        content = "ALPHA-2 investigating lead at (3,5)"
    m.extract([FakeMsg()], tick=15)
    assert any("investigating lead" in e.lower() for e in m.tier1)
