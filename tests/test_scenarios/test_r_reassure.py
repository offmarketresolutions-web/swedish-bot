"""Feature 2 -- reassure-and-close. A documented reassurance ('normal, no visit
needed') should let the customer close out without a technician lead when they
confirm they're satisfied; a still-worried customer falls through to the normal
escalate flow; a safety-flagged draft is NEVER eligible for reassure-close.
"""
import pytest

from chat import orchestrator as orch
from crm.models import ServiceRequest
from tests.support.convo import finish_escalation, run_convo

pytestmark = pytest.mark.django_db


# R1 -- documented reassurance + customer confirms -> RESOLVED, no lead.
# The specialist mistakenly returns decision="escalate" (today's bug) but sets
# no_action_needed=true with in_docs/confidence over the gate -- the orchestrator
# must recognize this as an eligible solve, not an escalation.
def test_r1_reassure_close_condensation_normal(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "That's completely normal -- condensation on a cold pipe, not a leak. No visit needed."),
        "confidence": 0.85, "decision": "escalate", "in_docs": True,
        "no_action_needed": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early -- declined
        "there is condensation on the cold pipe, is that normal?",
        "IVT",
        ("Geo 412C", {"state": "SPECIALIST", "decision": "solve"}),
    ])
    final = orch.process_turn(conv, "yes that answers it, thanks")
    assert final["state"] == "RESOLVED" and final["decision"] == "solve"
    assert ServiceRequest.objects.count() == 0


# R2 -- customer still worried -> falls through to normal escalate flow, lead created.
def test_r2_still_worried_falls_through_to_escalate(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "That's completely normal -- condensation on a cold pipe, not a leak. No visit needed."),
        "confidence": 0.85, "decision": "escalate", "in_docs": True,
        "no_action_needed": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",
        "there is condensation on the cold pipe, is that normal?",
        "IVT",
        ("Geo 412C", {"state": "SPECIALIST", "decision": "solve"}),
    ])
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Understood, let's get a technician to double-check.",
        "confidence": 0.2, "decision": "escalate", "in_docs": False, "report": {},
    }
    res = orch.process_turn(conv, "no, I'm still worried about it")
    assert res["state"] == "ESCALATE"
    finish_escalation(conv, name="Worried Customer", phone="070-900 10 20")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# R3 -- a safety-flagged draft is never eligible for reassure-close, even if the
# model (incorrectly) sets no_action_needed=true.
def test_r3_safety_veto_beats_reassure_close(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Just rewire the terminal block yourself, totally normal.",
        "confidence": 0.9, "decision": "solve", "in_docs": True,
        "no_action_needed": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",
        "there is condensation on the cold pipe, is that normal?",
        "IVT",
        ("Geo 412C", {"state": "ESCALATE"}),
    ])
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"].startswith("forbidden term")
    assert conv.case_state["state"] == "ESCALATE"
