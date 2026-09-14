"""The rewrite must simplify the WORDING and never the ADVICE.

These answers tell customers what they may and may not touch. A rewrite that turns
"använd endast om manualen beskriver det" into "använd knappen" is worse than the
officialese it replaced, so check_rewrite() is the gate everything passes through.
"""
from __future__ import annotations

import pytest

from kb.management.commands.simplify_faq_language import (
    check_rewrite,
    long_words,
    needs_simplifying,
    qualifiers,
    verdict,
)

pytestmark = pytest.mark.django_db


ORIGINAL = ("Byt båda batterierna, kontrollera polariteten och rikta fjärrkontrollen mot "
            "mottagaren. Använd eventuell nöddrift endast om exakt manual beskriver den.")


def test_a_genuine_simplification_is_accepted():
    simpler = ("Byt båda batterierna. Kontrollera att de sitter åt rätt håll. Rikta "
               "fjärrkontrollen mot mottagaren. Använd nöddrift endast om din manual "
               "beskriver den.")
    assert check_rewrite(ORIGINAL, simpler) is None


def test_dropping_a_safety_condition_is_rejected():
    """The one failure that matters: "endast om manualen beskriver den" becomes a plain
    instruction, which tells the customer to do something the original forbade."""
    unsafe = ("Byt båda batterierna. Kontrollera att de sitter åt rätt håll. Rikta "
              "fjärrkontrollen mot mottagaren. Använd nöddrift.")
    reason = check_rewrite(ORIGINAL, unsafe)
    assert reason and "restriction" in reason, reason


def test_dropping_a_negation_is_rejected():
    original = "Rör inte kompressorn. Kontakta en tekniker."
    assert check_rewrite(original, "Rör kompressorn. Kontakta en tekniker.") is not None


def test_an_answer_that_grew_into_something_else_is_rejected():
    """A rewrite far longer than the original has invented steps rather than simplified."""
    padded = ORIGINAL + " " + ("Du kan också öppna panelen och kontrollera kablarna, "
                               "mäta spänningen, justera tryckvakten och rengöra "
                               "kretskortet med sprit om det behövs. " * 3)
    assert check_rewrite(ORIGINAL, padded) is not None


def test_an_empty_or_truncated_rewrite_is_rejected():
    assert check_rewrite(ORIGINAL, "") is not None
    assert check_rewrite(ORIGINAL, "Byt batterier") is not None


def test_a_rewrite_that_introduces_forbidden_work_is_rejected():
    """Even with every qualifier intact, the deterministic forbidden-term scan still runs —
    the rewrite must not invent professional-only work."""
    original = "Kontrollera att strömmen är på. Kontakta tekniker om felet kvarstår."
    invented = ("Kontrollera att strömmen är på. Öppna elpanelen och koppla om kablarna. "
                "Kontakta tekniker om felet kvarstår.")
    reason = check_rewrite(original, invented)
    assert reason is not None, "a rewrite that adds electrical work must be rejected"


def test_qualifier_and_long_word_helpers():
    assert qualifiers("Använd endast om manualen beskriver det") == 1
    assert qualifiers("Rör inte enheten") == 1
    # Plain Swedish can carry the same restriction a different way — that must count.
    assert qualifiers("Låt en tekniker öppna luckan") == 1
    assert qualifiers("Byt batteriet.") == 0
    assert long_words("garanti- och reklamationsbedömning av installationer") >= 1
    assert long_words("Byt batteriet. Det är enkelt.") == 0


# ── quota handling ───────────────────────────────────────────────────────────
# A 429 is not a verdict on the answer. Counting the two together reported
# "kept original 78" on a run where only 7 answers were actually judged unsafe.

class _Resp:
    def __init__(self, text):
        self.text = text


def _command(monkeypatch, sleeps):
    from kb.management.commands.simplify_faq_language import Command

    monkeypatch.setattr("kb.management.commands.simplify_faq_language.time.sleep",
                        lambda s: sleeps.append(s))
    return Command()


def test_a_quota_refusal_is_retried_then_succeeds(monkeypatch):
    sleeps, calls = [], []

    class Gem:
        def generate(self, *a, **k):
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("429 RESOURCE_EXHAUSTED. Resource exhausted.")
            return _Resp("Byt batteriet. Det tar en minut.")

    text, err = _command(monkeypatch, sleeps)._rewrite(Gem(), "x" * 40, retries=4, sleep_s=0)
    assert err is None and text.startswith("Byt batteriet")
    assert len(calls) == 3, "it should have retried twice before succeeding"
    assert sleeps and sleeps[0] < sleeps[-1], "the backoff must grow"


def test_a_persistent_quota_refusal_is_reported_not_silently_kept(monkeypatch):
    class Gem:
        def generate(self, *a, **k):
            raise RuntimeError("429 RESOURCE_EXHAUSTED. Resource exhausted.")

    text, err = _command(monkeypatch, [])._rewrite(Gem(), "x" * 40, retries=2, sleep_s=0)
    assert text is None
    assert "429" in err, err


