"""tools/eval/spec_conformance.py — the checker that grades real conversations against
docs/spec/owner-workflow-spec.md.

This is the mechanism the whole "conversations match the spec" claim rests on, so it needs
its own tests. The first three drafts of it were WRONG in the expensive direction: they
flagged the bot for doing exactly what the spec asks (warning a customer off refrigerant
work, naming the refrigerant circuit in an alarm explanation, recording an unknown model
after two failed attempts, skipping the postcode for an off-domain caller). A checker with
false positives sends you to "fix" correct behaviour; one with false negatives guarantees
nothing. Both directions are pinned here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "eval"))
import spec_conformance as sc  # noqa: E402


def conv(bot_and_user, *, slots=None, decision=None, artifacts=None, contact=None, cid="T001"):
    """Build a minimal record in the shape runner.py writes."""
    transcript = []
    for role, content in bot_and_user:
        transcript.append({"role": role, "content": content})
    return {"id": cid, "category": "resolvable", "transcript": transcript,
            "slots": slots or {"category": "heat_pump"},
            "decision": decision, "artifacts": artifacts or {}, "contact": contact or {}}


def fire(rule_id, record):
    """Violations produced by one rule for one record."""
    return sc.run([record], rule_id)[rule_id]["violations"]


# ── §7/§8/§10 forbidden professional work ────────────────────────────────────

def test_instructing_professional_work_is_flagged():
    rec = conv([("assistant", "Öppna pumpstyrningen och justera tryckvakten till 2 bar.")])
    assert fire("S7-FORBIDDEN-GUIDANCE", rec)


def test_warning_the_customer_off_professional_work_is_not_flagged():
    """The spec REQUIRES this turn. Flagging it would invert the rule."""
    rec = conv([("assistant",
                 "Det är viktigt att du inte försöker justera några inställningar själv, "
                 "som till exempel förtrycket i trycktanken eller tryckvakten.")])
    assert not fire("S7-FORBIDDEN-GUIDANCE", rec)


def test_naming_a_component_in_an_alarm_explanation_is_not_flagged():
    """§6: the manual controls alarm-code meaning. Explaining that H01 5252 is a
    high-pressure alarm in the refrigerant circuit is the correct answer, not DIY advice."""
    rec = conv([("assistant",
                 "Felkod H01 5252 indikerar ett högtryckslarm i köldmediekretsen. "
                 "Det betyder att trycket i systemet är för högt.")])
    assert not fire("S7-FORBIDDEN-GUIDANCE", rec)


def test_safe_observation_of_a_component_is_not_flagged():
    """§10 explicitly allows reading gauges and looking at visible parts."""
    rec = conv([("assistant", "Du kan ofta se detta genom att titta på expansionskärlet.")])
    assert not fire("S7-FORBIDDEN-GUIDANCE", rec)


def test_english_authorized_personnel_warning_is_not_flagged():
    rec = conv([("assistant", "The refrigerant circuit is sealed and must only be handled "
                              "by authorized personnel.")])
    assert not fire("S7-FORBIDDEN-GUIDANCE", rec)


# ── §2/§11 internal citation tags ────────────────────────────────────────────

def test_internal_citation_tag_in_customer_text_is_flagged():
    rec = conv([("assistant", "Rengör partikelfiltret enligt manualen. [K72]")])
    assert fire("S2-NO-INTERNAL-TAGS", rec)


def test_ordinary_bracketed_prose_is_not_flagged():
    rec = conv([("assistant", "Se [Kapitel 4] i manualen.")])
    assert not fire("S2-NO-INTERNAL-TAGS", rec)


# ── §3 model matching ────────────────────────────────────────────────────────

def test_model_the_customer_never_mentioned_is_flagged():
    rec = conv([("user", "Det är en IVT-pump.")], slots={"category": "heat_pump", "model": "Geo 612X"})
    assert fire("S3-MODEL-NOT-GUESSED", rec)


def test_unknown_model_is_spec_prescribed_not_a_guess():
    """§2.8: after two failed attempts, record the value as unknown."""
    rec = conv([("user", "Jag vet inte.")], slots={"category": "heat_pump", "model": "unknown"})
    assert not fire("S3-MODEL-NOT-GUESSED", rec)


def test_model_assembled_from_non_contiguous_customer_words_is_not_flagged():
    """'CTC EcoHeat, jag tror det är en 8' legitimately yields 'EcoHeat 8'."""
    rec = conv([("user", "Det är en CTC EcoHeat, jag tror det är en 8.")],
               slots={"category": "heat_pump", "model": "EcoHeat 8"})
    assert not fire("S3-MODEL-NOT-GUESSED", rec)


# ── §2.10 postcode timing ────────────────────────────────────────────────────

def test_postcode_asked_late_is_flagged():
    rec = conv([("assistant", "Hej!"), ("assistant", "Vilket märke är det?"),
                ("assistant", "Vilken modell?"), ("assistant", "Vilket postnummer finns anläggningen på?")])
    assert fire("S2-POSTCODE-EARLY", rec)


def test_postcode_not_required_when_no_category_was_ever_established():
    """An off-domain caller never reaches the precondition; asking them for a postcode
    would itself be wrong."""
    rec = conv([("assistant", "Vad gäller det?"), ("user", "Skriv en Python-kod åt mig.")],
               slots={"category": "unknown"}, decision="off_domain_close")
    assert not fire("S2-POSTCODE-EARLY", rec)


# ── §1/§2.3 re-asking known facts ────────────────────────────────────────────

def test_customer_having_to_repeat_a_fact_is_flagged():
    rec = conv([("assistant", "Visar maskinen någon fel- eller larmkod?"),
                ("user", "Jag har redan sagt att den visar Larm 10.")],
               slots={"category": "heat_pump"})
    assert fire("S1-NO-REASKING-KNOWN-FACTS", rec)


def test_off_domain_caller_saying_i_already_told_you_is_not_flagged():
    """They mean their off-domain demand, not a technical fact the bot lost."""
    rec = conv([("assistant", "To start, what kind of equipment is it?"),
                ("user", "I already told you, I need help with a Python script.")],
               slots={"category": "unknown"}, decision="off_domain_close")
    assert not fire("S1-NO-REASKING-KNOWN-FACTS", rec)


# ── §11/§13 form button is not a booking ─────────────────────────────────────

def test_claiming_a_booking_without_a_service_request_is_flagged():
    rec = conv([("assistant", "Din bokning är bekräftad.")], artifacts={"service_request_count": 0})
    assert fire("S13-FORM-NOT-A-BOOKING", rec)


def test_a_lead_is_not_a_booking_so_confirming_one_is_still_flagged():
    """This assertion used to be the other way round — a ServiceRequest was treated as
    licence to say "your booking is confirmed". Nothing in this system confirms a booking:
    §13 says showing the form button "does not mean the form is submitted or that a booking
    is confirmed", and §11 lists "booking not confirmed" as a status the summary must
    REPORT. The office schedules, after it receives the lead."""
    rec = conv([("assistant", "Din bokning är bekräftad.")], artifacts={"service_request_count": 1})
    assert fire("S13-FORM-NOT-A-BOOKING", rec)


def test_the_future_tense_promise_is_flagged_even_with_a_lead():
    """The live failure: "Jag kommer att boka in ett servicebesök för dig", said mid-
    conversation. The old rule only matched past-tense confirmations."""
    for claim in ("Jag kommer att boka in ett servicebesök för dig.",
                  "Jag bokar in en tekniker imorgon.",
                  "En tekniker från Nordland larmas nu."):
        rec = conv([("assistant", claim)], artifacts={"service_request_count": 1})
        assert fire("S13-FORM-NOT-A-BOOKING", rec), claim


def test_offering_to_send_the_case_is_not_flagged():
    """The correct wording must survive — this is what the bot is supposed to say."""
    for ok in ("Ska jag skicka dina uppgifter till Nordland VVS?",
               "Jag skickar detta till Nordland VVS så hör de av sig.",
               "Kan jag skicka detta till Nordland VVS så att en tekniker kan höra av sig?"):
        rec = conv([("assistant", ok)], artifacts={"service_request_count": 1})
        assert not fire("S13-FORM-NOT-A-BOOKING", rec), ok


# ── §4 manufacturer preserved ────────────────────────────────────────────────

def test_known_brand_flattened_to_other_is_flagged():
    rec = conv([("user", "Jag har en NIBE värmepump.")],
               slots={"category": "heat_pump", "brand": "other"})
    assert fire("S4-BRAND-PRESERVED", rec)


def test_known_brand_preserved_is_not_flagged():
    rec = conv([("user", "Jag har en NIBE värmepump.")],
               slots={"category": "heat_pump", "brand": "NIBE"})
    assert not fire("S4-BRAND-PRESERVED", rec)


def test_every_rule_cites_a_spec_section():
    """A rule with no spec citation is an opinion, not a conformance check."""
    assert sc.RULES, "no rules registered"
    for r in sc.RULES:
        assert r["section"].startswith("§"), r
        assert r["desc"].strip(), r


def test_comfort_complaint_without_onset_is_flagged():
    """§7's always-vs-sudden distinction is the precondition for deciding the case."""
    rec = conv([("user", "Det är för kallt i huset.")],
               slots={"category": "heat_pump", "onset": None})
    assert fire("S7-ONSET-ESTABLISHED", rec)


