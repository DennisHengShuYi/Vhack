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
