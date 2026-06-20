"""Agent FSM integration tests (plan §6) — Gemini mocked, real Postgres + seeded KB."""
import pytest
from django.core.management import call_command

from chat import orchestrator as orch
from crm.models import Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def _drive_to_specialist(conv):
    """Run the intake turns for a supported IVT 490 heat-pump case."""
    orch.process_turn(conv, "heat_pump")   # category (chip)
    orch.process_turn(conv, "no_heat")     # problem (chip)
    orch.process_turn(conv, "IVT")         # brand (chip)
    return orch.process_turn(conv, "IVT 490")  # model (free text) → routes + specialist


def test_open_conversation_greets_with_category_chips(seeded, mock_gemini):
    conv, greet = orch.open_conversation()
    assert greet["state"] == "INTAKE"
    values = {c["value"] for c in greet["chips"]}
    assert {"heat_pump", "water_pump_well", "water_filtration"} <= values


def test_supported_case_solves_and_flushes_session(seeded, mock_gemini):
    mock_gemini.responses["router"] = {"severity": "normal", "problem_category": "no_heat", "supported": True}
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Note the alarm code on the display, then check the extract-air filter is clean.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "severity": "normal",
        "report": {"resolved": False, "troubleshooting_performed": ["explained alarm + filter check"]},
    }
    conv, _ = orch.open_conversation()
    res = _drive_to_specialist(conv)

    assert res["decision"] == "solve"
    assert "alarm code" in res["message"]
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "IVT" and sess.model == "IVT 490"
    assert sess.machine.model_name == "IVT 490"
    assert sess.confidence_score == 0.9
    assert sess.decision == "solve"
    assert sess.problem_category is not None and sess.problem_category.slug == "no_heat"
    assert sess.category is not None


def test_low_confidence_escalates(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "It might be the sensor, but I'm not certain.",
        "confidence": 0.5, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    res = _drive_to_specialist(conv)
    assert res["decision"] == "escalate"
    assert "Nordland" in res["message"]
    assert Session.objects.get(conversation=conv).status == "escalated"


def test_guardrail_vetoes_unsafe_answer(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "You should rewire the compressor and top up the refrigerant.",
        "confidence": 0.95, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    res = _drive_to_specialist(conv)
    assert res["decision"] == "escalate"
    assert "rewire" not in res["message"].lower()  # unsafe text never delivered
    assert "refrigerant" not in res["message"].lower()


def test_unsupported_brand_becomes_qualified_lead(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "other")              # unsupported brand
    res = orch.process_turn(conv, "Mitsubishi MSZ-2024")  # not in catalog
    assert res["decision"] == "escalate"
    sess = Session.objects.get(conversation=conv)
    assert sess.machine is None
    assert sess.status == "escalated"


def test_reply_budget_forces_escalation(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Try checking the filter.", "confidence": 0.95,
        "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    _drive_to_specialist(conv)  # one solve
    conv.refresh_from_db()
    cs = conv.case_state
    cs["turns"] = orch.REPLY_BUDGET  # exhaust the budget
    conv.case_state = cs
    conv.save(update_fields=["case_state"])
    res = orch.process_turn(conv, "it's still not working")
    assert res["decision"] == "escalate"  # forced wrap-up despite high confidence
