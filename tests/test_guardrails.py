"""Guardrail backstop tests (plan §6.4)."""
import pytest
from django.core.management import call_command

from chat import guardrails

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def test_keyword_veto_catches_forbidden_classes():
    bad = [
        "You should rewire the compressor terminals",
        "Just top up the refrigerant yourself",
        "Open the electrical panel and replace the heating element",
        "You can re-pressurize the system to 1.5 bar",
        "Adjust the pressure switch a little",
        # disassembly / opening the unit — exceeds the look-only envelope (the
        # prompt-injection target). Must fail closed → escalate.
        "To do this you will need to remove the upper front panel",
        "Take off the cover and check inside",
        "Unscrew the casing to reach the board",
        "Just open up the unit and have a look",
        "You can dismantle the housing yourself",
        "Remove the electrical panel first",
    ]
    for t in bad:
        unsafe, hit = guardrails.keyword_unsafe(t)
        assert unsafe, f"should be unsafe: {t!r}"
        assert hit


def test_keyword_allows_safe_envelope():
    ok = [
        "Note the alarm code shown on the display",
        "Check the breaker hasn't tripped — just look, don't touch",
        "Close the visible stop valve to limit the leak",
        "Make sure the isolation valve is open",   # operating a visible valve is allowed
        "Read the pressure gauge and tell me the number",
    ]
    for t in ok:
        unsafe, _ = guardrails.keyword_unsafe(t)
        assert not unsafe, f"should be safe: {t!r}"


def test_is_unsafe_consults_llm_when_no_keyword(seeded, mock_gemini):
    mock_gemini.responses["safety"] = {"unsafe": True, "reason": "implies pro work"}
    unsafe, reason = guardrails.is_unsafe("do the thing with the unit")
    assert unsafe and reason

    mock_gemini.responses["safety"] = {"unsafe": False, "reason": ""}
    unsafe, _ = guardrails.is_unsafe("read the display code")
    assert not unsafe


def test_keyword_veto_overrides_llm(mock_gemini):
    mock_gemini.responses["safety"] = {"unsafe": False}  # LLM says fine...
    unsafe, _ = guardrails.is_unsafe("rewire the board")  # ...but keyword vetoes
    assert unsafe