def test_comfort_complaint_with_onset_established_is_not_flagged():
    rec = conv([("user", "Det är för kallt i huset.")],
               slots={"category": "heat_pump", "onset": "always"})
    assert not fire("S7-ONSET-ESTABLISHED", rec)


def test_non_comfort_case_does_not_require_onset():
    """A leak or an alarm code is not a comfort/performance complaint; §7 doesn't apply."""
    rec = conv([("user", "Det läcker vatten under pumpen.")],
               slots={"category": "heat_pump", "onset": None})
    assert not fire("S7-ONSET-ESTABLISHED", rec)


def test_alarm_code_stored_as_model_is_flagged():
    rec = conv([("user", "H01 5252 again. filter probably.")],
               slots={"category": "heat_pump", "model": "H01 5252"})
    assert fire("S3-MODEL-IS-NOT-AN-ALARM", rec)


def test_a_real_model_that_looks_like_a_code_is_not_flagged():
    """NIBE F1145 is a genuine product; only the two-part alarm shape is a fault reading."""
    for model in ("F1145", "S1255", "IVT 490", "Geo 412C"):
        rec = conv([("user", f"Jag har en {model}.")],
                   slots={"category": "heat_pump", "model": model})
        assert not fire("S3-MODEL-IS-NOT-AN-ALARM", rec), model


