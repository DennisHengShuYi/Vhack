import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.fallback import WeightedPlanner

# Scoring sanity:
# Z0 GAP-ROW: (2.5×3.0) + (1/3×2.0) + 1.0 = 9.17
# Z5 plain:   (1.2×3.0) + (1/8×2.0)        = 3.85
# Z3 plain:   (1.0×3.0) + (1/10×2.0)       = 3.20
# Z7 PARTIAL: (0.9×3.0) + (1/4×2.0)  + 0.5 = 3.70  ← beats Z3

POLL_ONE_DRONE = """[DRONE: ALPHA-1] @ (2,1) | Battery: 80%
  Opt 1: assign_scan_zone("ALPHA-1", "Z0") | Score: 2.5 | Transit: 3 cells | Terrain: City:12 | [GAP-ROW]
  Opt 2: assign_scan_zone("ALPHA-1", "Z5") | Score: 1.2 | Transit: 8 cells | Terrain: Flat:10"""

POLL_TWO_DRONES = """[DRONE: ALPHA-1] @ (2,1) | Battery: 80%
  Opt 1: assign_scan_zone("ALPHA-1", "Z0") | Score: 2.5 | Transit: 3 cells | Terrain: City:12
  Opt 2: assign_scan_zone("ALPHA-1", "Z1") | Score: 1.8 | Transit: 6 cells | Terrain: City:5

[DRONE: ALPHA-2] @ (8,1) | Battery: 75%
  Opt 1: assign_scan_zone("ALPHA-2", "Z0") | Score: 2.5 | Transit: 5 cells | Terrain: City:12
  Opt 2: assign_scan_zone("ALPHA-2", "Z1") | Score: 1.8 | Transit: 2 cells | Terrain: City:5"""

POLL_RTB = """[DRONE: ALPHA-3] @ (4,7) | Battery: 22%
  return_to_base() | Battery too low for any zone"""

POLL_NO_ZONES = """NO_ZONES_AVAILABLE — all zones IN_PROGRESS or COMPLETE
Idle drones [ALPHA-2, ALPHA-4]: return_to_base()
Zones still being scanned: Z0→ALPHA-1, Z2→ALPHA-3"""

POLL_PARTIAL = """[DRONE: ALPHA-1] @ (2,1) | Battery: 80%
  Opt 1: assign_scan_zone("ALPHA-1", "Z3") | Score: 1.0 | Transit: 10 cells | Terrain: Flat:15
  Opt 2: assign_scan_zone("ALPHA-1", "Z7") | Score: 0.9 | Transit: 4 cells | Terrain: Flat:12 | [PARTIAL-resume]"""


def test_single_drone_assigned():
    actions = WeightedPlanner().assign(POLL_ONE_DRONE)
    assert len(actions) == 1
    assert actions[0] == ("assign", "ALPHA-1", "Z0")


def test_gap_row_bonus_wins():
    # Z0 has GAP-ROW: score 9.17 vs Z5: 3.85 — Z0 must win
    actions = WeightedPlanner().assign(POLL_ONE_DRONE)
    assert actions[0][2] == "Z0"


def test_partial_resume_bonus_flips_choice():
    # Z7 PARTIAL (3.70) beats Z3 plain (3.20) despite lower zone score
    actions = WeightedPlanner().assign(POLL_PARTIAL)
    assert actions[0][2] == "Z7"


def test_two_drones_no_zone_conflict():
    actions = WeightedPlanner().assign(POLL_TWO_DRONES)
    assert len(actions) == 2
    zones = [a[2] for a in actions]
    assert len(set(zones)) == 2


def test_two_drones_greedy_best_first():
    # ALPHA-1 processed first, takes Z0 (score 8.17)
    # ALPHA-2 falls back to Z1 (Z0 claimed)
    actions = WeightedPlanner().assign(POLL_TWO_DRONES)
    drone_map = {a[1]: a[2] for a in actions}
    assert drone_map["ALPHA-1"] == "Z0"
    assert drone_map["ALPHA-2"] == "Z1"


def test_rtb_when_battery_too_low():
    actions = WeightedPlanner().assign(POLL_RTB)
    assert actions == [("return", "ALPHA-3", None)]


def test_no_zones_rtbs_idle_drones_only():
    actions = WeightedPlanner().assign(POLL_NO_ZONES)
    assert len(actions) == 2
    assert {a[1] for a in actions} == {"ALPHA-2", "ALPHA-4"}
    assert all(a[0] == "return" for a in actions)
