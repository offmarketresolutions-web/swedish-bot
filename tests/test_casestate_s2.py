"""Sprint S2 — case-state expansion: per-turn multi-fact extraction, model-slot
protection, postcode-early + skip-at-contact, check memory, summarizer coverage,
and the new Session flush columns. Gemini mocked (offline, deterministic)."""
import pytest
from django.core.management import call_command

from chat import orchestrator as orch
from chat import prompts
from chat.casestate import flush_to_session, new_case_state
from chat.models import Conversation
from crm.models import Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def _cs(conv):
    conv.refresh_from_db()
    return conv.case_state


# ── per-turn multi-fact extraction ─────────────────────────────────────

def test_bulk_extract_merges_only_into_empty(seeded, mock_gemini):
    """A rich message mines every fact, but only fills EMPTY slots — a slot already
    captured is never clobbered by a later bulk pass."""
    mock_gemini.responses["bulk"] = {
        "category": "heat_pump", "subtype": None, "brand": "IVT", "model": "Geo 600",
        "error_code": "E9", "alarm_text": None, "onset": "sudden", "postal_code": None,
        "installer": None, "operating_context": None, "readings": [], "problem": "no heat",
    }
    conv, _ = orch.open_conversation()
    cs = conv.case_state
    cs["slots"]["brand"] = "Bosch"      # pre-existing — must survive
    conv.case_state = cs
    conv.save(update_fields=["case_state"])

    orch.process_turn(conv, "my IVT Geo 600 shows E9, no heat, started suddenly")
    s = _cs(conv)["slots"]
    assert s["brand"] == "Bosch"        # NOT overwritten by bulk's "IVT"
    assert s["model"] == "Geo 600"      # filled into empty
    assert s["error_code"] == "E9"
    assert s["onset"] == "sudden"


def test_bulk_runs_every_turn_not_once(seeded, mock_gemini):
    """The old bulk_done once-guard is gone: a fact stated on a LATER intake turn is
    still mined (regression against 'bulk only on the first message')."""
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")            # turn 1 — plain chip, nothing to mine
    mock_gemini.responses["bulk"] = {
        "category": None, "subtype": None, "brand": None, "model": None, "error_code": None,
        "alarm_text": None, "onset": "gradual", "postal_code": None, "installer": "nordland",
        "operating_context": None, "readings": [], "problem": None,
    }
    orch.process_turn(conv, "it's been getting worse gradually, Nordland installed it")
    s = _cs(conv)["slots"]
    assert s["onset"] == "gradual"
    assert s["installer"] == "nordland"


def test_model_slot_never_overwritten(seeded, mock_gemini):
    """slots.model holds RAW customer text and is never replaced by a later extraction."""
    conv, _ = orch.open_conversation()
    cs = conv.case_state
    cs["slots"]["model"] = "Geo 600"
    conv.case_state = cs
    conv.save(update_fields=["case_state"])
    mock_gemini.responses["bulk"] = {
        "category": "heat_pump", "subtype": None, "brand": None, "model": "Geo 600C",
        "error_code": None, "alarm_text": None, "onset": None, "postal_code": None,
        "installer": None, "operating_context": None, "readings": [], "problem": None,
    }
    orch.process_turn(conv, "it might be the Geo 600C actually, some model like that")
    assert _cs(conv)["slots"]["model"] == "Geo 600"   # raw text preserved


# ── postcode-early ─────────────────────────────────────────────────────

