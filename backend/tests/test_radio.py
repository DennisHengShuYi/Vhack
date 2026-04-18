import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from simulation import SimulationState, Lead


def test_lead_dataclass_fields():
    lead = Lead(
        id="L001", tick=5, lang="BM",
        raw="ada orang di masjid", english="someone at mosque",
        x=4, y=7, urgency="CRITICAL", status="GROUNDED"
    )
    assert lead.id == "L001"
    assert lead.urgency == "CRITICAL"
    assert lead.status == "GROUNDED"


def test_sim_has_leads_list():
    import random; random.seed(42)
    sim = SimulationState()
    assert hasattr(sim, 'leads')
    assert isinstance(sim.leads, list)
    assert len(sim.leads) == 0


def test_lead_ungrounded_construction():
    lead = Lead(
        id="L002", tick=1, lang="EN",
        raw="someone near river", english="someone near river",
        x=None, y=None, urgency="URGENT", status="PENDING_GROUND"
    )
    assert lead.x is None
    assert lead.y is None
    assert lead.status == "PENDING_GROUND"


def test_sim_lead_counter_starts_at_zero():
    import random; random.seed(42)
    sim = SimulationState()
    assert sim._lead_counter == 0


from landmarks import LandmarkRegistry


def test_registry_loads():
    reg = LandmarkRegistry()
    assert len(reg.landmarks) >= 5


def test_lookup_by_exact_name():
    reg = LandmarkRegistry()
    result = reg.lookup("mosque")
    assert result is not None
    x, y = result
    assert 0 <= x <= 19
    assert 0 <= y <= 14


def test_lookup_unknown_returns_none():
    reg = LandmarkRegistry()
    assert reg.lookup("xyzzy_nowhere") is None
