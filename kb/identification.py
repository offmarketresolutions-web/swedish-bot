"""Machine identification (plan §8) — Postgres pg_trgm fuzzy match over the
catalog, with an optional embedding fallback (V2) when trigram is unsure.
Identification ONLY — never answer retrieval.
"""
from __future__ import annotations

import re

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import F, FloatField, Func, Value
from django.db.models.functions import Greatest

from kb.models import Machine

DEFAULT_THRESHOLD = 0.30  # tuned against real pg_trgm; below this → unsupported


def _norm(s) -> str:
    """Lowercased, non-alphanumerics stripped — for EXACT (identity) matching a
    customer-typed model against the catalog ('Geo 412C' == 'geo412c' == '412 c')."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def exact_machine(query: str, model_text: str = "", *, vendor=None):
    """Return the ONE catalog Machine whose model_name / vendor+model_name / an alias
    matches the customer text exactly after normalization, else None. This is the only
    fast-path allowed to auto-bind (plan S3 no-auto-bind): a partial like 'Geo 600' does
    NOT normalize-equal 'Geo 600C', so it never silently binds an unconfirmed unit."""
    keys = {k for k in (_norm(query), _norm(model_text)) if k}
    if not keys:
        return None
    base = Machine.objects.filter(is_supported=True).select_related("vendor")
    if vendor is not None:
        base = base.filter(vendor=vendor)
    for m in base:
        names = {_norm(m.model_name), _norm((m.vendor.name if m.vendor_id else "") + m.model_name)}
        names |= {_norm(a) for a in (m.aliases or [])}
        names.discard("")
        if keys & names:
            return m
    return None


def machine_named_in(text: str, *, vendor=None, max_words: int = 4):
    """(Machine, the exact span of `text` that named it), or None if nothing matched.

    The span is returned rather than just the machine because the caller stores the
    CUSTOMER's wording, not the catalog's: the seeded name for one unit is literally
    "Bosch Compress 7000i", and rewriting a customer who typed "Compress 7000i" into that
    would be a downgrade, not a repair.

    exact_machine() compares the WHOLE reply, so it only fires when the customer typed
    nothing but the model. The per-slot extractor, though, narrows "AirX 500" to "500" —
    it reads "AirX" as the series and keeps the number — and "IVT 500" then trigram-matches
    Aero 500 / Geo 500C / Geo 500E / AirX 500 equally well, so a customer who typed the
    exact chip we had just offered was asked to disambiguate against a list containing
    their own answer (seen live in production, 2026-09-13).

    Scanning windows of the raw reply also catches the model inside a sentence ("it's an
    AirX 500"). Longest window first, so "AirX 500" wins over a bare "500" alias, and a
    window matching two machines is ignored rather than guessed at.
    """
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    if not words:
        return None
    base = Machine.objects.filter(is_supported=True)
    if vendor is not None:
        base = base.filter(vendor=vendor)
    by_name: dict[str, set[int]] = {}
    machines = {}
    for m in base:
        machines[m.id] = m
        # Model-level names ONLY. exact_machine() also indexes vendor+model so it can match
        # a whole reply like "IVT Geo 412C", but the span returned here is what gets STORED
        # in slots.model — and matching that composite put the brand in the model slot
        # ("IVT Geo 412C"), which is the brand slot's job.
        names = {_norm(m.model_name)} | {_norm(a) for a in (m.aliases or [])}
        names.discard("")
        for n in names:
            by_name.setdefault(n, set()).add(m.id)
    for size in range(min(max_words, len(words)), 0, -1):
        for i in range(len(words) - size + 1):
            span = words[i:i + size]
            ids = by_name.get(_norm("".join(span)))
            if ids and len(ids) == 1:
                return machines[next(iter(ids))], " ".join(span)
    return None


def candidate_matches(query: str, *, vendor=None, category_ids=None,
                      threshold: float = DEFAULT_THRESHOLD, limit: int = 4):
    """Return up to `limit` (Machine, score) plausible matches at/above `threshold`,
    best first — the ambiguity set offered to the customer as chips ('Geo 600' ->
    [Geo 600C, Geo 600E]). Retrieval ONLY; the orchestrator owns the bind policy.
    `category_ids` narrows to the stated sub-type/family (same as suggest_models): without
    it, "IVT 600-serien" trigram-matched IVT 490 / IVT 402 (exhaust-air) on the shared
    vendor token and the customer was offered the wrong family (run100 V036 + 5 more)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    base = Machine.objects.filter(is_supported=True)
    if vendor is not None:
        base = base.filter(vendor=vendor)
    if category_ids:
        base = base.filter(category_id__in=category_ids)
    qs = (base.annotate(sim=Greatest(TrigramSimilarity("search_text", q),
                                     _WordSimilarity(F("search_text"), Value(q))))
          .filter(sim__gte=threshold).order_by("-sim").select_related("vendor"))
    return [(m, float(m.sim or 0.0)) for m in qs[:limit]]


def suggest_models(query: str, *, vendor=None, category_ids=None, limit: int = 5,
                   floor: float = 0.15):
    """Free-text model search over the FULL supported catalog — including manual-less
    machines (unlike the chip suggestions, which require a loaded manual). Returns up to
    `limit` (Machine, score) above `floor`, best first, optionally scoped to a vendor and
    a set of categories (subtype narrowing)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    base = Machine.objects.filter(is_supported=True)
    if vendor is not None:
        base = base.filter(vendor=vendor)
    if category_ids:
        base = base.filter(category_id__in=category_ids)
    qs = (base.annotate(sim=Greatest(TrigramSimilarity("search_text", q),
                                     _WordSimilarity(F("search_text"), Value(q))))
          .filter(sim__gte=floor).order_by("-sim").select_related("vendor"))
    return [(m, float(m.sim or 0.0)) for m in qs[:limit]]


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
