"""Per-category general specialists (feature 1): the single `intelligent_specialist`
role is split into three family-tailored agents — heat_pump_specialist,
water_pump_specialist, water_filtration_specialist — selected by the case's category
family BEFORE the intelligent_specialist fallback. Machine-confirmed manual mode is
untouched.
"""
import pytest
from django.core.management import call_command

from chat import orchestrator as orch
from chat.casestate import new_case_state
from chat.prompts import render
from crm.models import Session
from tests.support.convo import DIY_FORBIDDEN, finish_escalation, run_convo

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def _cs(**slots):
    cs = new_case_state()
    cs["slots"].update(slots)
    return cs


# ── role selection ─────────────────────────────────────────────────────
def test_general_role_selection_per_family(seeded):
    assert orch._general_role(_cs(category="heat_pump")) == "heat_pump_specialist"
    assert orch._general_role(_cs(category="water_pump_well")) == "water_pump_specialist"
    assert orch._general_role(_cs(category="water_filtration")) == "water_filtration_specialist"


def test_general_role_leaf_rolls_up_to_family(seeded):
    # a leaf sub-type (air_to_air / water_to_water / exhaust_air) rolls up to heat_pump
    assert orch._general_role(_cs(category="air_to_air")) == "heat_pump_specialist"
    assert orch._general_role(_cs(category="water_to_water")) == "heat_pump_specialist"
    # via subtype when the coarse category is the family
    assert orch._general_role(_cs(category="heat_pump", subtype="exhaust_air")) == "heat_pump_specialist"


def test_general_role_unknown_falls_back_to_intelligent_specialist(seeded):
    assert orch._general_role(_cs(category="unknown")) == "intelligent_specialist"
    assert orch._general_role(_cs(category=None)) == "intelligent_specialist"
    assert orch._general_role(_cs(category="something_unseeded")) == "intelligent_specialist"


# ── prompt rendering ───────────────────────────────────────────────────
@pytest.mark.parametrize("role", ["heat_pump_specialist", "water_pump_specialist",
                                  "water_filtration_specialist"])
def test_general_prompt_renders_with_placeholders(seeded, role):
    out = render(role, locale="en", brand="NIBE", model="S1255", category="heat_pump",
                 general_knowledge="GK-BLOCK", problem="no heat", error_code="E5",
                 forced_wrapup="false", previous_checks="PREV-CHECKS", onset="sudden")
    # placeholders filled, no leftover braces
    assert "GK-BLOCK" in out and "PREV-CHECKS" in out
    assert "{general_knowledge}" not in out and "{previous_checks}" not in out and "{onset}" not in out
    assert "NIBE" in out


# ── behavioral: correct role actually runs, safely ─────────────────────
def test_water_scenario_runs_under_water_pump_specialist(seeded, mock_gemini):
    """A serviced water-pump case with no catalog machine routes to water_pump_specialist
    (asserted via the mock's role classification), escalates safely, captures the brand."""
    mock_gemini.responses["water_pump_specialist"] = {
        "decision": "escalate", "confidence": 0.4, "in_docs": False,
        "answer_to_customer": "We don't have a manual for your Scandia pump loaded, "
                              "but I can get a Nordland technician out to look at the pressure.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "water_pump_well",
        "no",  # postcode declined early
        "no water pressure at all from our Scandia Pumps well pump",
        "Scandia Pumps",
        ("Scandia SP 200", {"state": "ESCALATE", "decision": "escalate",
                            "prohibited": ["adjust the pressure switch", "step 1:"]}),
    ], all_prohibited=DIY_FORBIDDEN)
    # the water_pump_specialist role (not intelligent_specialist) actually served the turn
    roles = [c["role"] for c in mock_gemini.calls]
    assert "water_pump_specialist" in roles
    assert "intelligent_specialist" not in roles
    finish_escalation(conv, name="Per Lindqvist", phone="070-703 10 20")
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "Scandia Pumps"
    assert sess.machine is None  # no-auto-bind


def test_heat_pump_nibe_runs_under_heat_pump_specialist(seeded, mock_gemini):
    mock_gemini.responses["heat_pump_specialist"] = {
        "decision": "escalate", "confidence": 0.4, "in_docs": False,
        "answer_to_customer": "We don't have a NIBE manual loaded, but a Nordland technician "
                              "can take a look at the compressor cutting out.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",
        "compressor keeps cutting out on my heat pump",
        "NIBE",
        ("S1255", {"state": "ESCALATE", "decision": "escalate"}),
    ], all_prohibited=DIY_FORBIDDEN)
    roles = [c["role"] for c in mock_gemini.calls]
    assert "heat_pump_specialist" in roles
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "NIBE"


def test_manual_mode_unchanged_uses_specialist(seeded, mock_gemini):
    """A confirmed catalog machine still runs the top-tier `specialist` role, never a
    general one."""
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "That needs a technician to look at.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump", "no", "keeps alarming", "IVT",
        ("IVT 490", {"state": "ESCALATE"}),
    ], all_prohibited=DIY_FORBIDDEN)
    roles = [c["role"] for c in mock_gemini.calls]
    assert "specialist" in roles
    for gr in ("heat_pump_specialist", "water_pump_specialist",
               "water_filtration_specialist", "intelligent_specialist"):
        assert gr not in roles
