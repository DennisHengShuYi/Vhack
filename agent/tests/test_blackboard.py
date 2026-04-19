"""Tests for Blackboard data structure and zone claim logic."""
import asyncio
import pytest
from agent.agent import Blackboard, ZoneClaim


def make_blackboard(tick: int = 0) -> Blackboard:
    return Blackboard(
        priority_map={},
        posture="SPREAD",
        urgent_redirect=None,
        updated_at_tick=tick,
        tick=tick,
        zone_claims={},
        lock=asyncio.Lock(),
    )


def test_commit_zone_adds_claim():
    bb = make_blackboard(tick=10)
    bb.zone_claims["Z1"] = ZoneClaim(drone_id="ALPHA-1", committed_at_tick=10, expires_at_tick=70)
    assert "Z1" in bb.zone_claims
    assert bb.zone_claims["Z1"].drone_id == "ALPHA-1"
    assert bb.zone_claims["Z1"].expires_at_tick == 70


def test_scrub_removes_expired_claims():
    bb = make_blackboard(tick=100)
    bb.zone_claims["Z0"] = ZoneClaim(drone_id="ALPHA-1", committed_at_tick=10, expires_at_tick=69)
    bb.zone_claims["Z1"] = ZoneClaim(drone_id="ALPHA-2", committed_at_tick=50, expires_at_tick=110)

    # Simulate orchestrator scrub at tick 100
    expired = [z for z, c in list(bb.zone_claims.items()) if c.expires_at_tick <= bb.tick]
    for z in expired:
        del bb.zone_claims[z]

    assert "Z0" not in bb.zone_claims
    assert "Z1" in bb.zone_claims


def test_scrub_keeps_active_claims():
    bb = make_blackboard(tick=50)
    bb.zone_claims["Z2"] = ZoneClaim(drone_id="ALPHA-3", committed_at_tick=40, expires_at_tick=100)

    expired = [z for z, c in list(bb.zone_claims.items()) if c.expires_at_tick <= bb.tick]
    for z in expired:
        del bb.zone_claims[z]

    assert "Z2" in bb.zone_claims


def test_priority_map_readable_without_lock():
    bb = make_blackboard(tick=5)
    bb.priority_map = {"Z0": 8.5, "Z1": 3.2, "Z2": 6.0}

    # Pilots read priority_map without acquiring the lock
    assert bb.priority_map["Z0"] == 8.5
    assert bb.priority_map["Z1"] == 3.2
    assert bb.priority_map["Z2"] == 6.0


def test_zone_claim_expiry_calculation():
    bb = make_blackboard(tick=20)
    claim = ZoneClaim(drone_id="ALPHA-4", committed_at_tick=20, expires_at_tick=80)
    assert claim.expires_at_tick - claim.committed_at_tick == 60  # 60 tick lifetime
