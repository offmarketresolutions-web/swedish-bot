"""Regression coverage for the 2026-07-13 live-eval gap fixes (docs/evals/
2026-07-13-gap-analysis.md). Uses the same `seeded` + `mock_gemini` fixtures and
`run_convo` driver as the rest of the scenario suite.

- GAP 1/6: post-solve confirmation FSM — yes → RESOLVED (no lead), no → back into
  troubleshooting (then legitimately escalates), a question → answered without the
  in_docs/low-confidence cap auto-escalating, then re-asked.
- GAP 2: a symptom-only opener lands category + problem via bulk-extract and never
  shows the "didn't catch that" apology.
- GAP 5: the "welcome back" greeting requires the name to match, not the phone alone.
"""
import pytest

from chat import orchestrator as orch
from crm.models import Customer, ServiceRequest, Session
from tests.support.convo import DIY_FORBIDDEN, run_convo

pytestmark = pytest.mark.django_db


_SOLVE_FILTER = {
    "answer_to_customer": (
        "H01 5252 means the particle filter is likely dirty — rinse it under running "
        "water and clear the alarm on the controller."),
    "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {"resolved": True},
}


def _to_solve(conv, mock_gemini):
    """Drive a conversation to a delivered specialist solve (awaiting confirmation)."""
    mock_gemini.responses["specialist"] = dict(_SOLVE_FILTER)
    return run_convo(conv, [
        "heat_pump",
        "no",  # postcode asked early (S2) -- declined
        "H01 5252 filter alarm keeps showing",
        "IVT",
        ("Geo 412C", {"state": "SPECIALIST", "decision": "solve",
                      "required": ["filter", ("clean", "rinse")]}),
    ], all_prohibited=DIY_FORBIDDEN)


# ── GAP 1/6 — post-solve confirmation ────────────────────────────────────────────────

def test_confirm_fix_prompt_appended_with_yesno_chips(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    res = _to_solve(conv, mock_gemini)[-1]
    # the solve turn now carries the confirmation ask + yes/no chips
    assert "did that fix it" in res["message"].lower()
    assert {c["value"] for c in res["chips"]} == {"yes", "no"}
    conv.refresh_from_db()
    assert conv.case_state["awaiting_confirm"] is True


def test_confirm_yes_resolves_without_lead(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _to_solve(conv, mock_gemini)
    final = orch.process_turn(conv, "yes")
    assert final["state"] == "RESOLVED" and final["decision"] == "solve"
    sess = Session.objects.get(conversation=conv)
    assert sess.resolved is True
    assert ServiceRequest.objects.count() == 0


def test_confirm_no_routes_back_to_troubleshooting_then_escalates(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _to_solve(conv, mock_gemini)
    # the remedy failed → a fresh troubleshooting turn runs; here it escalates
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.4, "in_docs": True,
        "answer_to_customer": "Since cleaning it didn't clear the alarm, this needs a technician.",
    }
    res = orch.process_turn(conv, "no, it's still showing the alarm")
    assert res["state"] == "ESCALATE"
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] in ("low_confidence", "decision")


def test_confirm_question_answered_without_autoescalation_then_resolves(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _to_solve(conv, mock_gemini)
    # A clarifying question about the remedy. in_docs=False + conf 0.5 would normally hard-cap
    # to an escalation, but while awaiting confirmation we answer it and re-ask instead.
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Good question — switch it off at the main switch first, then "
                              "rinse the filter and switch it back on.",
        "confidence": 0.5, "decision": "solve", "in_docs": False, "report": {},
    }
    res = orch.process_turn(conv, "do I need to turn the unit off first?")
    assert res["state"] == "SPECIALIST" and res["decision"] == "solve"
    assert "did that fix it" in res["message"].lower()
    for term in DIY_FORBIDDEN:
        assert term.lower() not in res["message"].lower()
    conv.refresh_from_db()
    assert conv.case_state["awaiting_confirm"] is True
    assert ServiceRequest.objects.count() == 0
    # now the customer confirms → resolved, still no lead
    final = orch.process_turn(conv, "yes, that did it, thanks")
    assert final["state"] == "RESOLVED"
    assert Session.objects.get(conversation=conv).resolved is True
    assert ServiceRequest.objects.count() == 0


# ── GAP 2 — symptom-only opener isn't misread as unintelligible ───────────────────────

def test_gap2_symptom_opener_lands_category_and_problem_no_apology(seeded, mock_gemini):
    mock_gemini.responses["bulk"] = {
        "category": "heat_pump", "brand": None, "model": None, "error_code": None,
        "problem": "house never gets warm though the pump runs",
    }
    conv, _ = orch.open_conversation()
    res = orch.process_turn(
        conv, "Huset blir aldrig riktigt varmt fast pumpen verkar gå som vanligt")
    conv.refresh_from_db()
    cs = conv.case_state
    assert cs["slots"]["category"] == "heat_pump"
    assert cs["slots"]["problem"]
    low = res["message"].lower()
    assert "didn't catch" not in low and "uppfattade inte" not in low
    # advances to the next missing slot (now postal_code, asked early per S2), not a
    # restart-from-equipment reask
    assert "postal code" in low or "postnummer" in low


def test_gap2_partial_bulk_does_not_apologize(seeded, mock_gemini):
    # bulk pulls brand/model/problem but not the category slug — must not apologize, just
    # ask the still-missing category plainly.
    mock_gemini.responses["bulk"] = {
        "category": None, "brand": "IVT", "model": "Geo 412C", "error_code": None,
        "problem": "making a weird grinding noise",
    }
    conv, _ = orch.open_conversation()
    res = orch.process_turn(conv, "my IVT Geo 412C is making a weird grinding noise")
    conv.refresh_from_db()
    cs = conv.case_state
    assert cs["slots"]["brand"] == "IVT"
    assert cs["slots"]["model"] == "Geo 412C"
    assert cs["slots"]["problem"]
    assert "didn't catch" not in res["message"].lower()


# ── GAP 5 — returning greeting requires a name match, not phone alone ──────────────────

def test_gap5_name_conflict_skips_welcome_back(seeded, mock_gemini):
    Customer.objects.create(name="Anna", phone="+46701112233", consent_to_contact=True)
    mock_gemini.responses["specialist"] = {
        "decision": "escalate", "confidence": 0.3, "in_docs": True,
        "answer_to_customer": "I'll get a Nordland technician to look at this.",
    }
    conv, _ = orch.open_conversation()
    run_convo(conv, [
        "heat_pump", "no", "no heat at all", "IVT", ("Geo 412C", {"state": "ESCALATE"}),
    ], all_prohibited=DIY_FORBIDDEN)
    orch.process_turn(conv, "skip")            # diag -> name
    orch.process_turn(conv, "Björn")           # DIFFERENT name than the on-file Anna
    orch.process_turn(conv, "070-111 22 33")   # SAME phone (hash matches Anna)
    conv.refresh_from_db()
    assert conv.case_state.get("returning") is not True
    orch.process_turn(conv, "skip")            # email
    orch.process_turn(conv, "skip")            # postal
    orch.process_turn(conv, "skip")            # address
    done = orch.process_turn(conv, "yes_send")
    low = done["message"].lower()
    assert "welcome back" not in low and "välkommen" not in low
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()