def test_lead_summary_hiding_a_missing_model_is_flagged():
    rec = conv([("user", "Det låter konstigt.")], slots={"category": "heat_pump", "model": "unknown"},
               artifacts={"service_requests": [{"payload_json": {
                   "summary": "Customer reports noise. Technician dispatched."}}]})
    assert fire("S11-SUMMARY-STATES-GAPS", rec)


def test_lead_summary_that_declares_the_gap_is_not_flagged():
    rec = conv([("user", "Det låter konstigt.")], slots={"category": "heat_pump", "model": "unknown"},
               artifacts={"service_requests": [{"payload_json": {
                   "summary": "Customer reports noise. Missing: equipment model, error code."}}]})
    assert not fire("S11-SUMMARY-STATES-GAPS", rec)


def test_unnormalised_postcode_is_flagged():
    for raw in ("111 52 ", "16150 ", "111 52 Stockholm"):
        rec = conv([("user", raw)], slots={"category": "heat_pump", "postal_code": raw})
        assert fire("S12-POSTCODE-NORMALISED", rec), raw


def test_five_digit_postcode_is_not_flagged():
    rec = conv([("user", "11152")], slots={"category": "heat_pump", "postal_code": "11152"})
    assert not fire("S12-POSTCODE-NORMALISED", rec)


