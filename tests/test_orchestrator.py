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


def test_escalation_asks_for_problem_and_error_photo_before_contact(seeded, mock_gemini):
    """Unsupported brand → before collecting contact, the bot asks for a detailed
    problem description + a photo of any error code; only then does it ask for name."""
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "other")
    res = orch.process_turn(conv, "Aqua Invent X")          # unsupported → escalate
    assert res["decision"] == "escalate"
    low = res["message"].lower()
    assert "photo" in low and ("error" in low or "code" in low)   # asked for the error-code photo
    assert "name" not in low                                       # NOT contact yet
    nxt = orch.process_turn(conv, "it leaks and shows code F2")    # diagnostics reply
    assert "name" in nxt["message"].lower()                        # now collects contact


def test_history_and_files_carried_to_downstream_agents(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_specialist(conv)
    for role in ("router", "specialist"):
        calls = [c for c in mock_gemini.calls if c["role"] == role]
        assert calls, f"no {role} call recorded"
        blob = str(calls[-1]["contents"])
        assert "Conversation so far" in blob              # full transcript carried over
        assert "no_heat" in blob or "IVT" in blob         # actual prior messages present


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
    cs["specialist_turns"] = orch.REPLY_BUDGET  # exhaust the TROUBLESHOOTING budget
    conv.case_state = cs
    conv.save(update_fields=["case_state"])
    res = orch.process_turn(conv, "it's still not working")
    assert res["decision"] == "escalate"  # forced wrap-up despite high confidence


def test_intake_turns_do_not_consume_reply_budget(seeded, mock_gemini):
    """Regression: the customer's first real question after intake must still get a
    real answer — intake turns must NOT count toward the troubleshooting budget."""
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Check the filter.", "confidence": 0.95,
        "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    _drive_to_specialist(conv)                       # 4 intake turns + 1 specialist solve
    res = orch.process_turn(conv, "what does alarm E2 mean?")   # 2nd specialist turn
    assert res["decision"] == "solve"                # not force-escalated by intake turns
