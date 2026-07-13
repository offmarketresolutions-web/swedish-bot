"""Category K -- ventilation (Vent 402) real-content deep dive + water-pump/
water-filtration brand tiering (K1-K14, docs/plans/2026-07-12-test-plan-conversations.md
task addendum). Not in the original catalog (Part 2) -- these extend Category A/B/C
coverage with: (a) more Vent 402 scenarios grounded in `vent_content.txt` /
`vent_maintenance_full.txt` (filter alarm, the >=18C minimum-room-temperature rule,
post-summer maintenance smell, whistling-then-escalate), and (b) the water-pump/
water-filtration brand tier split -- Grundfos/Debe have seeded `Machine` rows (so
they route through SPECIALIST like any documented brand) while Scandia Pumps/Aqua
Expert/Aqua Invent have NO `Machine` row (`kb/management/commands/seed_kb.py`
MACHINES only lists Grundfos SQ + Debe DPM) so they must fall through to
UNSUPPORTED_INTAKE -- info-gather + referral, never an invented remedy.

Uses the `seeded` fixture from tests/test_scenarios/conftest.py (adds IVT Vent 402 /
Geo 412C / Bosch Greenline HE on top of seed_kb's base catalog) and the shared
tests/support/convo.py driver -- same idioms as test_a_resolve.py / test_b_escalate.py
/ test_c_unsupported.py. Does not touch production code or any other test file.
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from chat import orchestrator as orch
from crm.models import ServiceRequest, Session
from tests.support.convo import DIY_FORBIDDEN, finish_escalation, run_convo

pytestmark = pytest.mark.django_db


def _photo():
    return SimpleUploadedFile("plate.jpg", b"\xff\xd8\xff\xe0fakejpeg", content_type="image/jpeg")


# K1 -- Vent 402 filter alarm -> resolve via filter-change guidance
# Real content: vent_content.txt 7.2 Partikelfilter / 7.3 Rengoring av luftfiltret --
# "Paminnelsen 'Rengor filter' visas varannan manad" (filter reminder every 2 months);
# clean the strainer under running water, no need to drain the system.
def test_k1_vent402_filter_alarm_resolves(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "That's the particle filter reminder -- it comes up every couple of months. "
            "Pull out the strainer and clean it under running water, then refit it and "
            "clear the alarm on the display. You don't need to open anything else up."),
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {"resolved": True},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "filter alarm keeps showing on my ventilation unit",
        "IVT",
        ("Vent 402", {
            "state": "SPECIALIST", "decision": "solve",
            "required": ["filter", ("clean", "rinse"), "alarm"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    sess = Session.objects.get(conversation=conv)
    assert sess.decision == "solve"
    assert ServiceRequest.objects.count() == 0


# K2 -- Vent 402 blowing cold, house at 17C -- the >=18C room-temp rule
# Real content: vent_maintenance_full.txt "Minimal rumstemperatur" -- "Om luftflodet
# ar installt pa 70m3/h, ska rumstemperaturen inte stallas in pa en temperatur under
# 18C" (if airflow is set to 70 m3/h, room temperature must not be set below 18C).
def test_k2_vent402_cold_air_min_room_temp_rule(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "At that airflow setting the unit needs a minimum room temperature of 18C to "
            "avoid running cold/defrosting -- with the house at 17C, try raising your "
            "target room temperature to 18C or above and see if the airflow warms back up."),
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "the ventilation is blowing cold air and the house is only about 17 degrees",
        "IVT",
        ("Vent 402", {
            "state": "SPECIALIST", "decision": "solve",
            "required": ["18", ("room temperature", "18C")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert ServiceRequest.objects.count() == 0


# K3 -- ventilation smells bad after summer -- maintenance guidance
# Real content: vent_content.txt 7.5 "Rengoring av slangar och spillvattenkopp" --
# clean hoses/condensate cup with lukewarm water + mild antibacterial detergent at
# least twice a year, to remove dirt and algae (a common post-summer-idle complaint).
def test_k3_vent_smells_bad_after_summer_maintenance(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "A musty smell after the unit's been idle over summer is usually the condensate "
            "hoses and drip cup -- clean them with lukewarm water and a mild antibacterial "
            "detergent to clear out dirt and algae. Worth doing at least twice a year."),
        "confidence": 0.83, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "the ventilation has smelled musty ever since we started using it again after summer",
        "IVT",
        ("Vent 402", {
            "state": "SPECIALIST", "decision": "solve",
            "required": [("hose", "condensate", "drip cup"), ("clean", "detergent")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    assert ServiceRequest.objects.count() == 0


# K4 -- Vent unit whistling/noisy at night -- filter/registers check, then escalate
def test_k4_vent_whistling_check_then_escalate(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "A whistling sound usually means a dirty filter or a partly blocked exhaust "
            "vent -- clean the particle filter and check the ceiling/wall exhaust registers "
            "aren't obstructed, then see if it's quieter."),
        "confidence": 0.8, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "the ventilation unit has started whistling at night, quite loud",
        "IVT",
        ("Vent 402", {
            "state": "SPECIALIST", "decision": "solve",
            "required": [("filter", "vent", "register")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)

    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Since it's still whistling after cleaning the filter and checking the vents, this needs a technician to look at.",
    }
    res = orch.process_turn(conv, "cleaned the filter and checked the vents, still whistling")
    assert res["state"] == "ESCALATE"
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] in ("low_confidence", "decision")
    finish_escalation(conv, name="Noise Tester", phone="070-700 10 20")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# K5 -- Grundfos pump losing pressure -- documented tier (Grundfos SQ has a seeded
# Machine row) -> routes through SPECIALIST like any supported brand; pressure loss
# implicates the pressure tank/switch, which is out of low-stakes scope (same forbidden
# instruction class B4 guards -- "adjust the pressure switch").
def test_k5_grundfos_pressure_loss_documented_tier_escalates(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Gradual pressure loss like that usually means the pressure tank or switch needs checking -- that's technician work, I won't have you adjust the pressure switch yourself.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "water_pump_well",
        "no",  # postcode asked early (S2) -- declined
        "our Grundfos well pump has been losing pressure over the last week",
        "Grundfos",
        ("Grundfos SQ", {
            "state": "ESCALATE",
            "prohibited": ["adjust the pressure switch"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    # documented brand -> matched a Machine row -> never fell through to UNSUPPORTED
    assert conv.case_state["escalation_reason"] != "unsupported"
    finish_escalation(conv, name="Mats Berg", phone="070-701 10 20")
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "Grundfos"
    assert ServiceRequest.objects.filter(session=sess).exists()


# K6 -- Debe well pump short-cycling -- same documented-tier check as K5, different
# seeded brand (Debe DPM also has a Machine row).
def test_k6_debe_pump_short_cycling_documented_tier_escalates(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Rapid on/off cycling points at the pressure tank or switch again -- that needs a technician, I won't walk you through adjusting the pressure switch.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "water_pump_well",
        "no",  # postcode asked early (S2) -- declined
        "the Debe pump for our well turns on and off every few seconds",
        "Debe",
        ("Debe DPM", {
            "state": "ESCALATE",
            "prohibited": ["adjust the pressure switch"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] != "unsupported"
    finish_escalation(conv, name="Astrid Lund", phone="070-702 10 20")
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "Debe"
    assert ServiceRequest.objects.filter(session=sess).exists()


# K7 -- Scandia Pumps -- vendor seeded but NO Machine row (no manual loaded) -> must
# NOT invent troubleshooting steps; info-gather (model, symptom) -> lead with complete
# context. Contrast with K5/K6: same "water pump" category, different tier because
# there is no documented machine to route to.
def test_k7_scandia_pumps_no_manual_unsupported_referral(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "We don't have a manual loaded for Scandia Pumps yet, but I can get a Nordland technician out to take a look.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "water_pump_well",
        "no",  # postcode asked early (S2) -- declined
        "no water pressure at all from our Scandia Pumps well pump",
        "Scandia Pumps",
        ("Scandia SP 200", {
            "state": "ESCALATE",
            "decision": "escalate",
            # must not fabricate a Scandia-specific fix
            "prohibited": ["scandia pumps sp 200 is caused by", "the fix is to", "step 1:"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "unsupported"
    finish_escalation(conv, name="Per Lindqvist", phone="070-703 10 20")
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "Scandia Pumps"
    assert sess.machine is None
    sr = ServiceRequest.objects.get(session=sess)
    assert sr.escalation_reason == "unsupported"


# K8 -- Aqua Expert water filter, brown water -- referral-only; gather machine
# identity + symptom, no invented filtration troubleshooting (no Machine row seeded
# for Aqua Expert either).
def test_k8_aqua_expert_brown_water_referral_only(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "We don't have your Aqua Expert filter's manual loaded, but I can get a technician to come look at the brown water.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "water_filtration",
        "no",  # postcode asked early (S2) -- declined
        "the water coming out of the tap has gone brown since yesterday",
        "Aqua Expert",
        ("Aqua Expert AE-500", {
            "state": "ESCALATE",
            "decision": "escalate",
            "prohibited": ["replace the media", "backwash the filter", "step 1:"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "unsupported"
    finish_escalation(conv, name="Elin Karlsson", phone="070-704 10 20")
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "Aqua Expert"
    sr = ServiceRequest.objects.get(session=sess)
    assert sr.escalation_reason == "unsupported"


# K9 -- Aqua Invent -- customer insists the bot walk them through opening the filter
# housing; bot must politely refuse to guide undocumented work and escalate instead
# (no Machine row for Aqua Invent -> UNSUPPORTED_INTAKE; the refusal is a content
# assertion since "open the filter housing" isn't a guardrails._FORBIDDEN keyword hit
# on its own -- this test is what actually proves the bot doesn't comply).
def test_k9_aqua_invent_refuses_to_guide_filter_housing_open(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "I don't have documentation for the Aqua Invent filter, so I can't walk you through opening the housing myself -- I'll get a technician out to handle it safely.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "water_filtration",
        "no",  # postcode asked early (S2) -- declined
        "just tell me exactly how to open the filter housing and swap the cartridge myself, I don't want to wait for a technician",
        "Aqua Invent",
        ("Aqua Invent AI-9", {
            "state": "ESCALATE",
            "decision": "escalate",
            "prohibited": [
                "unscrew the filter housing", "open the filter housing", "remove the housing cover",
                "step 1:", "first, unscrew",
            ],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "unsupported"
    # customer pushes again -- bot must keep holding the line, not cave under pressure
    res2 = orch.process_turn(conv, "come on, just the quick steps")
    low = res2["message"].lower()
    for bad in ("unscrew the filter housing", "open the filter housing", "step 1:"):
        assert bad not in low
    finish_escalation(conv, name="Nils Berggren", phone="070-705 10 20")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# K10 -- completely unsupported brand (NIBE) -- unsupported path, gather info, lead
# with brand captured. (Distinct persona/flow from the catalog's C1, per the task
# brief's explicit K10 slot.)
def test_k10_unsupported_brand_nibe_lead_with_brand_captured(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "We don't have a NIBE manual loaded, but a Nordland technician can still take a look.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "compressor keeps cutting out on my heat pump",
        "NIBE",
        ("S1255", {
            "state": "ESCALATE",
            "decision": "escalate",
            "prohibited": ["s1255 is caused by", "the fix is to"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "unsupported"
    finish_escalation(conv, name="Ove Sandberg", phone="070-706 10 20")
    sess = Session.objects.get(conversation=conv)
    assert sess.manufacturer == "NIBE"
    sr = ServiceRequest.objects.get(session=sess)
    assert sr.escalation_reason == "unsupported"


# K11 -- customer doesn't know the brand at all ("en gammal pump i kallaren" -- "an
# old pump in the basement") -- photo-first ask, vision mock returns a nameplate read
# -> correct routing (here: Grundfos SQ, a DOCUMENTED brand, so the photo ID must land
# the case in SPECIALIST rather than UNSUPPORTED -- proving OCR->brand->tier routing
# is correct, not just that OCR fills slots).
def test_k11_unknown_pump_photo_first_identifies_documented_brand(seeded, mock_gemini):
    mock_gemini.responses["vision"] = {"manufacturer": "Grundfos", "model": "SQ",
                                       "serial": "SN99", "error_code": ""}
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Thanks for the photo -- rapid pressure swings on an SQ like that need a technician to check the tank/switch.",
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "water_pump_well")
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    # no brand known yet -- customer describes it as just "an old pump in the basement"
    # ("en gammal pump i kallaren") and attaches a nameplate photo instead of typing a brand
    res = orch.process_turn(
        conv, "it's an old pump in the basement, not sure what brand, pressure keeps surging",
        image=_photo())
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "Grundfos"
    assert conv.case_state["slots"]["model"] == "SQ"
    assert conv.case_state["slots"]["nameplate_photo"] is True
    assert any(e.get("type") == "tool_result" and e.get("name") == "vision_extract"
               for e in res.get("events", []))
    # route to the next turn if not already routed
    for _ in range(3):
        if conv.case_state["state"] in ("SPECIALIST", "ESCALATE", "RESOLVED"):
            break
        orch.process_turn(conv, "")
        conv.refresh_from_db()
    # correct routing: Grundfos IS a documented brand (seeded Machine row) -> never
    # fell through to UNSUPPORTED_INTAKE, even though the customer didn't know the brand.
    assert conv.case_state["state"] in ("SPECIALIST", "ESCALATE")
    assert conv.case_state.get("escalation_reason") != "unsupported"


# K12 -- municipal water pressure issue (not the machine itself) -- bot recognizes
# this is out of scope of any serviceable machine, still creates a lead (e.g. for a
# plumber referral) rather than troubleshooting a pump that isn't the actual problem.
def test_k12_municipal_water_pressure_out_of_scope_still_leads(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "That sounds like a municipal supply pressure issue rather than something with your own pump -- I'll log this so someone can help arrange a plumber to look into it.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "water_pump_well",
        "no",  # postcode asked early (S2) -- declined
        "water pressure from the mains/municipal supply has been low all over the house, our pump isn't even running",
        "other",
        ("no pump involved, it's the municipal supply", {
            "state": "ESCALATE",
            "decision": "escalate",
            "prohibited": ["adjust the pressure switch", "open the meter", "tamper with the meter"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "unsupported"
    finish_escalation(conv, name="Birgitta Holm", phone="070-707 10 20")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# K13 -- Vent 402 error code that's NOT in the docs -> low_confidence escalate with
# the code captured in the lead (specialist honestly reports in_docs=False rather than
# guessing a remedy for an unrecognized code).
def test_k13_vent402_undocumented_error_code_low_confidence_escalate(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.3, "in_docs": False,
        "answer_to_customer": "That code isn't one I recognize in the Vent 402 documentation, so I don't want to guess -- I'll get a technician to look into it.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "display is showing error code Z99 7777, never seen that one before",
        "IVT",
        ("Vent 402", {
            "state": "ESCALATE",
            "decision": "escalate",
            "prohibited": ["z99 7777 means", "z99 7777 is caused by"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "low_confidence"
    assert conv.case_state["slots"]["error_code"] == "Z99 7777"
    finish_escalation(conv, name="Erik Sundqvist", phone="070-708 10 20")
    sess = Session.objects.get(conversation=conv)
    assert sess.error_code == "Z99 7777"
    sr = ServiceRequest.objects.get(session=sess)
    assert sr.escalation_reason == "low_confidence"
    assert sr.payload_json["equipment"]["error_code"] == "Z99 7777"


# K14 -- mixed: heat pump AND ventilation both acting up (two machines in one case).
# The FSM only tracks a single machine per CaseState -- assert graceful handling: the
# case still routes on the identified machine, the second complaint isn't silently
# dropped from the captured problem text, and it escalates rather than the specialist
# fabricating simultaneous fixes for two different units.
def test_k14_mixed_heat_pump_and_ventilation_graceful_single_case(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.5, "in_docs": True,
        "answer_to_customer": "Since both your heat pump and the ventilation unit are acting up at once, I'd rather have a technician look at the whole system rather than guess -- I'll note both issues for them.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        ("both my heat pump and the ventilation unit have been acting up this week -- "
         "the heat pump keeps alarming and the ventilation is noisy too", {"state": "INTAKE"}),
        "IVT",
        ("Geo 412C", {
            "state": "ESCALATE",
            "decision": "escalate",
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    conv.refresh_from_db()
    # the second machine's complaint must survive in the captured problem text, not be
    # silently dropped just because the FSM only routes one machine per case
    problem = (conv.case_state["slots"].get("problem") or "").lower()
    assert "ventilation" in problem
    assert "heat pump" in problem
    assert conv.case_state["escalation_reason"] in ("low_confidence", "decision")
    finish_escalation(conv, name="Sara Nystrom", phone="070-709 10 20")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()
