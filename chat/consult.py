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
