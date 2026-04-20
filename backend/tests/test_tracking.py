import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.simulation import SimulationState, Zone, ZoneStatus


def test_survivor_found_tick_recorded():
    sim = SimulationState(num_victims=1)
    sim.tick_count = 42
    # Force a survivor to position (0,0) so scan() finds it
    sim.zone.survivors[0]["x"] = 0
    sim.zone.survivors[0]["y"] = 0
    sim.zone.scanned_cells[0][0] = False
    sim.zone.hazard_cells[0][0] = False
    drone = list(sim.drones.values())[0]
    drone.x, drone.y = 0, 0
    drone.is_active = True
    sim.scan(drone.id)
    s = sim.zone.survivors[0]
    if s["found"]:
        assert s.get("found_tick") == 42
        assert s.get("found_by_drone") == drone.id


def test_zone_completed_tick_recorded():
    zone = Zone(id="Z0", sx=0, sy=0, ex=4, ey=4)
    assert zone.completed_tick is None
    zone.completed_tick = 55
    assert zone.completed_tick == 55


def test_replay_buffer_appended():
    sim = SimulationState(num_victims=0)
    sim.tick_count = 10
    sim.append_replay_snapshot(events=[])
    assert len(sim._replay_buffer) == 1
    snap = sim._replay_buffer[0]
    assert snap["tick"] == 10
    assert "drones" in snap
    assert "zones" in snap
    assert "coverage_pct" in snap
