"""Consent parsing: a chip posts its VALUE not its label, and a "yes" can be withdrawn.

The bug this exists to stop: the post-fix details offer emits a chip whose value is
"yes_save". `_is_yes` special-cased only "yes_send" and otherwise matched affirmative
WORDS, and "_" is a word character, so `\\byes\\b` never matches inside "yes_save". Tapping
"Ja" was therefore read as a refusal and the entire post-solve contact capture — the
feature that says "en av våra specialister går igenom ärendet" — silently never ran.

Typing "ja" worked. Tapping the button did not. Nothing failed loudly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from chat.orchestrator import _AFFIRM_CHIP_VALUES, _is_yes

pytestmark = pytest.mark.django_db

SRC = [Path("chat/orchestrator.py"), Path("chat/intake.py")]


def emitted_chip_values() -> set[str]:
    """Every literal chip value the code can post back to itself."""
    found: set[str] = set()
    for path in SRC:
        found |= set(re.findall(r'"value":\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    return found


def test_every_affirmative_chip_value_is_understood_as_yes():
    for value in sorted(_AFFIRM_CHIP_VALUES):
        assert _is_yes(value), (
            f"chip value {value!r} is listed as affirmative but _is_yes() rejects it")


def test_no_affirmative_chip_is_emitted_that_is_not_listed():
    """The guard that would have caught the original bug: a new yes-chip added to the UI
    without being taught to _is_yes."""
    suspicious = {v for v in emitted_chip_values()
                  if v.startswith("yes") or v in {"confirm", "ok", "send"}}
    unlisted = suspicious - set(_AFFIRM_CHIP_VALUES)
    assert not unlisted, (
        f"these chip values look affirmative but _is_yes() will not accept them: {unlisted}. "
        "Add them to _AFFIRM_CHIP_VALUES or the button will read as a refusal.")


def test_negative_chip_values_are_not_yes():
    for value in ("no", "no_save", "not_yet", "none_of_these", "unknown"):
        assert not _is_yes(value), f"chip value {value!r} must not read as consent"


def test_a_chip_value_is_not_matched_loosely():
    """Guard against 'fix' by substring: "yes_but_no" or "yesterday" must not be consent."""
    for value in ("yesterday", "yes_but_not_now", "noyes"):
        assert not _is_yes(value), f"{value!r} must not be treated as an affirmative chip"


# ── consent has to be what the customer meant, not their first word ──────────

@pytest.mark.parametrize("text", [
    "ja", "yes", "ja skicka", "ja men gärna", "ok", "absolutely",
    # The case the first-clause rule was built for (run100 X002): consent plus a factual
    # correction. The negation belongs to the correction, not to the consent.
    "Ja, skicka till Nordland. Men det är en IVT, inte Bosch.",
])
def test_real_consent_is_accepted(text):
    assert _is_yes(text), f"{text!r} is consent and must be read as such"


@pytest.mark.parametrize("text", [
    # These used to dispatch a lead AND write consent_to_contact=True. The customer said no.
    "ja men skicka inte",
    "ja, men inte än",
    "ja fast vänta",
    "yes but do not send it",
    "ja men hör av er senare",
    # Plain refusals.
    "nej", "not yet", "skicka inte",
])
def test_a_withdrawn_yes_is_a_refusal(text):
    assert not _is_yes(text), (
        f"{text!r} withdraws the consent it opens with — dispatching on this sends a lead "
        "and records consent for someone who declined")