def test_unknown_postcode_is_not_flagged():
    """§2.8 records an unanswered slot as unknown; that is conformance, not a bad value."""
    rec = conv([("user", "vet inte")], slots={"category": "heat_pump", "postal_code": "unknown"})
    assert not fire("S12-POSTCODE-NORMALISED", rec)


def test_the_refrigerant_emergency_template_is_not_flagged():
    """The deterministic safety reply names the hazard, gives safe actions (ventilate,
    keep away) and forbids touching the unit — all correct per §10. A window-based
    prohibition check missed the "don't touch" 150 characters downstream and flagged this
    exact message on five safety conversations."""
    for msg in (
        "That sounds like it could be a refrigerant leak. Keep people and pets away from "
        "the unit, open windows to ventilate, no open flames or smoking nearby, and don't "
        "touch or operate the unit. A Nordland technician is being alerted urgently.",
        "Det låter som att det kan vara ett köldmedieläckage. Håll människor och husdjur "
        "borta från enheten, öppna fönster och vädra, ingen öppen eld eller rökning i "
        "närheten, och rör eller hantera inte enheten.",
    ):
        assert not fire("S7-FORBIDDEN-GUIDANCE", conv([("assistant", msg)])), msg[:60]


def test_a_genuine_instruction_is_still_flagged_in_a_long_turn():
    """Widening the prohibition scan must not blind the rule: a turn that actually tells
    the customer to do professional work still fails, even if it is chatty."""
    msg = ("Tack för informationen om din värmepump. För att komma vidare behöver du "
           "öppna pumpstyrningen och justera tryckvakten till 2 bar. Hör av dig sedan.")
    assert fire("S7-FORBIDDEN-GUIDANCE", conv([("assistant", msg)]))


def test_contact_asked_after_a_self_solved_fix_is_not_flagged():
    """§2.9 forbids asking for contact details DURING technical intake. Asking once the
    customer already has their working answer — so a specialist can review the case and
    follow up — is not intake, and flagging it would have condemned the correct flow."""
    rec = conv([
        ("assistant", "Clean the extract-air filter.\n\nDid that fix it?"),
        ("user", "yes that worked"),
        ("assistant", "Glad that sorted it! Can I take your phone number and email? "
                      "One of our specialists reviews these cases."),
        ("user", "yes please"),
        ("assistant", "What's your name?"),
    ], decision="solve")
    assert not fire("S2-NO-CONTACT-IN-INTAKE", rec)


def test_contact_asked_before_any_answer_is_still_flagged():
    """The rule must keep its teeth: asking for a phone number mid-intake, before the
    customer has been helped at all, is exactly what §2.9 prohibits."""
    rec = conv([
        ("assistant", "To start, what kind of equipment is it?"),
        ("user", "heat pump"),
        ("assistant", "What's the best phone number to reach you?"),
    ])
    assert fire("S2-NO-CONTACT-IN-INTAKE", rec)


# ── gap #21 (R-7.13/7.14) — RAISE_SETTING missed flow-temperature and indefinite wording ────

def test_raise_setting_catches_flow_temperature_and_screw_up_and_indefinite_hot_water():
    """Before: 'öka' was bound only to (värme)kurvan, and framledningstemperatur (flow
    temperature) and 'skruva upp' were not covered at all."""
    for msg in (
        "Höj framledningstemperaturen några grader så blir det varmare.",
        "Öka framledningen lite på panelen.",
        "Skruva upp kurvan ett par steg.",
        "Öka varmvattentemperaturen till 55 grader.",
    ):
        rec = conv([("assistant", msg)], slots={"onset": "sudden"})
        assert fire("S7-SUDDEN-NOT-A-SETTING", rec), msg


