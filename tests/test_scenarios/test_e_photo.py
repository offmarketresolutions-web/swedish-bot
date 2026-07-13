"""Category E -- photo flows (test plan §Category E, E1-E3; E4 is voice/WhatsApp,
not implementable against the existing web-chat pipeline -- see the module-level
skip below). Exercises `_run_vision` -> slot fill -> routing, CustomerFile rows.
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from chat import orchestrator as orch
from crm.models import ServiceRequest, Session
from tests.support.convo import DIY_FORBIDDEN, run_convo

pytestmark = pytest.mark.django_db


def _photo():
    return SimpleUploadedFile("plate.jpg", b"\xff\xd8\xff\xe0fakejpeg", content_type="image/jpeg")


# E1 -- photo-first nameplate identification
def test_e1_photo_first_nameplate_identification(seeded, mock_gemini):
    mock_gemini.responses["vision"] = {"manufacturer": "IVT", "model": "Geo 412C",
                                       "serial": "SN123", "error_code": ""}
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "The particle filter light means it's time to clean the filter -- rinse it under running water and refit it.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    # a photo attached alongside the problem description: vision fills brand+model from the
    # nameplate OCR (no separate brand/model turns needed) while the free text fills 'problem'
    # -- both required slots land in this one turn, so it routes straight to the specialist.
    final = orch.process_turn(conv, "the particle filter light is on, what model is this?", image=_photo())
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "IVT"
    assert conv.case_state["slots"]["model"] == "Geo 412C"
    assert conv.case_state["slots"]["nameplate_photo"] is True
    assert any(e.get("type") == "tool_result" and e.get("name") == "vision_extract"
               for e in final.get("events", []))
    assert final["decision"] == "solve"
    assert "filter" in final["message"].lower()
    sess = Session.objects.get(conversation=conv)
    assert ServiceRequest.objects.count() == 0
    assert sess.decision == "solve"


# E2 -- blurry / wrong photo -> graceful re-ask, no wrong-model guess
def test_e2_blurry_photo_reask_then_typed_model(seeded, mock_gemini):
    mock_gemini.responses["vision"] = {}  # unreadable
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no heat")
    res = orch.process_turn(conv, "", image=_photo())
    conv.refresh_from_db()
    assert not conv.case_state["slots"]["nameplate_photo"]
    assert not conv.case_state["slots"]["model"]
    assert res["message"]  # no crash, some coherent re-ask/continuation

    mock_gemini.responses["vision"] = {}  # second bad photo, still nothing usable
    res2 = orch.process_turn(conv, "", image=_photo())
    conv.refresh_from_db()
    assert not conv.case_state["slots"]["model"]

    # customer types the model instead
    res3 = orch.process_turn(conv, "Bosch")
    res4 = orch.process_turn(conv, "Compress 7000i")
    conv.refresh_from_db()
    assert conv.case_state["slots"]["model"] == "Compress 7000i"
    assert conv.case_state["slots"]["brand"] == "Bosch"


# E3 -- photo of the error-code display
def test_e3_photo_of_error_code_display(seeded, mock_gemini):
    mock_gemini.responses["vision"] = {"manufacturer": "IVT", "model": "Geo 412C", "error_code": "H01 5252"}
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "H01 5252 means the particle filter is dirty -- clean/rinse it and clear the alarm.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    res = orch.process_turn(conv, "my heat pump is showing an alarm, here's a photo of the screen",
                             image=_photo())
    conv.refresh_from_db()
    assert conv.case_state["slots"]["error_code"] == "H01 5252"
    assert conv.case_state["slots"]["brand"] == "IVT"
    # category+problem(the message)+brand+model already known -> should already have routed
    if conv.case_state["state"] not in ("SPECIALIST",):
        res = orch.process_turn(conv, "")
        conv.refresh_from_db()
    assert conv.case_state["state"] == "SPECIALIST"
    assert conv.case_state["decision"] == "solve"
    from crm.models import CustomerFile
    assert ServiceRequest.objects.count() == 0


@pytest.mark.skip(reason="E4: WhatsApp-photo-during-a-phone-call is a planned voice/telephony "
                          "channel (audit Constraints 1/2/4/5) -- no Vapi/WhatsApp integration "
                          "exists against chat/orchestrator.py yet, so there is nothing to drive "
                          "this scenario against. See docs/plans/2026-07-12-test-plan-conversations.md "
                          "§E4 and §3.3 for the spec to implement once the channel lands.")
def test_e4_whatsapp_photo_during_phone_call_confirmation_loop():
    pass
