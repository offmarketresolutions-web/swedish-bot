"""Specialist knowledge context (plan §8): brand notes + FAQ (small, fresh each
turn) and the full machine PDF(s) served from a Gemini context cache (or inlined
when below the cache token floor). Cache holds ONLY the PDFs so prompt/notes/FAQ
edits take effect immediately (resolves crit 0.4)."""
from __future__ import annotations

import hashlib

from django.core.cache import cache as django_cache

from core.constants import CACHE_MIN_TOKENS, MODELS
from core.services import gemini

_CACHE_TTL = 3600


_NOTES_CAP = 2000  # so notes never crowd out the manual (crit 1.9)


def collect_knowledge(machine, locale: str = "en", *, query: str = "") -> tuple[str, str]:
    """Return (notes_text, faq_text) for the machine. Per-machine notes precede
    vendor/category brand notes; both are wrapped as untrusted reference DATA (S8)
    and length-capped so the manual stays the dominant source. When `query` (the
    problem text) is given and semantic search is on, the most relevant FAQ/guide
    snippets across the KB are appended (V2 embedding retrieval)."""
    from chat.sanitize import cap, wrap_untrusted
    from kb.models import BrandNote, FAQEntry, GenericGuide, MachineNote

    parts: list[str] = []
    if machine:
        if machine.vendor.agent_notes:  # per-vendor guidance (V2 P-C)
            parts.append(machine.vendor.agent_notes)
        parts += [n.body for n in MachineNote.objects.filter(machine=machine)]
        parts += [n.body for n in BrandNote.objects.filter(vendor=machine.vendor).filter(models_q(machine))]
    raw = cap("\n".join(p for p in parts if p), _NOTES_CAP)
    notes_text = wrap_untrusted(raw, "internal_notes") if raw else ""

    # FAQ/guide injection is configurable per the specialist AgentPrompt (V2): a
    # toggle to inject at all, and an optional set of categories to inject from
    # (empty = the matched machine's own category, the original behaviour).
    from chat import prompts
    cfg = prompts.config_for("specialist")
    faq_text = ""
    if cfg.get("inject_faq", True) and machine:
        cat_ids = cfg.get("faq_category_ids") or ([machine.category_id] if machine.category_id else [])
        for faq in FAQEntry.objects.filter(category_id__in=cat_ids, is_approved=True):
            t = faq.text(locale)
            if t:
                faq_text += f"Q: {t.question}\nA: {t.answer}\n"
        # best-practice / generic guides for these categories (V2 P-D), capped.
        for g in GenericGuide.objects.filter(category_id__in=cat_ids, lang__in=[locale, "en"]).exclude(kind="faq"):
            faq_text += f"[{g.kind}] {g.body}\n"
        # Semantic retrieval (V2): the most relevant guidance for THIS problem, across
        # categories. Fail-safe + flag-gated inside rank_guides.
        if query:
            from kb import semantic
            for text, _score in semantic.rank_guides(query, locale=locale):
                if text not in faq_text:
                    faq_text += text + "\n"
    return notes_text, cap(faq_text, 1500)


def models_q(machine):
    from django.db.models import Q

    return Q(category=machine.category) | Q(category__isnull=True)


def _docset_hash(docs) -> str:
    h = hashlib.sha256()
    for d in docs:
        h.update((d.sha256 or str(d.pk)).encode())
    return h.hexdigest()[:16]


def machine_pdf_context(machine, locale: str = "en"):
    """Return (cached_content_name|None, inline_parts list). Reuses a cached
    content per machine docset (keyed by docset hash) across turns and sessions.
    Below the token floor, inline the PDFs instead (no cache)."""
    docs = list(machine.documents.all()) if machine else []
    if not docs:
        return None, []

    total_tokens = sum(d.token_estimate or 0 for d in docs)
    parts = [gemini.file_part(d.pdf.path) for d in docs if d.pdf]
    if not parts:
        return None, []

    if total_tokens < CACHE_MIN_TOKENS:
        return None, parts  # inline small docs (plan §8 cache-floor fallback)

    key = f"machinecache:{machine.pk}:{_docset_hash(docs)}:{locale}"
    cached = django_cache.get(key)
    if cached:
        return cached, []
    try:
        name = gemini.create_cache(
            model=MODELS["flash"], contents=parts, ttl_seconds=_CACHE_TTL,
            display_name=f"machine-{machine.pk}",
        )
    except Exception:  # noqa: BLE001 — caching unavailable / docset under provider floor
        return None, parts  # fall back to inline; never block an answer on caching
    django_cache.set(key, name, _CACHE_TTL - 60)
    return name, []
