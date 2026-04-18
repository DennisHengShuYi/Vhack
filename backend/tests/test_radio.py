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
