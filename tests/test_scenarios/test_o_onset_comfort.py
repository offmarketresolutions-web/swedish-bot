"""Category O — onset rules + comfort settings (plan S4 / D1).

Two enforcement layers:
  1. CODE — a SUDDEN fault clamps the specialist troubleshooting budget to 3
     (both modes); a gradual/always fault keeps the full budget.
  2. PROMPT — the SPECIALIST + INTELLIGENT_SPECIALIST bodies gain an ONSET RULES
     section: sudden+unexplained → look-only, NEVER settings-to-compensate;
     always/gradual comfort → documented USER settings only (note the ORIGINAL
     value, ONE small change at a time), never installer/service menus.
"""
import pytest

from chat import orchestrator as orch
from chat import prompts

pytestmark = pytest.mark.django_db


def _bulk(onset):
    return {"category": None, "subtype": None, "brand": None, "model": None,
            "error_code": None, "alarm_text": None, "onset": onset, "postal_code": None,
            "installer": None, "operating_context": None, "readings": [], "problem": None}


def _drive_to_specialist(conv, mock, onset):
    """Intake → routing → manual specialist (IVT Geo 412C bound), with `onset`
    mined during intake so it's present before the first troubleshooting turn."""
    mock.responses["bulk"] = _bulk(onset)
    mock.responses["specialist"] = {
        "answer_to_customer": "Please read what the display shows and tell me the value.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {"resolved": None}}
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")  # postcode declined
    orch.process_turn(conv, "it suddenly stopped heating this morning, was fine yesterday")
    orch.process_turn(conv, "IVT")
    res = orch.process_turn(conv, "Geo 412C")  # binds → specialist turn 1 (solve → confirm)
    return res


# ── CODE layer: sudden onset clamps the budget to 3 ─────────────────────────

def test_sudden_onset_clamps_budget_to_three(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_specialist(conv, mock_gemini, onset="sudden")
    conv.refresh_from_db()
    assert conv.case_state["slots"]["onset"] == "sudden"
    orch.process_turn(conv, "no")           # troubleshooting turn 2
    res = orch.process_turn(conv, "no")     # turn 3 → forced handoff (budget clamped to 3)
    assert res["state"] == "ESCALATE"
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] == "budget"


def test_gradual_onset_keeps_full_budget(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_specialist(conv, mock_gemini, onset="gradual")
    conv.refresh_from_db()
    assert conv.case_state["slots"]["onset"] == "gradual"
    orch.process_turn(conv, "no")           # turn 2
    res = orch.process_turn(conv, "no")     # turn 3 — still within the budget-5, NOT forced
    assert res["state"] == "SPECIALIST"
    conv.refresh_from_db()
    assert conv.case_state["escalation_reason"] != "budget"


# ── PROMPT layer: ONSET RULES injected with {onset} filled ──────────────────

def test_specialist_prompt_sudden_no_settings_compensation(seeded):
    body = prompts.render("specialist", onset="sudden", previous_checks="")
    assert "onset = sudden" in body                      # placeholder filled
    assert "NEVER suggest changing settings to compensate" in body
    assert "LOOK-ONLY checks" in body


def test_specialist_prompt_comfort_rules_present(seeded):
    body = prompts.render("specialist", onset="always", previous_checks="")
    # documented user comfort settings with the discipline: original value first, one small step
    assert "note the ORIGINAL value FIRST" in body
    assert "ONE small step at a time" in body
    assert "EVALUATE" in body
    # only normal user menus — never installer/service/safety settings
    assert "ONLY normal user menus" in body
    assert "anti-legionella" in body


def test_intelligent_specialist_prompt_has_onset_rules(seeded):
    body = prompts.render("intelligent_specialist", onset="sudden", previous_checks="")
    assert "onset = sudden" in body
    assert "NEVER suggest changing settings to compensate" in body
    assert "ONLY normal user menus" in body
