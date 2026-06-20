"""Intake helpers: templated questions + DB-driven quick-reply chips + a cheap
LLM extractor/validator for free-text answers (plan §6.1). A chip tap needs no
LLM (exact value match); only free text hits the extractor."""
from __future__ import annotations

import json

from chat import prompts
from core.services import gemini

QUESTION = {
    "category": "To start, what kind of equipment is it?",
    "problem": "Got it. In a few words, what's the problem?",
    "brand": "Which brand is it?",
    "model": "What's the model? A photo of the rating/nameplate is perfect if you have one.",
    "error_code": "Is there an error or alarm code shown? (You can skip this.)",
}

GREETING = (
    "Hi! I'm Nordland VVS's assistant. I can help with heat pumps, water pumps/wells "
    "and water filtration. Let's figure out what's going on."
)


def chips_for(slot: str, cs: dict, locale: str = "en") -> list[dict]:
    """Return [{value, label}] from the DB for this intake step. Problem chips are
    filtered to the chosen category."""
    from kb.models import QuickReplyChip

    qs = QuickReplyChip.objects.filter(intake_step=slot, is_active=True)
    if slot == "problem":
        cat_slug = cs["slots"].get("category")
        qs = qs.filter(category__slug=cat_slug) if cat_slug else qs.filter(category__isnull=True)
    else:
        qs = qs.filter(category__isnull=True)
    return [{"value": c.value, "label": c.label(locale)} for c in qs.order_by("order")]


def _allowed_values(slot: str, cs: dict) -> set[str]:
    return {c["value"] for c in chips_for(slot, cs)}


def extract_answer(slot: str, user_text: str, cs: dict, locale: str = "en") -> tuple[bool, str]:
    """Return (on_target, normalized_value). Exact chip match short-circuits the
    LLM. Free text → one cheap extractor call. 'I don't know' → (True, 'unknown')."""
    text = (user_text or "").strip()
    if not text:
        return False, ""

    allowed = _allowed_values(slot, cs)
    if text in allowed:
        return True, text
    low = text.lower()
    for v in allowed:
        if low == v.lower():
            return True, v
    if low in ("i don't know", "idk", "dont know", "don't know", "not sure", "no"):
        return True, "unknown"

    # Free-text → cheap extractor (the "folded validator", plan §3 / decision #3).
    enum_hint = f" Must be one of: {sorted(allowed)}." if allowed and slot in ("category", "brand") else ""
    system = (
        "You extract one field from a support reply. Return JSON only: "
        '{"on_target": true/false, "value": <normalized or null>}. '
        f"Field: {slot}.{enum_hint} on_target is true only if the reply addresses this field. "
        "For free-text fields (problem, model, error_code) return the cleaned text as value."
    )
    try:
        resp = gemini.generate(
            f"Question: {QUESTION.get(slot, slot)}\nReply: {text}",
            model=prompts.model_for("intake"), system_instruction=system,
            response_mime_type="application/json", max_output_tokens=120,
        )
        data = json.loads(resp.text)
        val = data.get("value")
        return bool(data.get("on_target")), ("" if val is None else str(val))
    except Exception:  # noqa: BLE001
        # Fail open for free-text fields (accept the raw text); strict for enums.
        if slot in ("problem", "model", "error_code"):
            return True, text
        return False, ""
