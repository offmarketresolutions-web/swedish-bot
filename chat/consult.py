"""Brand-consult tool (V2 conversation-core): a general specialist (no manual loaded)
can call this to have the BRAND documentation specialist dig through everything known
about the brand — Vendor.agent_notes, BrandNotes, MachineNotes, and candidate Machine
rows for that brand/model text — and bring back a token-concise digest.

Deterministic when there is nothing to consult (no vendor row, or no notes at all):
returns a NOT-IN-NOTES fallback with no LLM call. Otherwise one flash_lite call over
material wrapped as untrusted DATA (chat.sanitize.wrap_untrusted) — the brand
documentation specialist never invents; it says NOT-IN-NOTES when the notes don't
cover the question.
"""
from __future__ import annotations

from urllib.parse import urlparse

from chat.sanitize import cap, wrap_untrusted
from core.constants import MODELS
from core.services import gemini

_NO_NOTES = "NOT-IN-NOTES: no brand notes available"
_MATERIAL_CAP = 4000

_SYSTEM = (
    "You are the brand documentation specialist. Digest ONLY the material below to answer "
    "the consulting agent's question. Keep the answer to 180 tokens or fewer, as terse bullet "
    "facts, and cite the source tag ([B<pk>] for a brand note, [M<pk>] for a machine note/"
    "candidate) on every fact you use. If the material doesn't cover the question, say "
    "'NOT-IN-NOTES' plainly — never invent a fact.\n\n"
)


def _vendor_for(brand: str):
    from kb.models import Vendor

    if not brand:
        return None
    return (Vendor.objects.filter(name__iexact=brand).first()
            or Vendor.objects.filter(slug=str(brand).lower()).first())


def _gather_material(vendor, model_text: str | None) -> str:
    from kb.identification import candidate_matches
    from kb.models import BrandNote, MachineNote

    parts: list[str] = []
    if vendor.agent_notes:
        parts.append(f"[V{vendor.pk}] {vendor.agent_notes}")
    for bn in BrandNote.objects.filter(vendor=vendor):
        if bn.body:
            parts.append(f"[B{bn.pk}] {bn.body}")
    cands = candidate_matches(model_text or "", vendor=vendor, limit=5) if model_text else []
    machine_ids = []
    for m, _score in cands:
        machine_ids.append(m.id)
        alias_sfx = f" (aliases: {', '.join(m.aliases)})" if m.aliases else ""
        parts.append(f"[M{m.pk}] {m.vendor.name} {m.model_name}{alias_sfx}")
    if machine_ids:
        for mn in MachineNote.objects.filter(machine_id__in=machine_ids):
            if mn.body:
                parts.append(f"[M{mn.machine_id}] {mn.body}")
    return "\n".join(parts)


def consult_brand(brand: str, model_text: str | None, question: str, locale: str = "en") -> str:
    """Digest everything known about `brand` (+ candidate machines for `model_text`)
    to answer `question`. Deterministic NOT-IN-NOTES fallback when nothing exists for
    the brand — no LLM call in that case."""
    vendor = _vendor_for(brand)
    if vendor is None:
        return _NO_NOTES
    material = _gather_material(vendor, model_text)
    if not material.strip():
        return _NO_NOTES
    system = _SYSTEM + wrap_untrusted(cap(material, _MATERIAL_CAP), "brand_notes")
    try:
        resp = gemini.generate(
            f"Question: {cap(question or '', 300)}", model=MODELS["flash_lite"],
            system_instruction=system, max_output_tokens=250, temperature=0.2,
        )
        return (resp.text or "").strip() or _NO_NOTES
    except Exception:  # noqa: BLE001 — a consult failure must never break the turn
        return _NO_NOTES


# ── consult_web: official-manufacturer web research ────────────────────
# Mirrors consult_brand, but the material comes from a Google-Search-grounded flash
# call instead of the DB. Two hard gates: (1) the brand must have an explicit
# Vendor.official_domains allowlist — unknown brand or empty list means zero LLM
# calls; (2) every grounding chunk is filtered against that allowlist in Python
# before anything reaches the digest, so a lookalike host (nibe.eu.evil.com) or a
# forum (byggahus.se) can never become material.

_NO_SOURCES = "NOT-IN-SOURCES: no official manufacturer source found"