def test_postcode_asked_right_after_category(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    res = orch.process_turn(conv, "heat_pump")
    assert "postal code" in res["message"].lower() or "service area" in res["message"].lower()
    assert _cs(conv)["current_slot"] == "postal_code"


def test_postcode_asked_even_when_rich_opener_makes_case_routable(seeded, mock_gemini):
    """S7 regression (found by e2e scenario a): a rich opener that fills
    category+brand+model+problem makes is_routable() true, and intake used to
    short-circuit straight to ROUTING — the early postnummer ask was skipped
    entirely (it then only surfaced at lead-contact time). Postcode-early must
    hold for rich openers too: one postnummer question BEFORE routing."""
    mock_gemini.responses["bulk"] = {
        "category": "heat_pump", "subtype": None, "brand": "IVT", "model": "Geo 600",
        "error_code": "H01 5252", "alarm_text": None, "onset": None, "postal_code": None,
        "installer": None, "operating_context": None, "readings": [],
        "problem": "not enough hot water, house cold",
    }
    conv, _ = orch.open_conversation()
    res = orch.process_turn(
        conv, "My IVT Geo 600 heat pump shows H01 5252, not enough hot water, house cold")
    low = res["message"].lower()
    assert "postal code" in low or "postnummer" in low, low
    assert _cs(conv)["current_slot"] == "postal_code"
    # answering it proceeds into routing/specialist on the next turn (non-blocking)
    orch.process_turn(conv, "85234")
    assert _cs(conv)["slots"]["postal_code"] == "85234"


def test_postcode_not_reasked_when_rich_opener_contains_it(seeded, mock_gemini):
    """If the rich opener already states the postcode, routing proceeds without
    an extra postnummer question."""
    mock_gemini.responses["bulk"] = {
        "category": "heat_pump", "subtype": None, "brand": "IVT", "model": "Geo 600",
        "error_code": None, "alarm_text": None, "onset": None, "postal_code": "85234",
        "installer": None, "operating_context": None, "readings": [],
        "problem": "no heat",
    }
    conv, _ = orch.open_conversation()
    res = orch.process_turn(conv, "IVT Geo 600 no heat, I'm at 852 34 Sundsvall")
    low = res["message"].lower()
    assert "postal code" not in low and "postnummer" not in low, low
    assert _cs(conv)["slots"]["postal_code"] == "85234"


def test_postcode_two_reasks_then_unknown(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")            # → asks postcode
    r1 = orch.process_turn(conv, "not telling you")  # undecodable → reask #1
    assert "postal" in r1["message"].lower() or "postnummer" in r1["message"].lower()
    assert _cs(conv)["slots"]["postal_code"] is None
    orch.process_turn(conv, "still nope")            # reask #2 → give up → unknown
    assert _cs(conv)["slots"]["postal_code"] == "unknown"


def test_postcode_normalized_and_skipped_at_contact(seeded, mock_gemini):
    """A postcode captured early is normalized to 5 digits, flushed to the Session,
    and the contact stage never re-asks for it."""
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Not certain enough.", "confidence": 0.4, "decision": "solve",
        "in_docs": True, "report": {}}
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "852 34")               # space-tolerant postcode → 85234
    assert _cs(conv)["slots"]["postal_code"] == "85234"
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "other")
    orch.process_turn(conv, "Foobar 9000")          # unsupported → escalate → diag
    orch.process_turn(conv, "leaks and shows F2")   # diag → name
    orch.process_turn(conv, "Jane")                 # name → phone
    orch.process_turn(conv, "070-1234567")          # phone → email
    orch.process_turn(conv, "skip")                 # email → (postal skipped) → address
    approval = orch.process_turn(conv, "Storgatan 5")  # address → approval
    assert {c["value"] for c in approval["chips"]} == {"yes_send", "not_yet"}
    orch.process_turn(conv, "yes_send")
    sess = Session.objects.get(conversation=conv)
    assert sess.customer.postal_code == "85234"     # copied into contact, never re-asked
    assert sess.postal_code == "85234"              # flushed to the Session column


# ── check memory ───────────────────────────────────────────────────────

def _drive_to_specialist(conv):
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")           # postcode declined
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "IVT")
    return orch.process_turn(conv, "IVT 490")


def test_check_memory_accumulates_then_resolves(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Please check the inlet isolation valve is open.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
        "safe_steps_given": ["Check the inlet isolation valve is open"]}
    conv, _ = orch.open_conversation()
    _drive_to_specialist(conv)
    checks = _cs(conv)["report"]["checks"]
    assert checks == [{"step": "Check the inlet isolation valve is open", "result": "pending"}]

    # Next turn: the customer reports it didn't help; specialist suggests a new check.
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Okay, then check the breaker.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
        "safe_steps_given": ["Check the breaker is not tripped"],
        "extracted_facts": {"check_results": [{"step_hint": "inlet valve", "result": "no_help"}]}}
    orch.process_turn(conv, "the valve was already open, still no heat")
    rep = _cs(conv)["report"]
    steps = {c["step"]: c["result"] for c in rep["checks"]}
    assert steps["Check the inlet isolation valve is open"] == "no_help"   # resolved
    assert steps["Check the breaker is not tripped"] == "pending"          # new pending
    assert any("didn't help" in t for t in rep["troubleshooting_performed"])  # mirrored


