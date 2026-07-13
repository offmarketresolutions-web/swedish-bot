"""Category B -- troubleshoot-then-escalate (test plan §Category B, B1-B6).
Bot attempts a low-stakes fix, it doesn't resolve, bot stops and hands to a
human. Ends ESCALATE -> RESOLVED (after approval); ServiceRequest created;
escalation_reason per case.
"""
import pytest

from chat import orchestrator as orch
from crm.models import ServiceRequest, Session
from tests.support.convo import DIY_FORBIDDEN, finish_escalation, run_convo

pytestmark = pytest.mark.django_db


# B1 -- restart/clean doesn't clear the error code -> escalate
def test_b1_error_recurs_after_safe_fix_escalates(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Clean the outdoor unit (the fan and evaporator), then clear the alarm and see if it returns.",
        "confidence": 0.8, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "alarm H01 5292 keeps coming",
        "IVT",
        ("Geo 412C", {"state": "SPECIALIST", "decision": "solve", "required": ["outdoor unit"]}),
    ], all_prohibited=DIY_FORBIDDEN)

    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Since it's returned after cleaning, this needs a technician.",
    }
    res = orch.process_turn(conv, "I cleaned the outdoor unit but H01 5292 came straight back")
    assert res["state"] == "ESCALATE"
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] in ("low_confidence", "decision")

    finish_escalation(conv, name="Karin Berg", phone="070-111 22 33")
    sess = Session.objects.get(conversation=conv)
    assert sess.status == "escalated"
    assert sess.model == "Geo 412C"
    assert sess.error_code == "H01 5292"
    sr = ServiceRequest.objects.get(session=sess)
    assert sr.escalation_reason in ("low_confidence", "decision")
    assert sr.payload_json["equipment"]["model"] == "Geo 412C"
    assert sr.payload_json["equipment"]["error_code"] == "H01 5292"


# B2 -- intermittent fault (can't reproduce) needs a human
def test_b2_intermittent_fault_escalates(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.55, "in_docs": True,
        "answer_to_customer": "Intermittent low-pressure pump-stops like this need a technician to diagnose properly.",
    }
    conv, _ = orch.open_conversation()
    res_list = run_convo(conv, [
        "heat_pump",
        "my Bosch heat pump randomly stops and starts, no steady error",
        "Bosch",
        ("Greenline HE", {"state": "ESCALATE"}),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "low_confidence"

    finish_escalation(conv, name="Tomas", phone="070-222 33 44")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# B3 -- low system pressure top-up is out of scope; doubles as a guardrail test
def test_b3_pressure_topup_out_of_scope_and_guardrail_veto(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Topping up the sealed heating system's pressure is a technician job -- it risks the expansion vessel and relief valve, so I won't walk you through it.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "heating pressure gauge is low on my heat pump, how do I top it up?",
        "IVT",
        ("Geo 412C", {
            "state": "ESCALATE",
            "prohibited": ["re-pressuriz", "repressuriz"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    finish_escalation(conv, name="Ingrid", phone="070-333 44 55")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()

    # Guardrail sub-assert: a specialist draft that DID try to give the forbidden
    # procedure must be vetoed by the code-level backstop before ever reaching the
    # customer (guardrails.is_unsafe is the hard gate; separate from the FSM above).
    from chat import guardrails
    unsafe, reason = guardrails.is_unsafe("Just re-pressurize the system to 1.5 bar yourself.")
    assert unsafe
    assert reason.startswith("forbidden term")


# B4 -- pump short-cycling (well pump) -- out of low-stakes scope
def test_b4_pump_short_cycling_escalates(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Rapid on/off cycling like that points at the pressure tank or switch -- that's technician work, I won't have you adjust the pressure switch yourself.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "water_pump_well",
        "well pump keeps clicking on and off every few seconds",
        "Grundfos",
        ("Grundfos SQ", {
            "state": "ESCALATE",
            "prohibited": ["adjust the pressure switch"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    finish_escalation(conv, name="Mats", phone="070-444 55 66")
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "Grundfos"
    assert ServiceRequest.objects.filter(session=sess).exists()


# B5 -- reply budget exhausted (too many troubleshooting turns) -> forced escalate
def test_b5_reply_budget_forces_escalation(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Try checking the filter again and let me know.",
        "confidence": 0.72, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, ["heat_pump", "still not working after a few tries", "IVT"],
               all_prohibited=DIY_FORBIDDEN)
    res = orch.process_turn(conv, "Geo 412C")
    assert res["decision"] == "solve"
    for _ in range(orch.REPLY_BUDGET):
        res = orch.process_turn(conv, "still not working, what else?")
    assert res["decision"] == "escalate"
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "budget"
    assert conv.case_state["specialist_turns"] >= orch.REPLY_BUDGET
    finish_escalation(conv, name="Fredrik", phone="070-555 66 77")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# B6 -- Vent 402 low-pressure/defrost alarm tied to too-low room temp (borderline)
def test_b6_vent402_defrost_alarm_room_temp_then_escalate(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "For that airflow rate, keep the minimum room temperature at 18C or above to avoid defrost/low-pressure alarms -- try raising it from 16 to 18.",
        "confidence": 0.75, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "my ventilation heat pump keeps alarming about defrost",
        "IVT",
        ("Vent 402", {"state": "SPECIALIST", "decision": "solve", "required": [("18", "room temp")]}),
    ], all_prohibited=DIY_FORBIDDEN)

    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Since it alarmed again after raising the room temperature, this needs a technician.",
    }
    res = orch.process_turn(conv, "raised it to 18 but it alarmed again today")
    assert res["state"] == "ESCALATE"
    finish_escalation(conv, name="Ulla", phone="070-666 77 88")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()
