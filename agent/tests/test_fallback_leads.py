import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.fallback import WeightedPlanner

POLL_WITH_LEAD = """--- MISSION OPTIONS MENU (Found: 0) ---
[DRONE: ALPHA-1] Battery: 80.0% @ (5,5)
  Opt 1: assign_scan_zone("ALPHA-1", "Z3") - Score=0.90, Transit=4, Cost=14.0, Risk=LOW, Terrain=[City:5 Flat:20], Scanned=0%
  Opt 2: assign_scan_zone("ALPHA-1", "Z7") - Score=0.80, Transit=2, Cost=10.0, Risk=LOW, Terrain=[Flat:25], Scanned=0% [LEAD-NEARBY]
"""

def test_lead_nearby_scores_higher_than_plain():
    planner = WeightedPlanner()
    options = planner._parse_options(POLL_WITH_LEAD)
    opts = options["ALPHA-1"]
    # Real formula: score×6.0 + (1/√transit)×1.5 + 2.0 (if LEAD-NEARBY)
    # Z3 weighted: 0.90×6.0 + (1/√4)×1.5 + 0.0 = 5.40 + 0.75 + 0.0 = 6.15
    # Z7 weighted: 0.80×6.0 + (1/√2)×1.5 + 2.0 = 4.80 + 1.06 + 2.0 = 7.86
    # Z7 wins despite lower base score because LEAD-NEARBY tips the balance.
    assert opts[0]["zone"] == "Z7"

def test_lead_assigned_over_higher_base_score():
    planner = WeightedPlanner()
    actions = planner.assign(POLL_WITH_LEAD)
    assert actions[0] == ("assign", "ALPHA-1", "Z7")
