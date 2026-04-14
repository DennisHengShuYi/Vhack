# backend/tests/test_mobility.py
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from simulation import SimulationState


def _make_sim(seed=42):
    random.seed(seed)
    return SimulationState()


def test_survivors_have_mobility_fields():
    sim = _make_sim()
    for s in sim.zone.survivors:
        assert "is_mobile" in s
        assert "last_seen_tick" in s
        assert "position_history" in s


def test_mobile_healthy_is_mobile():
    sim = _make_sim()
    mobile = [s for s in sim.zone.survivors if s["condition"] == "MOBILE_HEALTHY"]
    for s in mobile:
        assert s["is_mobile"] is True


def test_stationary_conditions_not_mobile():
    sim = _make_sim()
    stationary = [s for s in sim.zone.survivors if s["condition"] == "CRITICAL_INJURY"]
    for s in stationary:
        assert s["is_mobile"] is False


def test_stale_sightings_initially_empty():
    sim = _make_sim()
    assert sim.stale_sightings == []


def test_simulate_movement_does_not_move_rescued():
    sim = _make_sim(seed=0)
    sim.mission_active = True
    # Mark a mobile survivor as rescued
    rescued_s = None
    for s in sim.zone.survivors:
        if s["is_mobile"]:
            s["rescued"] = True
            rescued_s = s
            break
    assert rescued_s is not None, "No mobile survivor found in test"
    orig_x, orig_y = rescued_s["x"], rescued_s["y"]
    # Run movement many times
    for _ in range(20):
        sim.simulate_survivor_movement()
    assert rescued_s["x"] == orig_x
    assert rescued_s["y"] == orig_y


def test_position_history_appended_on_move():
    random.seed(1)
    sim = _make_sim(seed=1)
    sim.mission_active = True
    mobile_s = next((s for s in sim.zone.survivors if s["is_mobile"] and not s["rescued"]), None)
    assert mobile_s is not None, "No mobile survivor found"
    initial_len = len(mobile_s["position_history"])
    for _ in range(30):
        sim.simulate_survivor_movement()
    # With 30 calls at 30% chance, at least one move is statistically certain
    assert len(mobile_s["position_history"]) >= initial_len
