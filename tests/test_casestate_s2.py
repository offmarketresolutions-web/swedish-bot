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
    approval = orch.process_turn(conv, "skip")      # email → (postal skipped) → approval
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
