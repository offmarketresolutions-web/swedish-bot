"""``identify_machine`` server tool — wraps ``kb.identification.identify_machine``."""

from __future__ import annotations

from chat import sanitize
from voice.tools import register


@register("identify_machine")
def identify_machine(args: dict, ctx: dict) -> dict:
    """Resolve the caller's equipment from brand/model/free-text. On no confident match returns
    ``{identified: false}`` — the agent proceeds to info-gather, never fabricates a model."""
    from kb.identification import identify_machine as _identify

    brand = sanitize.clean_lead_field(str(args.get("brand") or ""), 40)
    model = sanitize.clean_model(str(args.get("model") or "")) or str(args.get("model") or "")[:40]
    free_text = sanitize.clean_lead_field(str(args.get("free_text") or ""), 200)
    query = " ".join(p for p in (brand, model, free_text) if p).strip()
    if not query:
        return {"identified": False}

    machine, score = _identify(query)
    if not machine:
        return {"identified": False, "confidence": round(float(score or 0.0), 2)}
    return {
        "identified": True,
        "machine_id": machine.pk,
        "name": str(machine),
        "confidence": round(float(score or 0.0), 2),
    }
