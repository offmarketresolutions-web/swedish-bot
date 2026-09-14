"""Specialist knowledge context (plan §8): brand notes + FAQ (small, fresh each
turn) and the full machine PDF(s) served from a Gemini context cache (or inlined
when below the cache token floor). Cache holds ONLY the PDFs so prompt/notes/FAQ
edits take effect immediately (resolves crit 0.4)."""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache as django_cache

from core.constants import CACHE_MIN_TOKENS, MODELS
from core.services import gemini

logger = logging.getLogger(__name__)

# Stored in place of a cache name when the provider refused this docset, so the next turn
# inlines immediately instead of paying the same doomed upload again.
_CACHE_REFUSED = "__refused__"

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
        # Prefer the requested locale but fall back to ANY language the guide has a row
        # in, rather than dropping Swedish-only content for English conversations
        # (mirrors FAQEntry.text()/pick_text's en-fallback, generalized to any lang).
        by_key: dict[tuple, GenericGuide] = {}
        for g in GenericGuide.objects.filter(category_id__in=cat_ids).exclude(kind="faq"):
            gkey = (g.category_id, g.key)
            existing = by_key.get(gkey)
            if existing is None or (existing.lang != locale and g.lang == locale):
                by_key[gkey] = g
        for g in by_key.values():
            faq_text += f"[{g.kind}] {g.body}\n"
        # Semantic retrieval (V2): the most relevant guidance for THIS problem, across
        # categories. Fail-safe + flag-gated inside rank_guides.
        if query:
            from kb import semantic
            for text, _score in semantic.rank_guides(query, locale=locale):
                if text not in faq_text:
                    faq_text += text + "\n"
    return notes_text, cap(faq_text, 1500)


def collect_general_knowledge(cs, locale: str = "en", *, machine=None) -> str:
    """Approved, category-level general knowledge for THIS case — the 'retrieval before
    manual' layer (plan D2). Scoped per kb.corpus's role -> corpus registry (S10): the
    agent role is derived independently for retrieval purposes (kb.corpus.role_for_case,
    mirroring chat.orchestrator's own role resolution) so every specialist ranks against
    only the corpus its role is declared suitable for. Filtered further by the stated leaf
    sub-type + onset (+ the machine's manufacturer when known), approved-only. Ranked
    semantically when enabled (persisted vectors preferred, kb.corpus/build_embeddings),
    else by a deterministic keyword-overlap fallback so retrieval never silently vanishes.
    Each injected snippet carries a stable [K<pk>] citation tag so the specialist can cite
    which entry backed a claim."""
    from chat.sanitize import cap, wrap_untrusted
    from kb import corpus, semantic

    role = corpus.role_for_case(cs, machine)
    scope = corpus.get_corpus_for_role(role)
    if not scope.included:
        return ""  # e.g. intelligent_intake — no matched machine/category to scope to

    if role == "specialist" and machine is not None:
        # Manual mode: scope dynamically to the bound machine's own category, not a
        # fixed family (BrandNote/MachineNote already cover the vendor separately).
        cat_ids = corpus.family_ids_for_category(machine.category) if machine.category_id else None
        if not cat_ids and machine.category_id:
            cat_ids = [machine.category_id]
    elif scope.category_family:
        cat_ids = corpus.family_ids(scope.category_family)
    else:
        cat_ids = None  # intelligent_specialist: rank across all approved knowledge

    slots = cs.get("slots", {})
    manufacturer = machine.vendor if (machine and machine.vendor_id) else None
    entries = semantic.rank_general_knowledge(
        slots.get("problem") or "", category_ids=cat_ids, subtype=slots.get("subtype"),
        onset=slots.get("onset"), manufacturer=manufacturer, locale=locale, top_k=3,
        scope=role)
    parts: list[str] = []
    for fa, _score in entries:
        txt = fa.text(locale)
        if not txt:
            continue
        block = f"[K{fa.pk}] Q: {txt.question}\nA: {txt.answer}"
        if fa.safe_customer_checks:
            block += f"\nSafe customer checks: {fa.safe_customer_checks}"
        if fa.service_trigger:
            block += f"\nWhen to book a technician: {fa.service_trigger}"
        parts.append(block)
    raw = "\n\n".join(parts)
    return wrap_untrusted(cap(raw, 1500), "general_knowledge") if raw else ""


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
        # S1 loaded some manuals as TEXT only (no PDF) — IVT Geo 412C / Vent 402 /
        # Greenline HE. Fall back to the parsed_text so a text-only manual still reaches
        # the specialist instead of the machine silently losing its documentation.
        from chat.sanitize import cap, wrap_untrusted
        texts = [d.parsed_text for d in docs if (d.parsed_text or "").strip()]
        if texts:
            return None, [wrap_untrusted(cap("\n\n".join(texts), 12000), "manual")]
        return None, []

    if total_tokens < CACHE_MIN_TOKENS:
        return None, parts  # inline small docs (plan §8 cache-floor fallback)

    # Vertex counts an INLINE binary part as 1 token, so a docset of manuals is "1 token"
    # to the cache endpoint and lands under its 1024 floor. Measured: the upload takes 15.2s
    # and then 400s, every time — 40% of a specialist turn spent on work that is thrown
    # away. Explicit caching only pays off for content the endpoint can actually count, so
    # inline PDFs go straight to the prompt. (If Vertex ever tokenises inline parts, or the
    # manuals move to GCS URIs, drop this guard and the path below works as written.)
    if parts and all(getattr(part, "inline_data", None) is not None for part in parts):
        return None, parts

    key = f"machinecache:{machine.pk}:{_docset_hash(docs)}:{locale}"
    cached = django_cache.get(key)
    if cached:
        return (None, parts) if cached == _CACHE_REFUSED else (cached, [])
    try:
        name = gemini.create_cache(
            model=MODELS["flash"], contents=parts, ttl_seconds=_CACHE_TTL,
            display_name=f"machine-{machine.pk}",
        )
    except Exception as exc:  # noqa: BLE001 — caching unavailable / docset under provider floor
        # Remember the refusal. Vertex counts an INLINE pdf part as 1 token, so a docset of
        # manuals is "1 token" to the cache endpoint and lands under its 1024 floor — it
        # fails every time, deterministically. Uploading the PDF to be told that took 15.2s
        # of every specialist turn (~40% of the whole turn, measured), and the failure was
        # swallowed, so it looked like the model being slow rather than work we throw away.
        logger.warning("context cache refused for machine %s (%s) — inlining instead for "
                       "the next %ss", machine.pk, str(exc)[:120], _CACHE_TTL)
        django_cache.set(key, _CACHE_REFUSED, _CACHE_TTL)
        return None, parts  # fall back to inline; never block an answer on caching
    django_cache.set(key, name, _CACHE_TTL - 60)
    return name, []