_SEARCH_SYSTEM = (
    "You are a web research assistant. Search the OFFICIAL manufacturer website for the "
    "product below and report what the official product/specification/manual pages say "
    "about the question. Prefer the manufacturer's own domains. Be factual and terse."
)

_WEB_SYSTEM = (
    "You are the web research specialist. Digest ONLY the material below — official "
    "manufacturer sources — to answer the consulting agent's question. Keep the answer to "
    "180 tokens or fewer, as terse bullet facts, and cite the source tag "
    "([W<n> <domain>]) on every fact you use. Official product/specification pages may be "
    "cited for IDENTIFICATION, SPECIFICATIONS and CONTROL/SETTING descriptions ONLY. NEVER "
    "state a repair or service procedure sourced from the web — if the question asks for "
    "one, answer 'NOT-IN-SOURCES' for that part. If the material doesn't cover the "
    "question, say 'NOT-IN-SOURCES' plainly — never invent a fact.\n\n"
)


def _norm_host(host: str | None) -> str:
    h = (host or "").strip().lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def _allowlist(brand: str) -> list[str]:
    vendor = _vendor_for(brand)
    if vendor is None:
        return []
    doms = getattr(vendor, "official_domains", None) or []
    return [d for d in (_norm_host(str(x)) for x in doms) if d]


def _host_allowed(host: str, allow: list[str]) -> bool:
    return any(host == a or host.endswith("." + a) for a in allow)


def _web_chunks(resp) -> list[tuple[str, str, str]]:
    """(domain, title, uri) per grounding chunk. Vertex hands back redirect URIs
    (vertexaisearch.cloud.google.com/...), so web.domain is the trustworthy field;
    urlparse(uri).hostname is only a fallback. Chunks with neither are dropped."""
    raw = getattr(resp, "raw", None)
    cands = getattr(raw, "candidates", None) or []
    if not cands:
        return []
    meta = getattr(cands[0], "grounding_metadata", None)
    out: list[tuple[str, str, str]] = []
    for ch in (getattr(meta, "grounding_chunks", None) or []):
        web = getattr(ch, "web", None)
        if web is None:
            continue
        uri = getattr(web, "uri", "") or ""
        host = _norm_host(getattr(web, "domain", None)) or _norm_host(urlparse(uri).hostname)
        if not host:
            continue
        out.append((host, str(getattr(web, "title", "") or ""), str(uri)))
    return out


def consult_web(brand: str, model_text: str | None, question: str, locale: str = "en") -> str:
    """Research `question` against `brand`'s OFFICIAL manufacturer domains and return a
    token-concise digest. Deterministic NOT-IN-SOURCES (zero LLM calls) when the brand has
    no allowlist; NOT-IN-SOURCES (no digest call) when no source survives the filter."""
    allow = _allowlist(brand)
    if not allow:
        return _NO_SOURCES
    try:
        hints = " OR ".join(f"site:{d}" for d in allow)
        query = (f"{brand} {model_text or ''} {cap(question or '', 300)} ({hints})").strip()
        resp = gemini.generate(
            query, model=MODELS["flash"], system_instruction=_SEARCH_SYSTEM,
            max_output_tokens=600, temperature=0.2, tools=gemini.search_tool(),
        )
        chunks = _web_chunks(resp)
        kept = [c for c in chunks if _host_allowed(c[0], allow)]
        if not kept:
            return _NO_SOURCES
        parts = [f"[W{i} {host}] {title} {uri}".strip()
                 for i, (host, title, uri) in enumerate(kept, start=1)]
        # Laundering guard: the search summary is the model's prose over ALL its
        # sources, not just the whitelisted chunks — include it only when every
        # chunk passed the allowlist, else a single official hit would smuggle
        # forum-derived claims into the digest material.
        if len(kept) == len(chunks):
            parts.append("SEARCH SUMMARY: " + (resp.text or ""))
        system = _WEB_SYSTEM + wrap_untrusted(cap("\n".join(parts), _MATERIAL_CAP), "web_sources")
        digest = gemini.generate(
            f"Question: {cap(question or '', 300)}", model=MODELS["flash_lite"],
            system_instruction=system, max_output_tokens=250, temperature=0.2,
        )
        return (digest.text or "").strip() or _NO_SOURCES
    except Exception:  # noqa: BLE001 — a consult failure must never break the turn
        return _NO_SOURCES
