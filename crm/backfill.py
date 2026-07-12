"""Backfill Customer profiles from existing conversation/case data (Customer File Hub).

Historically a Customer row was only created lazily on escalation. This links older
cases to Customers where the contact facts were captured in the conversation's
case_state but no Customer/Session.customer link exists yet — so the File Hub shows
a complete history. Keyed by the peppered phone_hash so a returning caller collapses
onto one profile.

Run by migration crm/0003 and callable directly (tested). Idempotent.
"""
from __future__ import annotations


def _contact_from_case_state(case_state: dict) -> dict:
    contact = (case_state or {}).get("contact") or {}
    return {
        "name": (contact.get("name") or "").strip(),
        "phone": (contact.get("phone") or "").strip(),
        "email": (contact.get("email") or "").strip(),
        "postal_code": (contact.get("postal_code") or "").strip(),
    }


def backfill_customers() -> int:
    """Create/link Customers for Sessions that captured contact info but have no
    customer. Returns the number of Sessions newly linked. Idempotent."""
    from crm.models import Customer, phone_hash
    from crm.profile import enrich_customer_from_session
    from crm.models import Session

    linked = 0
    qs = Session.objects.select_related("conversation", "machine", "category").filter(customer__isnull=True)
    for sess in qs:
        cs = getattr(sess.conversation, "case_state", None) if sess.conversation_id else None
        contact = _contact_from_case_state(cs or {})
        if not (contact["phone"] or contact["email"] or contact["name"]):
            continue  # nothing to build a profile from

        customer = None
        ph = phone_hash(contact["phone"]) if contact["phone"] else ""
        if ph:
            customer = Customer.objects.filter(phone_hash=ph).first()
        if customer is None and contact["email"]:
            customer = Customer.objects.filter(email__iexact=contact["email"]).first()
        if customer is None:
            customer = Customer.objects.create(
                name=contact["name"], phone=contact["phone"],
                email=contact["email"], postal_code=contact["postal_code"],
            )
        sess.customer = customer
        sess.save(update_fields=["customer"])
        enrich_customer_from_session(customer, sess)
        linked += 1
    return linked
