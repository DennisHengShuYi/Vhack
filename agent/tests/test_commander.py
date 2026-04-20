"""Tests for Commander._parse_brief parsing logic."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from agent.agent import Commander, Blackboard, ZoneClaim
import asyncio


def make_commander() -> Commander:
    blackboard = Blackboard(
        priority_map={},
        posture="SPREAD",
        urgent_redirect=None,
        updated_at_tick=0,
        tick=0,
        zone_claims={},
        lock=asyncio.Lock(),
    )
    return Commander(
        blackboard=blackboard,
        memory=MagicMock(),
        llm=None,
        http_session=None,
        backend_url="http://127.0.0.1:8000",
    )


def test_parse_brief_extracts_priority_map():
    cmd = make_commander()
    text = "POSTURE: SPREAD\nPRIORITY: Z0=8.0, Z1=3.5, Z2=6.2, Z3=1.0\nBRIEF: Focus on city zones."
    priority_map, posture, redirect = cmd._parse_brief(text)
    assert priority_map == {"Z0": 8.0, "Z1": 3.5, "Z2": 6.2, "Z3": 1.0}


def test_parse_brief_extracts_posture():
    cmd = make_commander()
    text = "POSTURE: LEAD_CHASE\nPRIORITY: Z0=5.0\nBRIEF: Chase the lead."
    _, posture, _ = cmd._parse_brief(text)
    assert posture == "LEAD_CHASE"


def test_parse_brief_defaults_posture_to_spread():
    cmd = make_commander()
    text = "PRIORITY: Z0=5.0\nBRIEF: No posture line here."
    _, posture, _ = cmd._parse_brief(text)
    assert posture == "SPREAD"


def test_parse_brief_extracts_redirect():
    cmd = make_commander()
    text = "POSTURE: CONVERGE\nPRIORITY: Z0=9.0\nREDIRECT: (3, 7): survivor signal detected\nBRIEF: Redirect drone."
    _, _, redirect = cmd._parse_brief(text)
    assert redirect == (3, 7, "survivor signal detected")


def test_parse_brief_no_redirect_when_absent():
    cmd = make_commander()
    text = "POSTURE: SPREAD\nPRIORITY: Z0=5.0\nBRIEF: No redirect."
    _, _, redirect = cmd._parse_brief(text)
    assert redirect is None


def test_parse_brief_city_zones_higher_priority():
    cmd = make_commander()
    text = "POSTURE: CONVERGE\nPRIORITY: Z0=9.5, Z1=2.0, Z2=7.3, Z3=1.5\nBRIEF: City zones first."
    priority_map, _, _ = cmd._parse_brief(text)
    # City zones (Z0, Z2) should have higher weights than flat zones (Z1, Z3)
    assert priority_map["Z0"] > priority_map["Z1"]
    assert priority_map["Z2"] > priority_map["Z3"]


def test_parse_brief_rtb_cautious_posture():
    cmd = make_commander()
    text = "POSTURE: RTB_CAUTIOUS\nPRIORITY: Z0=3.0\nBRIEF: Low battery fleet."
    _, posture, _ = cmd._parse_brief(text)
    assert posture == "RTB_CAUTIOUS"
