"""Category A -- autonomously resolvable (test plan §Category A, scenarios A1-A8).
Bot solves; decision=='solve'; Session.resolved True; no ServiceRequest.

NOTE on terminal state: after a specialist "solve" the bot now appends a
"Did that fix it?" confirmation (GAP 1/6 fix in
`chat/orchestrator.py::_specialist_step`). The solve turn itself stays in
STATE_SPECIALIST with decision=='solve' (now carrying yes/no chips); the
customer's *next* reply drives the terminal state -- a "yes" transitions to
STATE_RESOLVED with Session.resolved=True and NO ServiceRequest (test plan
§Category A / SRS R1), while a "no"/"still broken" reply routes back into
troubleshooting. These tests assert that real behavior plus the Session/DB
facts the plan cares about (resolved flag, no lead).
"""
import pytest

from chat import orchestrator as orch
from crm.models import ServiceRequest, Session
from tests.support.convo import DIY_FORBIDDEN, run_convo

pytestmark = pytest.mark.django_db


# A1 -- IVT Geo dirty particle filter, alarm H01 5252
def test_a1_ivt_geo_filter_h01_5252(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "Your Geo 412C is showing H01 5252, which means the particle filter is likely "
            "dirty and restricting flow. You can clean it yourself without draining the "
            "system: close the shut-off valve, unscrew the filter cap by hand, pull out the "
            "strainer and rinse it under running water, then refit it and clear the alarm "
            "on the controller."),
        "confidence": 0.92, "decision": "solve", "in_docs": True,
        "report": {"resolved": True},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "showing an alarm H01 5252",
        "IVT",
        ("Geo 412C", {
            "state": "SPECIALIST", "decision": "solve",
            "required": ["filter", ("clean", "rinse"), ("alarm", "H01 5252")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    # customer confirms the fix worked -> RESOLVED terminal, no lead (SRS R1)
    final = orch.process_turn(conv, "Great, I cleaned it and the alarm cleared.")
    assert final["state"] == "RESOLVED" and final["decision"] == "solve"
    sess = Session.objects.get(conversation=conv)
    assert sess.decision == "solve"
    assert sess.resolved is True
    assert sess.error_code == "H01 5252"
    assert sess.manufacturer == "IVT"
    assert ServiceRequest.objects.count() == 0


# A2 -- Ventilation unit (Vent 402) filter change, noisy/weak airflow
def test_a2_vent_402_filter_change(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "Weak, noisy airflow is usually a dirty particle filter. Clean or replace the "
            "air filter first, and clean the exhaust vents while you're at it."),
        "confidence": 0.88, "decision": "solve", "in_docs": True, "report": {"resolved": True},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "airflow is weak and it's gotten noisy",
        "IVT",
        ("Vent 402", {
            "state": "SPECIALIST", "decision": "solve",
            "required": ["filter", ("clean", "replace", "change")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert Session.objects.get(conversation=conv).resolved is True
    assert ServiceRequest.objects.count() == 0


# A3 -- Thermostat misconfiguration (perceived fault, not a fault)
def test_a3_thermostat_valves_perceived_fault(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "No error code and the pump is running fine -- this looks like the thermostat "
            "valves on your radiators are set too low. Open the thermostat valves and check "
            "the heating setpoint isn't turned down too far."),
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "house won't get warm enough even though the heat pump seems to be running fine",
        "IVT",
        ("Geo 412C", {
            "state": "SPECIALIST", "decision": "solve",
            "required": [("thermostat", "valve"), ("open", "raise", "increase")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert ServiceRequest.objects.count() == 0
    assert Session.objects.get(conversation=conv).decision == "solve"


# A4 -- Simple restart / error-clear (condensation alarm clears on acknowledge)
def test_a4_acknowledge_clear_condensation_alarm(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "That warning is condensation on the flow pipe -- wait for it to dry, then "
            "acknowledge the alarm on the controller by pressing the menu dial. If it "
            "comes back, we'll get a technician to look at it."),
        "confidence": 0.8, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "there's a warning on my controller, everything else works, message mentions moisture on the pipes",
        "IVT",
        ("Geo 412C", {
            "state": "SPECIALIST", "decision": "solve",
            "required": [("acknowledge", "clear", "press"), ("wait", "dry")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert ServiceRequest.objects.count() == 0


# A5 -- Breaker tripped / no display
def test_a5_breaker_reset(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "A completely dead display is usually the breaker or residual-current device "
            "for the unit. Check your fuse/breaker/RCD in the consumer unit and switch it "
            "back on if it's tripped. If it trips again, that needs a technician."),
        "confidence": 0.78, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "heat pump display is completely dead",
        "IVT",
        ("Geo 412C", {
            "state": "SPECIALIST", "decision": "solve",
            "required": [("breaker", "fuse", "RCD"), ("reset", "switch"), "technician"],
            "prohibited": ["terminal block", "electrical panel"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert ServiceRequest.objects.count() == 0


# A6 -- Condensation confusion (normal behavior, no action needed)
def test_a6_condensation_is_normal(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "Those water drops are just normal condensation on a cold pipe, not a leak -- no "
            "action needed. It would only need a technician if you saw water pooling on the "
            "floor or an active alarm."),
        "confidence": 0.82, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "there is water drops on the pipe of my heat pump. is it broken?",
        "IVT",
        ("Geo 412C", {
            "state": "SPECIALIST", "decision": "solve",
            "required": [("normal", "expected"), ("condensation", "not a leak")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert ServiceRequest.objects.count() == 0


# A7 -- Hot-water temperature adjustment
def test_a7_hot_water_eco_to_comfort(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "Not enough hot water is usually the hot-water mode -- switch it from ECO to "
            "Normal/Comfort in the menu, or use the temporary extra hot water option."),
        "confidence": 0.8, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "not enough hot water lately",
        "IVT",
        ("Geo 412C", {
            "state": "SPECIALIST", "decision": "solve",
            "required": [("hot water",), ("ECO", "comfort", "normal", "mode", "setting")],
            "prohibited": ["legionella"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert ServiceRequest.objects.count() == 0


# A8 -- Noisy ventilation = filter, photo-free, robustness against a rambling message
def test_a8_noisy_vent_filter_rambling_intake(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Clean or replace the air filter first -- that's the usual cause of a rattly hum.",
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        # a run-on, rambling problem description -- the free-text 'problem' slot must
        # accept it verbatim (>=2 words shortcut, no LLM extraction needed) rather than
        # getting derailed or bouncing the customer back with a re-ask.
        ("so my ventilation thing has been making this rattly humming noise for like a week "
         "and honestly i thought it would go away but it hasn't and now it's kind of loud "
         "and i don't know if that's bad?", {"state": "INTAKE"}),
        "IVT",
        ("Vent 402", {
            "state": "SPECIALIST", "decision": "solve",
            "required": ["filter", ("clean", "replace")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert ServiceRequest.objects.count() == 0
