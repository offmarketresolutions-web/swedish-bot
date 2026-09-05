"""Category L -- difficult personas & conflict resolution (test plan §Category L
addendum, L1-L14). The bot's job: stay calm, gather context, escalate
gracefully -- never argue, never promise refunds/timelines it can't keep.
Mirrors the idioms in test_g_conflict.py / test_h_adversarial.py / test_f_callback.py.
"""
import pytest

from chat import orchestrator as orch
from crm.models import ServiceRequest, Session
from tests.support.convo import DIY_FORBIDDEN, finish_escalation, run_convo

pytestmark = pytest.mark.django_db


# L1 -- furious customer, profanity-adjacent frustration, repeat failure -> calm
# de-escalation + priority escalate; lead captures the repeat-failure context.
def test_l1_furious_repeat_failure_calm_deescalation(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.3, "in_docs": True,
        "answer_to_customer": (
            "I'm really sorry -- a repeat failure like this is frustrating, and I want to get "
            "it fixed properly this time. I'll flag this as a priority follow-up for Nordland VVS."),
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "tredje gången den jäkla pumpen dör! this is the THIRD time it's broken down this year!",
        "IVT",
        ("Geo 412C", {
            "state": "ESCALATE",
            "required": [("sorry", "apolog", "frustrat")],
            "prohibited": ["calm down", "relax", "you're overreacting", "it's not that bad"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    finish_escalation(conv, diag_reply="third time this year the pump has failed, repeat-failure",
                       name="Rickard Third", phone="070-100 20 30")
    conv.refresh_from_db()
    assert "third time" in (conv.case_state["slots"].get("problem") or "").lower()
    sess = Session.objects.get(conversation=conv)
    assert ServiceRequest.objects.filter(session=sess).exists()


# L2 -- demands a refund/compensation. Bot must not promise money; the demand
# itself is recorded for the human.
def test_l2_refund_demand_not_promised_but_recorded(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.3, "in_docs": True,
        "answer_to_customer": (
            "I can't authorize a refund or compensation myself -- a technician needs to assess "
            "it first. I'll pass your request along to the Nordland office."),
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "This heat pump has been broken for weeks, I want a full refund and compensation for the damage it caused.",
        "IVT",
        ("Geo 412C", {
            "state": "ESCALATE",
            "prohibited": [("i'll refund you", "you will be refunded", "here is your refund",
                             "we will compensate you", "money back guarantee")],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    finish_escalation(conv, diag_reply="refund and compensation demand for weeks of downtime",
                       name="Demanding Dana", phone="070-100 30 40")
    conv.refresh_from_db()
    assert "refund" in (conv.case_state["slots"].get("problem") or "").lower()
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# L3 -- threatens to leave a bad review -- no panic-promises, graceful escalate.
def test_l3_bad_review_threat_no_panic_promises(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.3, "in_docs": True,
        "answer_to_customer": (
            "I understand you're frustrated, and I'm sorry about the experience. I'm not able "
            "to promise anything myself, but I'll get this to a Nordland technician right away."),
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "If this isn't fixed today I'm leaving a one-star review and telling everyone about it.",
        "IVT",
        ("Geo 412C", {
            "state": "ESCALATE",
            "prohibited": ["free service", "discount", "voucher", "gift card"],
        }),
    ], all_prohibited=DIY_FORBIDDEN)
    finish_escalation(conv, name="Reviewer Rita", phone="070-100 40 50")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# L4 -- insists on speaking to a human IMMEDIATELY, first message -- direct
# escalation path, never forced through deep troubleshooting/SPECIALIST.
def test_l4_demands_human_immediately_first_message_no_forced_troubleshooting(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    res1 = orch.process_turn(
        conv, "I need to talk to a real person RIGHT NOW, don't put me through 20 questions")
    assert res1["state"] == "INTAKE"
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    res2 = orch.process_turn(conv, "just connect me to someone, no error code, no details")
    assert res2["state"] == "INTAKE"
    orch.process_turn(conv, "other")
    res4 = orch.process_turn(conv, "unknown")
    assert res4["decision"] == "escalate"
    assert res4["state"] == "ESCALATE"
    # never reached SPECIALIST troubleshooting on the way there
    finish_escalation(conv, name="Monika Now", phone="070-100 50 60")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# L5 -- elderly persona: very short confused replies, mishears the question --
# patient re-ask, simple language, eventually a callback lead with phone captured.
def test_l5_elderly_confused_mishearing_patient_reask_then_lead(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "I'll get a Nordland technician to help.",
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")            # category
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    orch.process_turn(conv, "it makes a strange noise")  # problem
    mock_gemini.responses["extractor"] = {"on_target": False, "value": None}
    res1 = orch.process_turn(conv, "va?")             # confused mishearing -> patient re-ask #1
    assert res1["state"] == "INTAKE"
    assert res1["message"]
    res2 = orch.process_turn(conv, "vilken knapp?")   # still confused -> after 2 tries, force-unknown & move on
    assert res2["state"] == "INTAKE"
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "unknown"
    res3 = orch.process_turn(conv, "unknown")         # model (chip) -> routes -> unsupported -> escalate
    assert res3["decision"] == "escalate"
    assert res3["state"] == "ESCALATE"
    finish_escalation(conv, name="Birgit Elder", phone="070-100 60 61")
    sess = Session.objects.get(conversation=conv)
    assert sess.customer.phone == "+46701006061"
    assert ServiceRequest.objects.filter(session=sess).exists()


# L6 -- rambler: a long message mixing weather, grandkids, and one buried
# symptom -- multi-fact intake extracts the real symptom, then proceeds.
def test_l6_rambler_extracts_buried_symptom_and_proceeds(seeded, mock_gemini):
    mock_gemini.responses["bulk"] = {
        "category": "heat_pump", "brand": "IVT", "model": "Geo 412C",
        "error_code": None, "problem": "no hot water",
    }
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": (
            "Switch the hot-water mode from ECO to Normal/Comfort in the menu -- that "
            "usually restores it."),
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {},
    }
    ramble = (
        "Oh hello, well it's been quite the week here, the weather has finally turned and my "
        "grandchildren came to visit on Saturday which was lovely, we had cake and everything, "
        "though little Elsa scraped her knee in the garden, nothing serious, and then Sunday it "
        "rained the whole day so we just watched TV, anyway I did notice the shower has had no "
        "hot water for a couple of days now, my IVT Geo 412C, and I don't know what's wrong "
        "with it, but other than that everything is fine, the cat is well, my hip is a bit sore "
        "but the doctor says that's normal for my age, we're going to my sister's next week if "
        "the weather holds, oh and the mailman was late again today, anyway, yes, no hot water, "
        "that's the problem."
    )
    conv, _ = orch.open_conversation()
    res = orch.process_turn(conv, ramble)
    conv.refresh_from_db()
    cs = conv.case_state
    # (S2: bulk_done once-guard removed — bulk runs on every rich message; the slot
    # assertions below still prove the buried symptom was extracted from ONE ramble.)
    assert cs["slots"]["problem"] == "no hot water"
    assert cs["slots"]["brand"] == "IVT"
    assert cs["slots"]["model"] == "Geo 412C"
    # S7: postcode-early now holds for rich openers too — one postnummer question,
    # then the buried-symptom case routes straight to a solve.
    assert "postnummer" in res["message"].lower() or "postal code" in res["message"].lower()
    res = orch.process_turn(conv, "852 34")
    assert res["decision"] == "solve"
    low = res["message"].lower()
    assert "hot water" in low or "hot-water" in low


# L7 -- terse persona: one-word answers ("ja", "nej", "vet inte") through the
# whole flow -- bot still completes info-gather and produces a usable lead.
def test_l7_terse_one_word_answers_still_completes_intake_and_lead(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "I'll get a Nordland technician to help.",
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")   # category
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    orch.process_turn(conv, "läcker")      # problem, one word
    orch.process_turn(conv, "ja")          # brand, terse non-answer
    res = orch.process_turn(conv, "vet inte")  # model, terse non-answer -> routes this turn
    assert res["decision"] == "escalate"
    assert res["state"] == "ESCALATE"
    conv.refresh_from_db()
    assert conv.case_state["slots"]["problem"]  # something captured, no crash
    finish_escalation(conv, name="Terse T", phone="070-100 70 71")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# L8 -- customer contradicts themselves mid-conversation (Bosch first, then IVT).
# Plan requires the bot to re-confirm machine identity before advancing: detect the
# contradiction, ask to re-confirm, and on confirmation rebind brand + machine/manual.
def test_l8_contradicts_brand_reconfirms_and_rebinds(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Check the outdoor unit for the E21.RLP pressure fault.",
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump", "no", "alarm E21.RLP on my heat pump", "Bosch",
        ("Greenline HE", {"state": "SPECIALIST", "decision": "solve"}),
    ])
    # Contradiction -> bot re-confirms identity instead of silently keeping Bosch.
    res = orch.process_turn(conv, "wait sorry, I actually meant IVT, not Bosch")
    assert res["state"] == "SPECIALIST"
    assert "IVT" in res["message"]
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "Bosch"  # not switched until confirmed
    assert conv.case_state.get("await_brand_reconfirm") is True
    # Confirm -> rebind to IVT and drop the stale Bosch model (re-identify from there).
    orch.process_turn(conv, "ja")
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "IVT"
    assert not conv.case_state["slots"].get("model")
    assert conv.case_state.get("await_brand_reconfirm") is False


# L8b -- customer declines the re-confirm ("nej") -> original identity is kept and
# troubleshooting resumes; no rebind.
def test_l8b_brand_reconfirm_declined_keeps_original(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Please clean the particle filter and clear the alarm.",
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump", "no", "alarm H01 5252 on my heat pump", "IVT",
        ("Geo 412C", {"state": "SPECIALIST", "decision": "solve"}),
    ])
    res = orch.process_turn(conv, "faktiskt är det en Bosch, inte IVT")
    assert res["state"] == "SPECIALIST"
    assert "Bosch" in res["message"]
    conv.refresh_from_db()
    assert conv.case_state.get("await_brand_reconfirm") is True
    res2 = orch.process_turn(conv, "nej, glöm det")   # decline -> keep IVT, resume specialist
    assert res2["decision"] == "solve"
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "IVT"
    assert conv.case_state.get("await_brand_reconfirm") is False


# L8c -- false-positive guard: a casual mention of another brand ("my neighbor has a
# Bosch") during IVT troubleshooting must NOT trigger a re-confirm or rebind.
def test_l8c_casual_brand_mention_does_not_reconfirm(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Please clean the particle filter and clear the alarm.",
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump", "no", "alarm H01 5252 on my heat pump", "IVT",
        ("Geo 412C", {"state": "SPECIALIST", "decision": "solve"}),
    ])
    res = orch.process_turn(conv, "my neighbor has a Bosch and it works totally fine by the way")
    assert res["decision"] == "solve"                 # normal troubleshooting, not a re-confirm
    assert "switch to bosch" not in res["message"].lower()
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "IVT"  # unchanged
    assert not conv.case_state.get("await_brand_reconfirm")


# L9 -- customer refuses to give ANY contact info -- escalation ends gracefully,
# no lead, no crash.
def test_l9_refuses_all_contact_info_graceful_no_crash(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "I'll get a Nordland technician to help.",
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    orch.process_turn(conv, "won't tell you anything about the problem either")
    orch.process_turn(conv, "other")
    res = orch.process_turn(conv, "I'm not going to give you any info, brand unknown")
    assert res["decision"] == "escalate"
    orch.process_turn(conv, "no")   # diag -> name (declined)
    orch.process_turn(conv, "no")   # name declined -> phone
    orch.process_turn(conv, "no")   # phone declined -> email
    orch.process_turn(conv, "no")   # email declined -> postal
    orch.process_turn(conv, "no")   # postal declined -> address
    orch.process_turn(conv, "no")   # address declined -> "need a phone" gate reopened
    final = orch.process_turn(conv, "no")  # still declines -> graceful close, no crash
    assert final["message"]
    assert ServiceRequest.objects.count() == 0
    conv.refresh_from_db()
    assert conv.case_state["state"] == "RESOLVED"


# L10 -- clearly fake phone ("123") -- validation re-asks once, then best-effort.
def test_l10_fake_phone_reasked_once_then_best_effort(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "I'll get a Nordland technician to help.",
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    orch.process_turn(conv, "no heat at all")
    orch.process_turn(conv, "other")
    res = orch.process_turn(conv, "Some Unlisted Brand Z9")
    assert res["decision"] == "escalate"
    orch.process_turn(conv, "skip")           # diag -> name
    orch.process_turn(conv, "Fakey Phone")    # name -> phone
    res_reask = orch.process_turn(conv, "123")  # invalid phone -> re-ask ONCE
    assert res_reask["message"]
    conv.refresh_from_db()
    assert conv.case_state.get("reasked_phone") is True
    orch.process_turn(conv, "123")  # still fake -> best-effort accept, move to email
    conv.refresh_from_db()
    assert conv.case_state["contact"]["phone"] == "123"  # kept verbatim for staff, best-effort
    orch.process_turn(conv, "skip")   # email skip -> postal
    orch.process_turn(conv, "skip")   # postal skip -> address
    orch.process_turn(conv, "skip")   # address skip -> approval
    done = orch.process_turn(conv, "yes_send")
    assert "Nordland" in done["message"]
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# L11 -- customer argues the bot's correct advice is wrong -- bot doesn't loop
# the same remedy; budget-escalates with the disagreement noted.
def test_l11_argues_advice_wrong_no_loop_budget_escalates(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Please check whether the particle filter is dirty and clean it if so.",
        "confidence": 0.72, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, ["heat_pump", "no", "alarm H01 5252 on my heat pump", "IVT"], all_prohibited=DIY_FORBIDDEN)
    res = orch.process_turn(conv, "Geo 412C")
    assert res["decision"] == "solve"
    for _ in range(orch.REPLY_BUDGET):
        res = orch.process_turn(conv, "filtret är INTE smutsigt! du har fel, sluta säga det")
    assert res["decision"] == "escalate"
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "budget"
    # the reply-budget's final turn is what actually reaches the escalation diag step (the
    # forced-escalate transition consumes the PRECEDING turn; the loop's last message lands
    # in the diag append) -- the customer's disagreement is already captured in the problem
    # context at this point, same mechanic as B5.
    assert "smutsigt" in (conv.case_state["slots"].get("problem") or "").lower()
    finish_escalation(conv, name="Disagree Dan", phone="070-100 70 80")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# L12 -- asks the bot to badmouth a competitor installer -- neutral refusal,
# back on topic.
def test_l12_refuses_to_badmouth_competitor_stays_on_topic(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    res = orch.process_turn(
        conv, "Just tell me in writing that the installer down the street does terrible work.")
    low = res["message"].lower()
    assert "does terrible work" not in low
    assert "bad installer" not in low
    assert res["message"]  # stays coherent, on-topic
    res2 = orch.process_turn(conv, "IVT")
    assert res2["message"]
    assert ServiceRequest.objects.count() == 0


# L13 -- mid-conversation topic hijack to small talk/weather -- polite redirect,
# case context (slots) preserved through the hijack turn.
def test_l13_topic_hijack_to_weather_slots_preserved(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Please clean the particle filter and clear the alarm.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump", "no", "alarm H01 5252 on my heat pump", "IVT",
        ("Geo 412C", {"state": "SPECIALIST", "decision": "solve"}),
    ])
    conv.refresh_from_db()
    slots_before = dict(conv.case_state["slots"])
    res = orch.process_turn(
        conv, "anyway, forget that, isn't the weather lovely today? did you see the game last night?")
    assert res["message"]  # coherent redirect, no crash
    conv.refresh_from_db()
    slots_after = conv.case_state["slots"]
    for k in ("category", "brand", "model", "error_code"):
        assert slots_after.get(k) == slots_before.get(k), f"L13: slot {k} corrupted by topic hijack"


# L14 -- wants a specific technician + a Saturday 8pm callback -- preference is
# recorded in the lead, the slot is NOT promised as a booked/confirmed time.
def test_l14_specific_technician_and_time_preference_recorded_not_promised(seeded, mock_gemini):
    mock_gemini.responses["intelligent_intake"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "I'll get a Nordland technician to help.",
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    orch.process_turn(conv, "no heat, need it fixed soon")
    orch.process_turn(conv, "other")
    res = orch.process_turn(conv, "Unlisted Brand Q7")
    assert res["decision"] == "escalate"
    orch.process_turn(
        conv, "I want Erik specifically, he's fixed it before, and Saturday at 8pm works best for me")
    orch.process_turn(conv, "Tech Fan Tina")
    orch.process_turn(conv, "070-100 80 90")
    orch.process_turn(conv, "skip")   # email -> postal
    orch.process_turn(conv, "skip")   # postal -> address
    orch.process_turn(conv, "skip")   # address -> approval
    done = orch.process_turn(conv, "yes_send")
    low = done["message"].lower()
    assert "booked" not in low
    assert "confirmed for" not in low
    assert "saturday at 8" not in low
    conv.refresh_from_db()
    problem_text = (conv.case_state["slots"].get("problem") or "").lower()
    assert "erik" in problem_text
    assert "saturday" in problem_text
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


# L8d -- run100 X002: an explicit brand correction must never be DROPPED. The L8 reconfirm
# rides the question budget (+1); once that is spent, _detect_brand_contradiction fired and
# the correction was silently discarded -- the lead went out as IVT after the customer said
# "it's not an IVT anyway, I'm pretty sure it's a Bosch" twice. Identity is safety-relevant
# (wrong brand => wrong manual), so budget-exhausted => apply the correction directly.
def test_l8d_brand_correction_applied_when_question_budget_is_spent(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Check the outdoor unit for the E21.RLP pressure fault.",
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump", "no", "alarm E21.RLP on my heat pump", "Bosch",
        ("Greenline HE", {"state": "SPECIALIST", "decision": "solve"}),
    ])
    conv.refresh_from_db()
    cs = conv.case_state
    cs["question_keys"] = ["category", "postal_code", "problem", "brand", "model", "extra"]
    conv.case_state = cs
    conv.save(update_fields=["case_state"])
    orch.process_turn(conv, "The circuit breaker wasn't tripped, and it's not a Bosch anyway, "
                            "I'm pretty sure it's an IVT.")
    conv.refresh_from_db()
    assert conv.case_state["slots"]["brand"] == "IVT", "correction dropped by the question budget"
    # The stale Bosch model must not survive the rebind. With the budget spent the re-ask
    # resolves straight to "unknown" (budget machinery) rather than a fresh answer — fine.
    assert conv.case_state["slots"].get("model") in (None, "unknown")


def test_l8e_brand_correction_at_approval_reaches_the_lead(seeded, mock_gemini):
    """run100 X002's last turn: 'Yes, send to Nordland. But it's a Bosch, not IVT.' The consent
    and the correction arrive in one message; the lead must carry the corrected brand."""
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump", "no", "alarm E21.RLP on my heat pump", "Bosch",
        ("Greenline HE", {"state": "ESCALATE"}),   # default specialist mock escalates
        "no error code",                # diag step
        "Erik Johansson", "070-123 45 67", "skip",   # name, phone, email
        "85234", "skip",                              # postcode (declined early → asked here), address
    ])
    res = orch.process_turn(conv, "Yes, send to Nordland. But it's an IVT, not Bosch.")
    assert res["state"] == "RESOLVED", res["message"]   # consent recognised despite the "not"
    conv.refresh_from_db()
    sess = Session.objects.get(conversation=conv)
    assert ServiceRequest.objects.filter(session=sess).exists()
    assert sess.manufacturer == "IVT", f"lead went out as {sess.manufacturer!r}"