def test_raising_something_unrelated_to_heat_settings_is_not_flagged():
    """Widening RAISE_SETTING must not turn 'öka'/'höj' into a blanket matcher — increasing
    airflow by cleaning a filter is unrelated, legitimate advice."""
    rec = conv([("assistant", "Öka luftflödet genom att rengöra filtret regelbundet.")],
               slots={"onset": "sudden"})
    assert not fire("S7-SUDDEN-NOT-A-SETTING", rec)


# ── gap #22 (R-9.16) — REFER_AWAY missed brand/installer/service-workshop phrasing ─────────

def test_refer_away_catches_brand_installer_and_service_workshop_phrasing():
    for msg in (
        "Jag rekommenderar att du kontaktar NIBE direkt för den frågan.",
        "Kontakta din installatör angående detta.",
        "Hör av dig till serviceverkstaden för vidare hjälp.",
    ):
        rec = conv([("assistant", msg)])
        assert fire("S9-NO-REFER-AWAY", rec), msg


def test_referring_the_customer_to_nordland_itself_is_not_flagged():
    """§9 forbids referring the customer AWAY. Passing the case to Nordland VVS itself is
    the correct outcome and must never be caught by this rule."""
    for msg in (
        "Jag skickar detta till Nordland VVS så hör de av sig.",
        "Kan jag skicka detta till Nordland VVS så att en tekniker kan höra av sig?",
    ):
        rec = conv([("assistant", msg)])
        assert not fire("S9-NO-REFER-AWAY", rec), msg


# ── gap #23 (R-4.12) — S4-BRAND-PRESERVED's 12-brand list missed common manufacturers ──────

def test_newly_added_known_brands_are_recognised():
    for brand in ("Vaillant", "Nilan", "Jäspi", "Danfoss", "Villavarme"):
        rec = conv([("user", f"Jag har en {brand}-panna.")],
                   slots={"category": "heat_pump", "brand": "other"})
        assert fire("S4-BRAND-PRESERVED", rec), brand


def test_unlisted_brand_is_still_not_flagged():
    """A brand genuinely outside the known list is not this rule's problem — it must not
    over-fire just because a broader list was added."""
    rec = conv([("user", "Jag har en pump av något okänt fabrikat.")],
               slots={"category": "heat_pump", "brand": "other"})
    assert not fire("S4-BRAND-PRESERVED", rec)


# ── gap #24 (R-8.16) — filter-media change missed the imperative "byt" ─────────────────────

def test_imperative_filter_media_change_is_flagged():
    rec = conv([("assistant", "Byt filtermassan i sandfiltret idag.")])
    assert fire("S7-FORBIDDEN-GUIDANCE", rec)


def test_checking_whether_filter_media_needs_changing_is_not_flagged():
    """Describing/observing status and correctly deferring the actual work to a technician,
    not instructing the customer to do it themselves."""
    rec = conv([("assistant", "Kontrollera om filtermassan behöver bytas av en tekniker.")])
    assert not fire("S7-FORBIDDEN-GUIDANCE", rec)


# ── gap #25 (R-8.13) — dosing increase missed "höj" and the indefinite "dosering" ──────────

def test_raising_dosing_catches_imperative_and_indefinite_forms():
    for msg in ("Höj doseringen lite för att bli av med lukten.",
                "Öka dosering av klor något."):
        rec = conv([("assistant", msg)])
        assert fire("S7-FORBIDDEN-GUIDANCE", rec), msg


def test_checking_the_dosing_level_is_not_flagged():
    rec = conv([("assistant", "Kontrollera doseringen på pumpen och notera värdet.")])
    assert not fire("S7-FORBIDDEN-GUIDANCE", rec)


# ── gap #26 (R-8.11) — well-pump lifting required the definite form ────────────────────────

def test_lifting_indefinite_well_pump_is_flagged():
    rec = conv([("assistant", "Du kan behöva lyfta upp en brunnspump för att inspektera den.")])
    assert fire("S7-FORBIDDEN-GUIDANCE", rec)