def test_previous_checks_block_injected_into_prompt(seeded):
    cs = new_case_state()
    cs["report"]["checks"] = [
        {"step": "Check the inlet valve is open", "result": "no_help"},
        {"step": "Read the pressure gauge", "result": "pending"}]
    block = orch._previous_checks_block(cs)
    assert "– Check the inlet valve is open → didn't help" in block
    assert "– Read the pressure gauge → awaiting result" in block
    rendered = prompts.render("specialist", previous_checks=block)
    assert "Check the inlet valve is open" in rendered
    assert "re-suggest a check" in rendered   # the no-repeat rule is present


# ── summarizer coverage (prompt render, not live) ──────────────────────

def test_summarizer_prompt_covers_new_sections(seeded):
    body = prompts.render("summarizer")
    assert "form shown to customer — not confirmed submitted" in body
    assert "Missing:" in body
    assert "service-area" in body.lower() or "service area" in body.lower()
    assert "onset" in body.lower()


# ── Session flush of the new columns ───────────────────────────────────

def test_flush_writes_new_session_columns():
    conv = Conversation.objects.create(case_state=new_case_state())
    cs = conv.case_state
    cs["slots"]["postal_code"] = "85234"
    cs["slots"]["onset"] = "sudden"
    cs["slots"]["installer"] = "bylunds"
    cs["escalation_reason"] = "low_confidence"
    cs["service_area"] = "border"
    cs["report"]["form_status"] = "shown"
    session = flush_to_session(conv, cs)
    assert session.postal_code == "85234"
    assert session.onset == "sudden"
    assert session.installer == "bylunds"
    assert session.escalation_reason == "low_confidence"
    assert session.service_area_status == "border"
    assert session.form_shown is True


def test_two_checks_reported_with_different_outcomes_are_not_collapsed(seeded, mock_gemini):
    """Regression (audit 2026-08-11): _apply_extracted_facts kept only the LAST result in
    check_results and stamped it onto EVERY pending check, discarding step_hint. A customer
    who says one check helped and another they refused had both recorded as refused, so the
    technician's lead misreported what was actually tried."""
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Please check the inlet valve, and also the breaker.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
        "safe_steps_given": ["Check the inlet isolation valve is open",
                             "Check the breaker is not tripped"]}
    conv, _ = orch.open_conversation()
    _drive_to_specialist(conv)
    assert [c["result"] for c in _cs(conv)["report"]["checks"]] == ["pending", "pending"]

    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Thanks.", "confidence": 0.9, "decision": "solve",
        "in_docs": True, "report": {},
        "extracted_facts": {"check_results": [
            {"step_hint": "inlet valve", "result": "helped"},
            {"step_hint": "breaker", "result": "refused"}]}}
    orch.process_turn(conv, "opening the valve helped; I won't touch the breaker")

    steps = {c["step"]: c["result"] for c in _cs(conv)["report"]["checks"]}
    assert steps["Check the inlet isolation valve is open"] == "helped"
    assert steps["Check the breaker is not tripped"] == "refused"


def test_single_result_still_resolves_every_pending_check(seeded, mock_gemini):
    """Guard the existing intent: one blanket 'none of that helped' with no step_hint must
    still close out all pending checks, so the fix above doesn't strand them as pending."""
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Try the valve and the breaker.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
        "safe_steps_given": ["Check the inlet isolation valve is open",
                             "Check the breaker is not tripped"]}
    conv, _ = orch.open_conversation()
    _drive_to_specialist(conv)

    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Understood.", "confidence": 0.9, "decision": "solve",
        "in_docs": True, "report": {},
        "extracted_facts": {"check_results": [{"result": "no_help"}]}}
    orch.process_turn(conv, "none of that helped")

    assert {c["result"] for c in _cs(conv)["report"]["checks"]} == {"no_help"}


def test_bare_postcode_is_accepted_deterministically_without_an_llm_call(seeded, mock_gemini):
    """Found in the 2026-09-05 latency run: '852 34' — a valid Sundsvall postcode, present in
    the table, and the spec's own 'with or without a space' example — was rejected twice with
    'didn't quite catch that'. looks_rich() treats any digit-bearing text as rich, so the bare
    postcode went to the bulk extractor, which returns nothing for six digits with no context.
    A message shaped like a Swedish postcode at the postcode question is accepted by regex —
    normalized to five digits — and costs zero model calls."""
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")                 # -> postcode question
    before = len(mock_gemini.calls)
    res = orch.process_turn(conv, "852 34")
    conv.refresh_from_db()
    assert conv.case_state["slots"]["postal_code"] == "85234"
    assert len(mock_gemini.calls) == before, "a bare postcode must not cost a model call"
    assert "didn't quite catch" not in (res.get("message") or "").lower()


