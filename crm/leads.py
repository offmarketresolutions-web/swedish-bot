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
        # S5: service-area status rides the lead so the technician sees inside/border/unknown
        # coverage at a glance (only present once a check actually ran).
        "service_area": {
            "status": f(session.service_area_status, 16),
            "name": f(session.service_area_name, 120),
        } if session.service_area_status else None,
    }


def attach_customer_files(session) -> int:
    """Copy uploaded photos from the transcript onto the customer's CRM profile
    (V2 P-E) via the Customer File Hub storage service, so they land in the
    per-customer uploads/ folder, survive a conversation purge, and get mirrored to
    Drive. Idempotent by content hash. Additive — same rows as before, better home."""
    from crm import storage

    c = session.customer
    if not c:
        return 0
    n = 0
    for m in session.conversation.messages.filter(image__isnull=False).exclude(image=""):
        try:
            m.image.open("rb")
            data = m.image.read()
        except Exception:  # noqa: BLE001
            continue
        _cf, created = storage.register_file(
            c, content=data, filename=f"{hashlib.sha256(data).hexdigest()[:12]}.jpg",
            folder="uploads", source="chat", kind="photo", source_message=m)
        n += created
    return n


def create_and_dispatch(session, reason: str = ""):
    """Create (or reuse) the ServiceRequest and fire all sinks. Returns (sr, results)."""
    reason = reason[:120]  # guardrail LLM reasons are unbounded; column is varchar(120)
    if not session.ai_summary:
        session.ai_summary = build_summary(session)
        session.save(update_fields=["ai_summary"])
    attach_customer_files(session)
    sr, _ = ServiceRequest.objects.get_or_create(
        idempotency_key=_idempotency_key(session, reason),
        defaults={"session": session, "payload_json": _payload(session), "escalation_reason": reason},
    )
    results = sinks.dispatch(sr)
    return sr, results
