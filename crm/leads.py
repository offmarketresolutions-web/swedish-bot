"""Create a qualified lead (ServiceRequest) + an AI summary, then fan out to the
sinks (plan §9). Idempotent per (session, reason) via a stable pre-insert key."""
from __future__ import annotations

import hashlib

from chat import prompts, sanitize
from core.services import gemini
from crm import sinks
from crm.models import ServiceRequest


def build_summary(session) -> str:
    transcript = "\n".join(
        f"{m.role}: {m.content}" for m in session.conversation.messages.all() if m.content
    )
    system = prompts.render("summarizer", locale=session.conversation.language)
    try:
        # S8: the transcript is untrusted — wrap as data so a user can't inject
        # instructions that poison the stored summary (which is re-shown to staff).
        resp = gemini.generate(sanitize.wrap_untrusted(transcript[:8000], "transcript"),
                               model=prompts.model_for("summarizer"),
                               system_instruction=system, max_output_tokens=300)
        return (resp.text or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _idempotency_key(session, reason: str) -> str:
    raw = f"{session.conversation.public_id}:{reason}:{session.model}:{session.error_code}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _payload(session) -> dict:
    c = session.customer
    f = sanitize.clean_lead_field  # S1: defense-in-depth — no CR/LF / control / oversize
    return {
        "equipment": {"manufacturer": f(session.manufacturer, 40), "model": f(session.model, 40),
                      "serial": f(session.serial, 40), "error_code": f(session.error_code, 16)},
        "problem_category": session.problem_category.slug if session.problem_category else None,
        "severity": session.severity,
        "customer": {
            "name": f(c.name) if c else "", "phone": f(c.phone, 32) if c else "",
            "email": f(c.email) if c else "", "address": f(c.address) if c else "",
            "postal_code": f(c.postal_code, 20) if c else "",
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
