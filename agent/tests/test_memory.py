import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.memory import MissionMemory
from unittest.mock import MagicMock


def _tool(content: str):
    m = MagicMock(); m.type = "tool"; m.content = content; return m

def _ai():
    m = MagicMock(); m.type = "ai"; m.content = "reasoning"; return m


def test_survivor_goes_to_tier0():
    mem = MissionMemory()
    mem.extract([_tool("Survivor found at (4,7) — P1-CRITICAL triage")], tick=5)
    assert len(mem.tier0) == 1 and "Tick 5" in mem.tier0[0]


def test_critical_triage_goes_to_tier0():
    mem = MissionMemory()
    mem.extract([_tool("CRITICAL: victim requires immediate evacuation")], tick=10)
    assert len(mem.tier0) == 1


def test_zone_complete_goes_to_tier1():
    mem = MissionMemory()
    mem.extract([_tool("Zone Z3 is now COMPLETE — all cells scanned")], tick=20)
    assert len(mem.tier1) == 1 and "Z3" in mem.tier1[0]


def test_rtb_goes_to_tier1():
    mem = MissionMemory()
    mem.extract([_tool("ALPHA-2 low battery — RTB triggered at 23%")], tick=15)
    assert len(mem.tier1) == 1


def test_routine_assign_goes_to_tier2():
    mem = MissionMemory()
    # Fixed: added 'zone' to match MissionMemory._classify requirement
    mem.extract([_tool("ALPHA-3 assigned to zone Z6 — zig-zag sweep queued")], tick=3)
    assert len(mem.tier2) == 1


def test_tier0_capped_at_6_oldest_dropped():
    mem = MissionMemory()
    for i in range(10):
        mem.extract([_tool(f"Survivor found at ({i},0) — P1-CRITICAL triage")], tick=i)
    assert len(mem.tier0) == 6
    assert all("Survivor" in e for e in mem.tier0)


def test_prompt_block_includes_tier0():
    mem = MissionMemory()
    mem.extract([_tool("Survivor found at (4,7) — P1-CRITICAL triage")], tick=5)
    block = mem.to_prompt_block()
    assert "Tick 5" in block and "(4,7)" in block


def test_prompt_block_empty_when_no_events():
    assert MissionMemory().to_prompt_block() == ""


def test_reset_clears_all_tiers():
    mem = MissionMemory()
    mem.extract([_tool("Survivor found at (4,7) — P1-CRITICAL triage")], tick=5)
    mem.reset()
    assert mem.tier0 == [] and mem.tier1 == [] and mem.tier2 == []


def test_non_tool_messages_ignored():
    mem = MissionMemory()
    mem.extract([_ai(), _tool("Zone Z1 COMPLETE")], tick=8)
    assert len(mem.tier1) == 1 and len(mem.tier0) == 0