def test_pre_escalate_diag_does_not_re_ask_for_an_error_code_already_known():
    """Spec §1/§2.3: "The customer must not be asked for those facts again later."
    The pre-escalation turn asked every customer for an error code even when one was
    already captured — it triggered 8 of the 14 "I already told you" complaints across
    100 live conversations (R019 "It's H01 5295. That's what I said.", R039, V034)."""
    from chat.i18n import t
    from chat.orchestrator import _pre_escalate_prompt

    known = {"slots": {"error_code": "H01 5252", "alarm_text": None}}
    unknown = {"slots": {"error_code": None, "alarm_text": None}}

    # No code on file → still ask for one.
    assert _pre_escalate_prompt(unknown, "en") == t("en", "pre_escalate_diag")
    # Code already captured → ask for detail, never for the code again.
    msg = _pre_escalate_prompt(known, "en")
    assert "fault code" not in msg and "error" not in msg.lower(), msg
    assert "detail" in msg.lower(), msg
    # Same in Swedish.
    sv = _pre_escalate_prompt(known, "sv")
    assert "larmkod" not in sv and "felkod" not in sv, sv
    # An alarm TEXT counts as already-known too.
    assert "fault code" not in _pre_escalate_prompt(
        {"slots": {"error_code": None, "alarm_text": "För stor skillnad framledning"}}, "en")


@pytest.mark.parametrize("reply", [
    "jag vet inte", "Jag vet inte modellen", "vet inte", "ingen aning",
    "kommer inte ihåg", "I don't know", "no idea", "not sure",
])
def test_dont_know_in_model_search_gives_up_instead_of_searching(reply):
    """Spec §2.8: "After two failed attempts, record the value as unknown and continue."

    In model-search mode any free text was treated as a model NAME, so a customer who
    said "jag vet inte modellen" had it cleaned into the model slot and searched — run100
    R048 answered that with "Menar du Debe DPM?" and the customer replied "Nej, jag sa ju
    att jag inte vet modellen." The English fast path existed; Swedish had none."""
    from chat.orchestrator import _consume_model_search

    cs = {"slots": {"brand": "Debe", "model": None}, "model_search_mode": True}
    out = _consume_model_search(cs, reply, "sv")
    assert out is None, f"{reply!r} should end the search, not ask again: {out}"
    assert cs["model_gave_up"] is True, reply
    assert cs["model_search_mode"] is False, reply
    assert cs["slots"]["model"] in (None, "", "unknown"), \
        f"{reply!r} must not be stored as a model name: {cs['slots']['model']!r}"


def test_consent_is_recorded_on_the_answer_not_on_the_question():
    """contact.consent was set to True at the moment the bot ASKED "shall I send this?",
    so a customer who answered "Nej" was left recorded as having consented (run100 D017:
    a billing complaint who said "Nej, jag vill inte att en tekniker ska höra av sig" and
    still carried consent=True). Nothing persisted it — Customer.consent_to_contact is
    only written on the yes-path — but a consent flag must never be true for someone who
    said no."""
    from chat.orchestrator import _escalate_step

    cs = {"slots": {}, "contact": {"name": "Ismael Andersson", "phone": "+46701234567",
                                   "email": "i@e.se", "address": "Götgatan 23",
                                   "postal_code": "12134"},
          "contact_slot": None, "diag_done": True, "awaiting_approval": False, "report": {}}
    out = _escalate_step(None, cs, "Götgatan 23", "sv")
    assert cs.get("awaiting_approval") is True, out
    assert cs["contact"].get("consent") is not True, \
        "consent must not be true merely because the approval question was asked"


@pytest.mark.parametrize("code", ["H01 5252", "H01 5295", "A01 5378", "E15 210"])
def test_an_alarm_code_is_not_accepted_as_a_model(code):
    """run100 R039 opened with "H01 5252 again. filter probably." and ended with
    slots.model = "H01 5252" — the alarm code stored as the machine model, which then
    rides into the lead and matches no manual."""
    from chat.sanitize import clean_model
    assert clean_model(code) == "", code


@pytest.mark.parametrize("model", ["F1145", "S1255", "F730", "IVT 490", "Geo 412C",
                                   "Vent 402", "EcoHeat 8", "Greenline HE"])
def test_real_models_that_look_like_codes_are_still_accepted(model):
    """NIBE genuinely sells F1145 / S1255 / F730. Rejecting anything letter+digit shaped
    would silently drop a whole manufacturer's catalogue."""
    from chat.sanitize import clean_model
    assert clean_model(model) == model, model
