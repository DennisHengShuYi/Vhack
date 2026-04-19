"""Tests for Pilot._commit_zone and Pilot._parse_llm_decision."""
import asyncio
from unittest.mock import MagicMock
from agent.agent import Pilot, Blackboard, ZoneClaim


def make_pilot(drone_id: str = "ALPHA-1", tick: int = 10) -> tuple:
    blackboard = Blackboard(
        priority_map={"Z0": 8.0, "Z1": 3.0},
        posture="SPREAD",
        urgent_redirect=None,
        updated_at_tick=tick,
        tick=tick,
        zone_claims={},
        lock=asyncio.Lock(),
    )
    pilot = Pilot(
        drone_id=drone_id,
        blackboard=blackboard,
        memory=MagicMock(),
        llm=None,
        mcp_session=None,
        http_session=None,
        backend_url="http://127.0.0.1:8000",
    )
    return pilot, blackboard


# ─── _commit_zone tests ────────────────────────────────────────────────────────

def test_commit_zone_primary_succeeds_when_free():
    pilot, bb = make_pilot()
    result = asyncio.run(pilot._commit_zone("Z0", "Z1"))
    assert result == "Z0"
    assert "Z0" in bb.zone_claims
    assert bb.zone_claims["Z0"].drone_id == "ALPHA-1"


def test_commit_zone_falls_back_to_backup():
    pilot, bb = make_pilot()
    bb.zone_claims["Z0"] = ZoneClaim(drone_id="ALPHA-2", committed_at_tick=5, expires_at_tick=65)
    result = asyncio.run(pilot._commit_zone("Z0", "Z1"))
    assert result == "Z1"
    assert "Z1" in bb.zone_claims


def test_commit_zone_returns_none_when_both_taken():
    pilot, bb = make_pilot()
    bb.zone_claims["Z0"] = ZoneClaim(drone_id="ALPHA-2", committed_at_tick=5, expires_at_tick=65)
    bb.zone_claims["Z1"] = ZoneClaim(drone_id="ALPHA-3", committed_at_tick=5, expires_at_tick=65)
    result = asyncio.run(pilot._commit_zone("Z0", "Z1"))
    assert result is None


def test_commit_zone_sets_correct_expiry():
    pilot, bb = make_pilot(tick=20)
    asyncio.run(pilot._commit_zone("Z2", None))
    assert bb.zone_claims["Z2"].expires_at_tick == 80  # tick 20 + 60


def test_commit_zone_no_backup_returns_none_when_primary_taken():
    pilot, bb = make_pilot()
    bb.zone_claims["Z0"] = ZoneClaim(drone_id="ALPHA-2", committed_at_tick=5, expires_at_tick=65)
    result = asyncio.run(pilot._commit_zone("Z0", None))
    assert result is None


# ─── _parse_llm_decision tests ────────────────────────────────────────────────

def test_parse_llm_decision_standard_arrow():
    pilot, _ = make_pilot()
    text = "DECISION → Z2: high city survivor density\nBACKUP → Z0: partial scan remaining"
    primary, backup = pilot._parse_llm_decision(text)
    assert primary == "Z2"
    assert backup == "Z0"


def test_parse_llm_decision_colon_separator():
    pilot, _ = make_pilot()
    text = "DECISION: Z1\nBACKUP: Z3"
    primary, backup = pilot._parse_llm_decision(text)
    assert primary == "Z1"
    assert backup == "Z3"


def test_parse_llm_decision_rtb():
    pilot, _ = make_pilot()
    text = "DECISION → RTB: battery critical"
    primary, backup = pilot._parse_llm_decision(text)
    assert primary == "RTB"
    assert backup is None


def test_parse_llm_decision_no_backup():
    pilot, _ = make_pilot()
    text = "DECISION → Z3: only option"
    primary, backup = pilot._parse_llm_decision(text)
    assert primary == "Z3"
    assert backup is None


def test_parse_llm_decision_case_insensitive():
    pilot, _ = make_pilot()
    text = "decision → z1: low battery area\nbackup → z2: fallback"
    primary, backup = pilot._parse_llm_decision(text)
    assert primary == "Z1"
    assert backup == "Z2"


def test_parse_llm_decision_malformed_returns_none():
    pilot, _ = make_pilot()
    text = "I think we should scan the northern area first."
    primary, backup = pilot._parse_llm_decision(text)
    assert primary is None
    assert backup is None
