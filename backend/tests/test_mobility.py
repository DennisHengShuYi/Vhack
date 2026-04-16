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


def test_simulate_movement_does_not_move_rescued():
    sim = _make_sim(seed=0)
    sim.mission_active = True
    rescued_s = None
    for s in sim.zone.survivors:
        if s["is_mobile"]:
            s["rescued"] = True
            rescued_s = s
            break
    assert rescued_s is not None, "No mobile survivor found in test"
    orig_x, orig_y = rescued_s["x"], rescued_s["y"]
    for _ in range(20):
        sim.simulate_survivor_movement()
    assert rescued_s["x"] == orig_x
    assert rescued_s["y"] == orig_y


def test_simulate_movement_does_not_move_found():
    """Once a survivor is found they must not drift."""
    sim = _make_sim(seed=2)
    sim.mission_active = True
    found_s = None
    for s in sim.zone.survivors:
        if s["is_mobile"]:
            s["found"] = True
            found_s = s
            break
    assert found_s is not None, "No mobile survivor found in test"
    orig_x, orig_y = found_s["x"], found_s["y"]
    for _ in range(20):
        sim.simulate_survivor_movement()
    assert found_s["x"] == orig_x
    assert found_s["y"] == orig_y


def test_mobile_survivor_stays_in_unscanned_cells():
    """Survivor must never drift into an already-scanned cell."""
    random.seed(5)
    sim = _make_sim(seed=5)
    sim.mission_active = True
    # Mark all cells as scanned except a 2x2 pocket so survivor can still move within it
    for y in range(sim.zone.height):
        for x in range(sim.zone.width):
            sim.zone.scanned_cells[y][x] = True
    mobile_s = next((s for s in sim.zone.survivors if s["is_mobile"] and not s["found"]), None)
    if mobile_s is None:
        return  # no mobile survivor spawned with this seed, skip
    # Unscanned a 2x2 area around the survivor so they have somewhere to go
    sx, sy = mobile_s["x"], mobile_s["y"]
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            nx, ny = sx + dx, sy + dy
            if 0 <= nx < sim.zone.width and 0 <= ny < sim.zone.height:
                sim.zone.scanned_cells[ny][nx] = False
    for _ in range(30):
        sim.simulate_survivor_movement()
        assert not sim.zone.scanned_cells[mobile_s["y"]][mobile_s["x"]], (
            f"Survivor moved into scanned cell ({mobile_s['x']},{mobile_s['y']})"
        )
