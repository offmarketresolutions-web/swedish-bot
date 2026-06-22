"""Machine identification (plan §8) — Postgres pg_trgm fuzzy match over the
catalog, with an optional embedding fallback (V2) when trigram is unsure.
Identification ONLY — never answer retrieval.
"""
from __future__ import annotations

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import F, FloatField, Func, Value
from django.db.models.functions import Greatest

from kb.models import Machine

DEFAULT_THRESHOLD = 0.30  # tuned against real pg_trgm; below this → unsupported


class _WordSimilarity(Func):
    """pg_trgm word_similarity(pattern, haystack): how well the (short) model
    string matches a contiguous run inside a (possibly long, noisy) query —
    the right direction for nameplate-OCR / free-text identification."""

    function = "WORD_SIMILARITY"
    output_field = FloatField()


def best_match(query: str, *, vendor=None):
    """Return (Machine|None, score) for the closest supported machine. Combines
    full-string similarity (good for clean "IVT 490") with word similarity of the
    model string inside the query (good for noisy "...model IVT 490 serial...").
    When `vendor` is given, candidates are scoped to that vendor (V2 P-C) — this
    raises scores for short model codes (e.g. PHR-N) once the brand is known."""
    q = (query or "").strip().lower()
    if not q:
        return None, 0.0
    base = Machine.objects.filter(is_supported=True)
    if vendor is not None:
        base = base.filter(vendor=vendor)
    qs = (
        base
        .annotate(
            sim=Greatest(
                TrigramSimilarity("search_text", q),
                _WordSimilarity(F("search_text"), Value(q)),
            )
        )
        .order_by("-sim")
    )
    top = qs.first()
    if not top:
        return None, 0.0
    return top, float(top.sim or 0.0)


def identify_machine(query: str, *, threshold: float = DEFAULT_THRESHOLD, vendor=None):
    """Return (Machine, score) only when confident (score >= threshold); else
    (None, score) so the orchestrator routes to intelligent-intake. A wrong
    manual is worse than none. Pass `vendor` to scope to a known brand."""
    machine, score = best_match(query, vendor=vendor)
    if machine and score >= threshold:
        return machine, score
    # Trigram unsure → embedding fallback (V2, gated + fail-safe). A wrong manual is
    # worse than none, so only claim on a high semantic cosine.
    from kb import semantic

    if semantic.enabled():
        sm, scos = semantic.semantic_identify(query, vendor=vendor)
        if sm and scos >= semantic.SEM_IDENTIFY_THRESHOLD:
            # Report a conservative, trigram-comparable confidence (NOT the raw
            # cosine) so the specialist's low-confidence safety gates still fire on
            # this less-certain path.
            return sm, semantic.SEMANTIC_MATCH_CONFIDENCE
    return None, score
