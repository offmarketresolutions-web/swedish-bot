"""Category C -- info-gather-only / out-of-scope brand (test plan §Category C, C1-C5).
Non-serviced brand/equipment -> UNSUPPORTED_INTAKE -> gather context -> refer.
escalation_reason == "unsupported". ServiceRequest created. No specialist "solve".
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from chat import orchestrator as orch
from crm.models import ServiceRequest, Session
from tests.support.convo import DIY_FORBIDDEN, finish_escalation, run_convo

pytestmark = pytest.mark.django_db


# C1 -- unsupported brand: NIBE
def test_c1_unsupported_brand_nibe(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "I'll get a Nordland technician to help with your NIBE unit.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "error 163 on the display",
        "other",
        # no Machine row for NIBE -> ROUTING sends it through _unsupported_step, which
        # always transitions straight to ESCALATE in the same turn (no manual = no solve).
        ("NIBE F1226", {
            "state": "ESCALATE",
            "decision": "escalate",
            "prohibited": ["error 163 means", "163 is caused by"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "unsupported"
    finish_escalation(conv, name="Gunilla", phone="070-100 20 30")
    sess = Session.objects.get(conversation=conv)
    assert sess.machine is None
    sr = ServiceRequest.objects.get(session=sess)
    assert sr.escalation_reason == "unsupported"


# C2 -- unsupported brand: Thermia
def test_c2_unsupported_brand_thermia(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "We don't have a Thermia manual loaded, but a Nordland technician can still help.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "making a grinding noise",
        "other",
        ("Thermia Diplomat", {"state": "ESCALATE", "decision": "escalate"}),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "unsupported"
    finish_escalation(conv, name="Roland", phone="070-101 20 30")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# C3 -- out-of-scope: commercial/industrial system
def test_c3_commercial_plant_out_of_scope(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "high",
        "answer_to_customer": "A 200kW commercial plant is beyond residential scope -- I'll route this to a technician.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "we run a 200 kW commercial heat pump plant in an apartment block, one compressor is faulting",
        "other",
        ("commercial plant, no single model plate", {"state": "ESCALATE", "decision": "escalate"}),
    ], all_prohibited=DIY_FORBIDDEN)
    finish_escalation(conv, name="Fastighet AB", phone="070-102 20 30")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# C4 -- machine too old / no manual (worn nameplate, model forced "unknown")
def test_c4_legacy_ivt_model_unknown_forces_escalation(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "very old heat pump from the 90s, model plate is worn")
    orch.process_turn(conv, "IVT")
    # Two off-target model answers force the slot to "unknown" (plan §C4).
    mock_gemini.responses["extractor"] = {"on_target": False, "value": ""}
    res = orch.process_turn(conv, "can't read it, it's too worn")
    assert res["state"] == "INTAKE"  # first re-ask
    res = orch.process_turn(conv, "still can't make it out")
    conv.refresh_from_db()
    assert conv.case_state["slots"]["model"] == "unknown"
    # weak/no identification on a brand-only query (model excluded once "unknown") -> either
    # UNSUPPORTED (no machine matched) or a weak SPECIALIST match that the confidence gate
    # (mocked specialist default: confidence 0.0) still force-escalates. Either way: ESCALATE,
    # never a fabricated fix for an unidentified legacy unit.
    assert res["state"] == "ESCALATE"
    assert res.get("decision") == "escalate"
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] in ("unsupported", "low_confidence", "decision")
    finish_escalation(conv, name="Bengt", phone="070-103 20 30")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# C5 -- unclear brand -> photo request -> identification -> referral (unsupported)
def test_c5_photo_identifies_unsupported_daikin(seeded, mock_gemini):
    mock_gemini.responses["vision"] = {"manufacturer": "Daikin", "model": "EDLA08",
                                       "serial": "", "error_code": ""}
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "That's a Daikin EDLA08 -- we don't have a manual for that brand, but a technician can help.",
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "some kind of heat pump outside is leaking a bit of water, not sure the brand")
    photo = SimpleUploadedFile("plate.jpg", b"\xff\xd8\xff\xe0fakejpeg", content_type="image/jpeg")
    res = orch.process_turn(conv, "", image=photo)
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "Daikin"
    assert conv.case_state["slots"]["model"] == "EDLA08"
    assert conv.case_state["slots"]["nameplate_photo"] is True
    # drive to routing/unsupported (brand+model now known from OCR); category+problem
    # are already filled, so is_routable() should be true and the very next turn routes.
    for _ in range(3):
        if conv.case_state["state"] in ("ESCALATE", "RESOLVED"):
            break
        orch.process_turn(conv, "")
        conv.refresh_from_db()
    assert conv.case_state["state"] == "ESCALATE"
    assert conv.case_state["escalation_reason"] == "unsupported"
    finish_escalation(conv, name="Hanna", phone="070-104 20 30")
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "Daikin"
    from crm.models import CustomerFile
    assert CustomerFile.objects.filter(customer=sess.customer).exists()
