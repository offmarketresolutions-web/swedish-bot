"""``kb_lookup`` server tool — grounded troubleshooting for the voice agent.

Mirrors the web specialist's confidence gate: a solve requires an identified machine, an
in-docs answer, and confidence >= CONFIDENCE_GATE. Anything else returns
``{can_help: false, suggest_escalate: true}`` so the agent escalates rather than stalls.
"""

from __future__ import annotations

import json
import logging

from chat import prompts, sanitize
from voice.tools import register

logger = logging.getLogger(__name__)

CONFIDENCE_GATE = 0.70


def _parse_json(text: str) -> dict:
    try:
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


@register("kb_lookup")
def kb_lookup(args: dict, ctx: dict) -> dict:
    """Return ``{can_help, suggest_escalate, answer?}``. Fails safe to escalate on any error or
    when the machine can't be identified / the answer isn't grounded in the docs."""
    from core.services import gemini
    from kb.identification import identify_machine
    from kb.models import Machine

    problem = sanitize.clean_lead_field(str(args.get("problem") or ""), 300)
    error_code = sanitize.clean_error_code(str(args.get("error_code") or ""))
    machine_id = args.get("machine_id")

    machine = None
    if isinstance(machine_id, (int, float)) and not isinstance(machine_id, bool):
        machine = Machine.objects.filter(pk=int(machine_id)).first()
    if machine is None and problem:
        machine, _score = identify_machine(problem)
    if machine is None:
        return {"can_help": False, "suggest_escalate": True, "reason": "machine not identified"}

    try:
        from chat.context import collect_knowledge

        brand_notes, faq = collect_knowledge(machine, "sv", query=problem)
        system = prompts.render(
            "specialist", locale="sv",
            brand=str(getattr(machine, "vendor", "") or ""), model=str(machine),
            category=str(getattr(machine, "category", "") or ""),
            brand_notes=brand_notes, faq=faq, problem=problem, symptoms=problem,
            error_code=error_code, serial="", forced_wrapup=False,
        )
        contents = [gemini.file_part(p) for p in _pdf_paths(machine)]
        contents.append(sanitize.wrap_untrusted(problem, "caller_problem"))
        resp = gemini.generate(contents or sanitize.wrap_untrusted(problem, "caller_problem"),
                               model=prompts.model_for("specialist"),
                               system_instruction=system,
                               response_mime_type="application/json", max_output_tokens=400)
        data = _parse_json(resp.text)
    except Exception:  # noqa: BLE001 — a KB/vision hiccup escalates, never crashes the call
        logger.warning("kb_lookup failed", exc_info=True)
        return {"can_help": False, "suggest_escalate": True, "reason": "lookup error"}

    confidence = float(data.get("confidence") or 0.0)
    in_docs = bool(data.get("in_docs"))
    decision = str(data.get("decision") or "escalate")
    can_help = decision == "solve" and in_docs and confidence >= CONFIDENCE_GATE
    out: dict = {"can_help": can_help, "suggest_escalate": not can_help,
                 "confidence": round(confidence, 2)}
    if can_help:
        out["answer"] = sanitize.clean_lead_field(str(data.get("answer_to_customer") or ""), 800)
    return out


def _pdf_paths(machine) -> list[str]:
    """Best-effort collect the machine's manual PDF paths for full-context grounding."""
    paths: list[str] = []
    try:
        from chat.context import models_q  # noqa: F401

        for doc in machine.documents.all():  # type: ignore[attr-defined]
            f = getattr(doc, "file", None)
            if f and getattr(f, "path", None):
                paths.append(f.path)
    except Exception:  # noqa: BLE001
        pass
    return paths
