import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.hooks import ToolHooks
from agent.memory import MissionMemory

def _state_with_drone(battery):
    return {"drones": [{"id": "ALPHA-1", "battery": battery}], "zone": {"zones": {}}}

def test_investigate_lead_blocked_low_battery():
    hooks = ToolHooks(MissionMemory())
    result = hooks.pre_investigate_lead("ALPHA-1", 5, 5, _state_with_drone(20.0))
    assert result is False

def test_investigate_lead_allowed_sufficient_battery():
    hooks = ToolHooks(MissionMemory())
    result = hooks.pre_investigate_lead("ALPHA-1", 5, 5, _state_with_drone(50.0))
    assert result is True
