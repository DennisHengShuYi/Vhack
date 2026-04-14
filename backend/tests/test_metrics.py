# backend/tests/test_metrics.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from simulation import MissionMetrics, DroneMetrics, LOW_BATTERY_THRESHOLD, BATTERY_DRAIN_MOVE


def test_cells_per_full_charge():
    m = MissionMetrics(total_scannable_cells=200, total_victims=10)
    expected = (100.0 - LOW_BATTERY_THRESHOLD) / BATTERY_DRAIN_MOVE
    assert m.cells_per_full_charge == expected


def test_coverage_percent_zero_initially():
    m = MissionMetrics(total_scannable_cells=200, total_victims=10)
    assert m.coverage_percent == 0.0


def test_detection_rate_zero_initially():
    m = MissionMetrics(total_scannable_cells=200, total_victims=10)
    assert m.detection_rate_percent == 0.0


def test_drone_metrics_default():
    dm = DroneMetrics(drone_id="ALPHA-1")
    assert dm.cells_moved == 0
    assert dm.scans_performed == 0
    assert dm.charges_count == 0


from simulation import SimulationState


def _make_sim():
    """Create a SimulationState with a fixed layout for testing."""
    import random
    random.seed(42)
    return SimulationState()


def test_metrics_initialised_on_sim():
    sim = _make_sim()
    assert hasattr(sim, 'metrics')
    assert sim.metrics.total_scannable_cells > 0
    assert sim.metrics.total_victims > 0


def test_scan_increments_cells_scanned():
    import random
    random.seed(42)
    sim = _make_sim()
    sim.mission_active = True
    # Activate first drone manually
    drone = list(sim.drones.values())[0]
    drone.is_active = True
    drone_id = drone.id
    sim.metrics.init_drone(drone_id)
    before = sim.metrics.total_cells_scanned
    sim.scan(drone_id)
    assert sim.metrics.total_cells_scanned == before + 1


def test_charge_step_increments_charges():
    import random
    random.seed(42)
    sim = _make_sim()
    sim.mission_active = True
    drone = list(sim.drones.values())[0]
    drone.is_active = True
    drone.battery = 0.0
    drone.x, drone.y = sim.base_station  # Position drone at base
    drone_id = drone.id
    sim.metrics.init_drone(drone_id)
    sim.charge_step(drone_id)
    assert sim.metrics.per_drone[drone_id].charges_count == 1
