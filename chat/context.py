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


def collect_knowledge(machine, locale: str = "en") -> tuple[str, str]:
    """Return (brand_notes_text, faq_text) for the machine's vendor/category."""
    from kb.models import BrandNote, FAQEntry

    notes = BrandNote.objects.filter(vendor=machine.vendor).filter(
        models_q(machine)
    ) if machine else BrandNote.objects.none()
    brand_notes = "\n".join(n.body for n in notes)

    faq_text = ""
    if machine:
        for faq in FAQEntry.objects.filter(category=machine.category):
            t = faq.text(locale)
            if t:
                faq_text += f"Q: {t.question}\nA: {t.answer}\n"
    return brand_notes, faq_text


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
    name = gemini.create_cache(
        model=MODELS["flash"], contents=parts, ttl_seconds=_CACHE_TTL,
        display_name=f"machine-{machine.pk}",
    )
    django_cache.set(key, name, _CACHE_TTL - 60)
    return name, []
