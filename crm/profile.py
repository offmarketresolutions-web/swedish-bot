"""Customer profile enrichment (CRM 360).

Deterministically copies the resolved machine / brand / equipment-type FKs + the AI
summary from an escalated Session onto the Customer, so the profile itself "logs
everything gathered" and links straight to the right machine/brand/type records.

This is NEVER driven by LLM output — only by the orchestrator-resolved Session
columns (Session.machine/category are written by chat.casestate.flush_to_session).
Latest-escalated-session-wins for the primary_* FKs; full per-conversation history
stays on the Session rows.
"""
from __future__ import annotations


def match_brand(name: str):
    """Best-effort, deterministic match of a typed brand string to a known Vendor
    (used when the machine itself isn't in our catalog). Returns a Vendor or None."""
    from kb.models import Vendor

    n = (name or "").strip()
    if not n:
        return None
    return (Vendor.objects.filter(name__iexact=n).first()
            or Vendor.objects.filter(slug=n.lower().replace(" ", "-")).first()
            or Vendor.objects.filter(name__icontains=n).first())


def build_equipment_summary(customer) -> str:
    """Readable list of the distinct equipment seen across the customer's sessions,
    e.g. 'IVT Geo 412C · Mitsubishi MSZ-LN35'. Supported machines first by recency."""
    seen, parts = set(), []
    for s in customer.sessions.select_related("machine", "machine__vendor").order_by("-created_at"):
        if s.machine_id:
            label = f"{s.machine.vendor.name} {s.machine.model_name}"
        elif s.manufacturer or s.model:
            label = f"{s.manufacturer} {s.model}".strip()
        else:
            continue
        key = label.lower()
        if key not in seen:
            seen.add(key)
            parts.append(label)
    return " · ".join(parts)[:255]


def build_problem_descriptor(session) -> str:
    """Deterministic 1-2 sentence 'senaste ärende' line for the customer profile, e.g.
    'IVT Geo 412C — larm H01 5252, otillräckligt varmvatten (2026-07-14)'. Built purely
    from already-resolved Session facts — never an LLM call. `_problem_text` is a
    transient attribute stashed by chat.casestate.flush_to_session (no Session column
    needed: the same in-memory Session instance flows straight into enrich_customer_from_session
    within one escalation turn)."""
    if session.machine_id:
        equip = f"{session.machine.vendor.name} {session.machine.model_name}"
    else:
        equip = f"{session.manufacturer} {session.model}".strip()
    problem = (getattr(session, "_problem_text", "") or "").strip()
    detail_parts = []
    if session.error_code:
        detail_parts.append(f"larm {session.error_code}")
    if problem:
        detail_parts.append(problem)
    line = equip.strip()
    if detail_parts:
        line = f"{line} — {', '.join(detail_parts)}" if line else ", ".join(detail_parts)
    if session.created_at:
        date = session.created_at.strftime("%Y-%m-%d")
        line = f"{line} ({date})" if line else date
    return line[:200]


def enrich_customer_from_session(customer, session) -> None:
    """Copy an escalated session's resolved facts onto the customer profile and save.

    Assigns primary_machine/primary_brand/primary_category FKs (so the profile routes
    to the right records), refreshes the concise problem descriptor, and rebuilds the
    equipment summary. Call AFTER session.customer is set so the summary includes this
    session.
    """
    if session.machine_id:
        customer.primary_machine = session.machine
        customer.primary_brand = session.machine.vendor
    else:
        brand = match_brand(session.manufacturer)  # unsupported brand → still link if we can
        if brand:
            customer.primary_brand = brand
    if session.category_id:
        customer.primary_category = session.category
    descriptor = build_problem_descriptor(session)
    if descriptor:
        customer.profile_summary = descriptor
    customer.equipment_summary = build_equipment_summary(customer)
    customer.save()
