import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.fallback import WeightedPlanner

POLL_WITH_LEAD = """--- MISSION OPTIONS MENU (Found: 0) ---
[DRONE: ALPHA-1] Battery: 80.0% @ (5,5)
  Opt 1: assign_scan_zone("ALPHA-1", "Z3") - Score=1.20, Transit=4, Cost=14.0, Risk=LOW, Terrain=[City:5 Flat:20], Scanned=0%
  Opt 2: assign_scan_zone("ALPHA-1", "Z7") - Score=0.80, Transit=2, Cost=10.0, Risk=LOW, Terrain=[Flat:25], Scanned=0% [LEAD-NEARBY]
"""

def test_lead_nearby_scores_higher_than_plain():
    planner = WeightedPlanner()
    options = planner._parse_options(POLL_WITH_LEAD)
    opts = options["ALPHA-1"]
    # Z7 has LEAD-NEARBY bonus (+2.0); Z3 has higher base score
    # Z7 weighted: 0.80×3 + (1/2)×2 + 2.0 = 2.4+1.0+2.0 = 5.4
    # Z3 weighted: 1.20×3 + (1/4)×2 + 0.0 = 3.6+0.5+0.0 = 4.1
    assert opts[0]["zone"] == "Z7"

def test_lead_assigned_over_higher_base_score():
    planner = WeightedPlanner()
    actions = planner.assign(POLL_WITH_LEAD)
    assert actions[0] == ("assign", "ALPHA-1", "Z7")