def test_a_non_quota_error_is_not_retried(monkeypatch):
    calls = []

    class Gem:
        def generate(self, *a, **k):
            calls.append(1)
            raise RuntimeError("400 INVALID_ARGUMENT")

    text, err = _command(monkeypatch, [])._rewrite(Gem(), "x" * 40, retries=4, sleep_s=0)
    assert text is None and "400" in err
    assert len(calls) == 1, "a permanent error must not burn the retry budget"


# ── the verdict is the answer ────────────────────────────────────────────────

def test_flipping_yes_to_no_is_rejected():
    """The one that reached production: "Ja. Kontrollera att den inte står i AUTO…" came
    back as "Nej. Kontrollera att den inte står i…". Same restriction count, every other
    check passed, and the answer now said the opposite thing."""
    original = ("Ja. Kontrollera att den inte står i AUTO, DRY, kyla, nattläge, eco eller "
                "timer. För felsökning av värme ska HEAT-läge användas.")
    flipped = ("Nej. Kontrollera att den inte står i AUTO, DRY, kyla, nattläge, eco eller "
               "timer. Använd HEAT-läget.")
    reason = check_rewrite(original, flipped)
    assert reason and "verdict" in reason, reason


def test_dropping_the_verdict_entirely_is_rejected():
    original = "Ja. Byt batterierna och rikta fjärrkontrollen mot mottagaren."
    assert check_rewrite(original, "Byt batterierna. Rikta den mot mottagaren igen.") is not None


def test_keeping_the_verdict_is_accepted():
    original = ("Ja. Kontrollera att den inte står i AUTO, DRY, kyla, nattläge, eco eller "
                "timer. För felsökning av värme ska HEAT-läge användas.")
    kept = ("Ja. Kontrollera att den inte står i AUTO, DRY, kyla, nattläge, eco eller timer. "
            "Använd HEAT-läget när du felsöker värmen.")
    assert check_rewrite(original, kept) is None


def test_verdict_only_matches_a_whole_word():
    assert verdict("Japp, det går bra") is None, "'Japp' is not a verdict"
    assert verdict("Ja. Byt filtret.") == "ja"
    assert verdict("Kontrollera filtret") is None


# ── re-running must not rewrite its own output ───────────────────────────────

def test_already_plain_answers_are_left_alone():
    """Without this the command had no memory of its own work: a second pass rewrote 78
    answers it had already simplified, each a rewrite of a rewrite."""
    plain = "Byt batteriet. Rikta fjärrkontrollen mot mottagaren. Kolla filtret."
    assert not needs_simplifying(plain)


def test_officialese_is_still_picked_up():
    compound = "Vi gör en garanti- och reklamationsbedömning av installationerna."
    assert needs_simplifying(compound), "a 14+ character compound must be simplified"

    long_sentence = ("Kontrollera att strömmen är på och att inga säkringar har löst ut samt "
                     "att huvudbrytaren står i rätt läge innan du går vidare med felsökningen.")
    assert needs_simplifying(long_sentence), "a 20-word sentence must be simplified"


# ── numbers and steps are load-bearing ───────────────────────────────────────

def test_changing_a_number_is_rejected():
    """A temperature, a pressure, a wait time. "sänk till 21 grader" must not come back
    as "sänk till 12 grader" just because the digits got re-typed."""
    original = "Sänk framledningen till 21 grader och vänta 30 minuter innan du mäter igen."
    changed = "Sänk framledningen till 12 grader. Vänta 30 minuter. Mät sedan igen."
    reason = check_rewrite(original, changed)
    assert reason and "21" in reason, reason


def test_inventing_a_number_is_rejected():
    original = "Kontrollera att strömmen är på och att inga säkringar har löst ut i skåpet."
    invented = "Kontrollera att strömmen är på. Vänta 15 minuter. Kolla att inga säkringar löst ut."
    reason = check_rewrite(original, invented)
    assert reason and "15" in reason, reason


def test_keeping_every_number_is_accepted():
    original = "Sänk framledningen till 21 grader och vänta 30 minuter innan du mäter igen."
    kept = "Sänk framledningen till 21 grader. Vänta 30 minuter. Mät sedan igen."
    assert check_rewrite(original, kept) is None


def test_a_rewrite_that_drops_half_the_answer_is_rejected():
    """The prompt says "never remove a step" and nothing verified it — the length check
    only ever looked at growth.

    Deliberately free of restriction words and numbers, so the ONLY thing separating these
    two is how much of the answer survived. A first version of this test used an example
    that also dropped an "inga", and passed on the earlier restriction gate instead.
    """
    original = ("Kontrollera att strömmen är på. Kontrollera att huvudbrytaren står rätt. "
                "Kontrollera att displayen lyser. Kontrollera att fläkten snurrar. "
                "Kontrollera att filtret sitter som det ska och att luften kommer fram.")
    gutted = "Kontrollera att strömmen är på och att filtret sitter rätt."
    assert qualifiers(original) == qualifiers(gutted) == 0, "this case must isolate length"
    reason = check_rewrite(original, gutted)
    assert reason and "shorter" in reason, reason
