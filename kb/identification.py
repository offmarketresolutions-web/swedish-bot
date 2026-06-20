"""Machine identification (plan §8) — Postgres pg_trgm fuzzy match over the
catalog. NO embeddings for v1 (the catalog is dozens of SKUs). Identification
ONLY — never answer retrieval.
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


def best_match(query: str):
    """Return (Machine|None, score) for the closest supported machine. Combines
    full-string similarity (good for clean "IVT 490") with word similarity of the
    model string inside the query (good for noisy "...model IVT 490 serial...")."""
    q = (query or "").strip().lower()
    if not q:
        return None, 0.0
    qs = (
        Machine.objects.filter(is_supported=True)
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


def identify_machine(query: str, *, threshold: float = DEFAULT_THRESHOLD):
    """Return (Machine, score) only when confident (score >= threshold); else
    (None, score) so the orchestrator routes to intelligent-intake. A wrong
    manual is worse than none."""
    machine, score = best_match(query)
    if machine and score >= threshold:
        return machine, score
    return None, score
