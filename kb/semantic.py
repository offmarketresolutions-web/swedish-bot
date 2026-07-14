"""Embedding-backed semantic search (V2) — an AUGMENTATION, never the primary path.

  • machine identification: a fallback when pg_trgm is unsure (handles paraphrases,
    typos, and cross-lingual queries trigram misses);
  • FAQ/guide retrieval: surface the most relevant guidance for the problem text.

Trigram + full-PDF-in-context stay primary and reliable. This module fails safe
(any embedding error → empty result, so the caller keeps the trigram answer) and
is gated by settings.SEMANTIC_SEARCH_ENABLED.

The catalog/guide corpora are small (dozens of rows), so vectors are embedded once
and cached in the Django cache — keyed by a content hash that self-invalidates on
edit — and scored with in-memory cosine. No pgvector needed at this scale; this
module is the seam to swap it in if the catalog ever grows past a few thousand rows.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re

from django.conf import settings
from django.core.cache import cache as django_cache

from core import constants
from core.services import gemini

logger = logging.getLogger(__name__)

_CACHE_TTL = 3600
SEM_IDENTIFY_THRESHOLD = 0.78  # min cosine to claim a machine via embeddings
# A semantic identification is the trigram-MISSED (less certain) path, so it is
# reported as a deliberately conservative confidence — NOT the raw cosine — so the
# specialist's downstream gates (thinking-on at <0.7) still fire and the model must
# confirm from the manual. (Review finding: a raw cosine ≥0.78 was masquerading as
# high trigram confidence and skipping those gates.)
SEMANTIC_MATCH_CONFIDENCE = 0.65


def enabled() -> bool:
    return bool(getattr(settings, "SEMANTIC_SEARCH_ENABLED", False))


def _cos(a, b) -> float:
    if len(a) != len(b):  # dimension mismatch (e.g. model/dim change) -> fail safe
        return 0.0
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _corpus_vectors(prefix: str, items: list[tuple]):
    """items: list of (id, text) -> dict {id: vector}, cached + content-hashed so it
    self-invalidates whenever the corpus text (or the embedding model/dim) changes."""
    if not items:
        return {}
    h = hashlib.sha256()
    for _id, text in items:
        h.update(f"{_id}\x1f{text}".encode("utf-8"))
    # Bind the cache entry to the embedding space so query/corpus vectors can never
    # be compared across different model or dimensionality.
    key = f"{prefix}:{gemini.active_embedding_model()}:{constants.EMBED_DIM}:{h.hexdigest()[:16]}"
    cached = django_cache.get(key)
    if cached is not None:
        return cached
    vecs = gemini.embed([t for _, t in items], task_type="RETRIEVAL_DOCUMENT")
    out = {items[i][0]: vecs[i] for i in range(len(items))}
    django_cache.set(key, out, _CACHE_TTL)
    return out


def semantic_identify(query: str, *, vendor=None):
    """Return (Machine, cosine) best-by-embedding, or (None, 0.0). Conservative —
    the caller should only claim a machine when cosine >= SEM_IDENTIFY_THRESHOLD."""
    if not enabled() or not (query or "").strip():
        return None, 0.0
    from kb.models import Machine

    base = Machine.objects.filter(is_supported=True)
    if vendor is not None:
        base = base.filter(vendor=vendor)
    rows = [(m.pk, m.search_text or f"{m.vendor.name} {m.model_name}") for m in base]
    if not rows:
        return None, 0.0
    try:
        qv = gemini.embed(query, task_type="RETRIEVAL_QUERY")
        vecs = _corpus_vectors(f"sem:machines:{getattr(vendor, 'pk', 'all')}", rows)
    except Exception:  # noqa: BLE001 — never break identification on an embedding error
        logger.warning("semantic_identify failed; trigram-only", exc_info=True)
        return None, 0.0

    best_id, best = None, 0.0
    for mid, v in vecs.items():
        s = _cos(qv, v)
        if s > best:
            best_id, best = mid, s
    if best_id is None:
        return None, 0.0
    machine = Machine.objects.filter(pk=best_id).first()  # fail-safe vs a concurrent delete
    return (machine, best) if machine else (None, 0.0)


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9åäö]+", (s or "").lower())


def _onset_match(entry_onset: str, want: str) -> bool:
    """FAQ onset_type vocab is any|sudden|long_term; case onset is sudden|gradual|always.
    Empty / 'any' entry applies to all. 'sudden'->'sudden'; 'gradual'/'always'->'long_term'."""
    ot = (entry_onset or "").strip().lower()
    if not ot or ot == "any" or not want:
        return True
    if ot == "sudden":
        return want == "sudden"
    if ot == "long_term":
        return want in ("gradual", "always")
    return True


def rank_general_knowledge(query: str, *, category_ids=None, subtype=None, onset=None,
                           manufacturer=None, locale: str = "en", top_k: int = 3):
    """Return up to top_k (FAQEntry, score) approved general-knowledge entries relevant to
    the case, filtered by category family + applicable_subtypes + onset (+ manufacturer,
    incl. brand-agnostic entries). Semantic cosine when enabled; else a deterministic
    keyword-overlap fallback so retrieval never silently vanishes when embeddings are off."""
    from django.db.models import Q

    from kb.models import FAQEntry

    qs = FAQEntry.objects.filter(is_approved=True)
    if category_ids:
        qs = qs.filter(category_id__in=category_ids)
    if manufacturer is not None:
        qs = qs.filter(Q(manufacturer=manufacturer) | Q(manufacturer__isnull=True))

    rows: list[tuple] = []  # (FAQEntry, blob)
    for fa in qs.select_related("manufacturer"):
        subs = fa.applicable_subtypes or []
        if subtype and subs and subtype not in subs:
            continue  # narrowed to sub-types that exclude this one
        if not _onset_match(fa.onset_type, onset):
            continue
        txt = fa.text(locale)
        if not txt:
            continue
        blob = f"{txt.question} {txt.answer} {' '.join(str(k) for k in (fa.keywords or []))}"
        rows.append((fa, blob))
    if not rows:
        return []

    q = (query or "").strip()
    if not enabled() or not q:
        # Deterministic keyword-overlap fallback (offline path).
        qtok = set(_tok(q))
        if not qtok:
            return []
        scored = sorted(((len(qtok & set(_tok(blob))), fa) for fa, blob in rows),
                        key=lambda x: x[0], reverse=True)
        return [(fa, float(n)) for n, fa in scored[:top_k] if n > 0]

    try:
        qv = gemini.embed(q, task_type="RETRIEVAL_QUERY")
        vecs = _corpus_vectors("sem:genknow", [(f"f{fa.pk}", blob) for fa, blob in rows])
    except Exception:  # noqa: BLE001
        logger.warning("rank_general_knowledge failed", exc_info=True)
        return []
    fa_by_id = {f"f{fa.pk}": fa for fa, _ in rows}
    scored = sorted(((_cos(qv, v), gid) for gid, v in vecs.items()), reverse=True)
    return [(fa_by_id[gid], s) for s, gid in scored[:top_k] if gid in fa_by_id]


def rank_guides(query: str, *, locale: str = "en", top_k: int = 3):
    """Return up to top_k (text, cosine) FAQ/guide snippets most relevant to the
    query, across categories. Empty on disabled / no corpus / error (fail-safe)."""
    if not enabled() or not (query or "").strip():
        return []
    from kb.models import FAQEntry, GenericGuide, SiteFAQ

    rows: list[tuple] = []
    for g in GenericGuide.objects.filter(lang__in=[locale, "en"]):
        rows.append((f"g{g.pk}", f"[{g.kind}] {g.body}"))
    for fa in FAQEntry.objects.filter(is_approved=True):
        t = fa.text(locale)
        if t:
            rows.append((f"f{fa.pk}", f"Q: {t.question}\nA: {t.answer}"))
    for s in SiteFAQ.objects.filter(is_active=True, is_approved=True):
        rows.append((f"s{s.pk}", f"Q: {s.question}\nA: {s.answer}"))
    if not rows:
        return []
    try:
        qv = gemini.embed(query, task_type="RETRIEVAL_QUERY")
        vecs = _corpus_vectors("sem:guides", rows)
    except Exception:  # noqa: BLE001
        logger.warning("rank_guides failed", exc_info=True)
        return []
    text_by_id = dict(rows)
    scored = sorted(((_cos(qv, v), gid) for gid, v in vecs.items()), reverse=True)
    return [(text_by_id[gid], s) for s, gid in scored[:top_k]]
