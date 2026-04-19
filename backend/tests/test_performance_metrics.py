# backend/tests/test_performance_metrics.py
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from simulation import MissionMetrics


def test_planning_latency_tracks():
    m = MissionMetrics(total_scannable_cells=200, total_victims=5)
    m.record_planning_latency(320.0)
    m.record_planning_latency(280.0)
    assert m.avg_planning_latency_ms == 300.0


def test_first_find_tick_set_once():
    m = MissionMetrics(total_scannable_cells=200, total_victims=5)
    m.record_first_find(tick=12)
    m.record_first_find(tick=20)  # should be ignored
    assert m.first_find_tick == 12


def test_to_dict_includes_performance_keys():
    m = MissionMetrics(total_scannable_cells=200, total_victims=5)
    d = m.to_dict()
    assert "performance" in d
    perf = d["performance"]
    assert "avg_planning_latency_ms" in perf
    assert "first_find_tick" in perf
    assert "battery_consumed_total" in perf
