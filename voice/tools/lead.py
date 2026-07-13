"""``create_lead`` + ``schedule_callback`` server tools — reuse the CRM lead pipeline.

Both build a ``crm.Session`` (the same durable row the web escalation writes) stamped with the
caller's peppered ``phone_hash``, then create a ``ServiceRequest`` and fan out via ``crm.sinks``.
Idempotent per ``(call_id, reason)`` so a Vapi tool re-fire returns the same lead — never a double.
"""

from __future__ import annotations

import hashlib

from chat import sanitize
from crm.models import phone_hash as _phone_hash
from voice.tools import register


def _voice_idempotency_key(call_id: str, reason: str, model: str, error_code: str) -> str:
    raw = f"voice:{call_id}:{reason}:{model}:{error_code}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _resolve_customer(args: dict, ctx: dict):
    from crm.models import Customer

    ph = ctx.get("phone_hash") or _phone_hash(ctx.get("caller_phone") or args.get("phone") or "")
    name = sanitize.clean_name(str(args.get("name") or ""))
    phone = str(args.get("phone") or ctx.get("caller_phone") or "")
    cust = None
    if ph:
        cust = Customer.objects.filter(phone_hash=ph).order_by("-created_at").first()
    if cust is None:
        cust = Customer(name=name, phone=phone,
                        email=sanitize.clean_email(str(args.get("email") or "")),
                        postal_code=sanitize.clean_postal(str(args.get("postal") or "")))
        cust.save()
    return cust


def _create_lead(args: dict, ctx: dict, *, reason: str) -> dict:
    from crm import leads, sinks
    from crm.models import ServiceRequest
    from chat.models import Conversation
    from crm.models import Session

    call_id = str(ctx.get("call_id") or "")
    model = sanitize.clean_model(str(args.get("model") or "")) or str(args.get("model") or "")[:40]
    error_code = sanitize.clean_error_code(str(args.get("error_code") or ""))
    key = _voice_idempotency_key(call_id, reason, model, error_code)

    existing = ServiceRequest.objects.filter(idempotency_key=key).first()
    if existing:
        return {"created": False, "lead_id": existing.pk, "reason": reason}

    cust = _resolve_customer(args, ctx)
    conv = Conversation.objects.create(language="sv", status="closed")
    session = Session.objects.create(
        conversation=conv, customer=cust,
        manufacturer=sanitize.clean_lead_field(str(args.get("brand") or ""), 40),
        model=model, error_code=error_code,
        decision="escalate", status="escalated",
        ai_summary=sanitize.clean_lead_field(str(args.get("problem") or ""), 800),
    )
    sr, _ = ServiceRequest.objects.get_or_create(
        idempotency_key=key,
        defaults={"session": session, "payload_json": leads._payload(session),
                  "escalation_reason": reason},
    )
    sinks.dispatch(sr)
    return {"created": True, "lead_id": sr.pk, "reason": reason}


@register("create_lead")
def create_lead(args: dict, ctx: dict) -> dict:
    """Create (or reuse) a qualified service lead. Idempotent per call+reason."""
    reason = sanitize.clean_lead_field(str(args.get("reason") or "phone_escalation"), 60)
    return _create_lead(args, ctx, reason=reason)


@register("schedule_callback")
def schedule_callback(args: dict, ctx: dict) -> dict:
    """Book a technician callback. Needs a phone; asks the agent to collect it if missing."""
    phone = sanitize.clean_phone(str(args.get("phone") or ctx.get("caller_phone") or ""))
    if not phone:
        return {"need": "phone"}
    merged = dict(args)
    merged["phone"] = phone
    if not merged.get("problem"):
        merged["problem"] = sanitize.clean_lead_field(str(args.get("preferred_window") or "callback"), 120)
    return _create_lead(merged, ctx, reason="callback")
