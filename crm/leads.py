"""Create a qualified lead (ServiceRequest) + an AI summary, then fan out to the
sinks (plan §9). Idempotent per (session, reason) via a stable pre-insert key."""
from __future__ import annotations

import hashlib

from chat import prompts
from core.services import gemini
from crm import sinks
from crm.models import ServiceRequest


def build_summary(session) -> str:
    transcript = "\n".join(
        f"{m.role}: {m.content}" for m in session.conversation.messages.all() if m.content
    )
    system = prompts.render("summarizer", locale=session.conversation.language)
    try:
        resp = gemini.generate(transcript[:8000], model=prompts.model_for("summarizer"),
                               system_instruction=system, max_output_tokens=300)
        return (resp.text or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _idempotency_key(session, reason: str) -> str:
    raw = f"{session.conversation.public_id}:{reason}:{session.model}:{session.error_code}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _payload(session) -> dict:
    c = session.customer
    return {
        "equipment": {"manufacturer": session.manufacturer, "model": session.model,
                      "serial": session.serial, "error_code": session.error_code},
        "problem_category": session.problem_category.slug if session.problem_category else None,
        "severity": session.severity,
        "customer": {
            "name": c.name if c else "", "phone": c.phone if c else "",
            "email": c.email if c else "", "address": c.address if c else "",
            "postal_code": c.postal_code if c else "",
        } if c else {},
        "summary": session.ai_summary,
        "troubleshooting_performed": session.troubleshooting_performed,
    }


def create_and_dispatch(session, reason: str = ""):
    """Create (or reuse) the ServiceRequest and fire all sinks. Returns (sr, results)."""
    if not session.ai_summary:
        session.ai_summary = build_summary(session)
        session.save(update_fields=["ai_summary"])
    sr, _ = ServiceRequest.objects.get_or_create(
        idempotency_key=_idempotency_key(session, reason),
        defaults={"session": session, "payload_json": _payload(session), "escalation_reason": reason},
    )
    results = sinks.dispatch(sr)
    return sr, results