def test_checking_pressure_without_lifting_the_pump_is_not_flagged():
    rec = conv([("assistant", "Kontrollera trycket vid brunnspumpen innan du gör något annat.")])
    assert not fire("S7-FORBIDDEN-GUIDANCE", rec)


# ── gap #27 (R-2.x) — CONTACT_ASK only recognised three exact phrases ──────────────────────

def test_broadened_contact_ask_phrasings_are_caught_during_intake():
    for msg in ("Kan du ge mig ditt namn?", "Vad är ditt telefonnummer?"):
        rec = conv([("assistant", "Vad är det för utrustning?"), ("user", "värmepump"),
                    ("assistant", msg)])
        assert fire("S2-NO-CONTACT-IN-INTAKE", rec), msg


def test_asking_for_a_serial_number_is_not_mistaken_for_a_phone_number():
    rec = conv([("assistant", "Vilket serienummer har enheten?")])
    assert not fire("S2-NO-CONTACT-IN-INTAKE", rec)


# ── gap #16 (R-11.10-11.13) — summary-gaps rule fired only on a missing model ──────────────

def test_summary_hiding_missing_contact_details_despite_known_model_is_flagged():
    """The old rule exited immediately once the model was known, so a summary that hid a
    missing phone/email, missing consent, or an unconfirmed booking sailed through
    untouched as long as the model happened to be captured."""
    rec = conv([("user", "Kompressorn låter konstigt.")],
               slots={"category": "heat_pump", "model": "NIBE F750"},
               artifacts={"error_code": "H01", "service_requests": [{"payload_json": {
                   "summary": "Customer reports a strange compressor noise. Technician "
                              "will follow up."}}]})
    assert fire("S11-SUMMARY-STATES-GAPS", rec)


def test_summary_disclosing_the_open_items_with_everything_known_is_not_flagged():
    rec = conv([("user", "Kompressorn låter konstigt.")],
               slots={"category": "heat_pump", "model": "NIBE F750"},
               artifacts={"error_code": "H01", "service_requests": [{"payload_json": {
                   "summary": "Customer reports a strange compressor noise. Contact and "
                              "consent captured. Booking not confirmed — Nordland VVS "
                              "will follow up."}}]},
               contact={"phone": "0701234567", "email": "a@b.se", "consent": True})
    assert not fire("S11-SUMMARY-STATES-GAPS", rec)


# ── the safety-footer masking defect ────────────────────────────────────────────────────────

def test_a_far_away_generic_safety_footer_does_not_mask_an_unrelated_instruction():
    """A canned closing disclaimer must not immunise an unrelated instruction earlier in the
    same turn. Before the window fix, _is_prohibition scanned the WHOLE turn: any prohibition
    phrase anywhere — even 300+ characters away, about a different component entirely —
    silenced every forbidden-guidance hit in that turn."""
    filler = " ".join(["Låt mig också nämna att det är vanligt med den här typen av fråga."] * 4)
    msg = (
        "Du kan sänka kompressorbegränsningen till 60% i installatörsmenyn för att minska "
        f"ljudet nattetid. {filler} "
        "Kom ihåg: allt arbete på kylkretsen och elektriska komponenter ska alltid utföras "
        "av behörig personal."
    )
    assert fire("S7-FORBIDDEN-GUIDANCE", conv([("assistant", msg)]))


def test_the_refrigerant_template_prohibition_still_works_after_the_window_fix():
    """The window must stay generous enough for the real deterministic template, where the
    hazard is named first and the prohibition follows ~130 characters later. This duplicates
    the intent of test_the_refrigerant_emergency_template_is_not_flagged as a direct check
    on the windowed behaviour, not just the end-to-end rule."""
    msg = ("That sounds like it could be a refrigerant leak. Keep people and pets away from "
           "the unit, open windows to ventilate, no open flames or smoking nearby, and don't "
           "touch or operate the unit. A Nordland technician is being alerted urgently.")
    assert not fire("S7-FORBIDDEN-GUIDANCE", conv([("assistant", msg)]))
