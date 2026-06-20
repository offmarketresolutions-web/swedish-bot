"""CaseState — the orchestrator's transient working blob, persisted on
Conversation.case_state and flushed to the typed crm.Session columns on every
state transition (plan §7). Session is the canonical reporting store.
"""
from __future__ import annotations

from core.enums import STATE_INTAKE

# Intake slots gathered before routing. Contact slots (name/phone/email/postal)
# are gathered lazily at escalation, exempt from the reply budget (plan §6.1/§6.2).
REQUIRED_SLOTS = ["category", "problem", "brand", "model"]
OPTIONAL_SLOTS = ["error_code", "serial"]
CONTACT_SLOTS = ["name", "phone", "email", "postal_code"]


def new_case_state() -> dict:
    return {
        "state": STATE_INTAKE,
        "current_slot": None,
        "reask": 0,
        "slots": {k: None for k in REQUIRED_SLOTS + OPTIONAL_SLOTS}
        | {"nameplate_photo": False, "ocr_text": None},
        "contact": {k: None for k in CONTACT_SLOTS} | {"consent": None},
        "contact_slot": None,
        "awaiting_approval": False,
        "escalation_reason": "",
        "machine_id": None,
        "match_confidence": 0.0,
        "problem_category": None,
        "severity": "",
        "decision": "",
        "confidence": 0.0,
        "report": {
            "troubleshooting_performed": [],
            "resolved": None,
            "service_recommended": None,
            "booking_requested": None,
        },
    }


def has_identity(cs: dict) -> bool:
    s = cs["slots"]
    return bool((s.get("brand") and s.get("model")) or s.get("nameplate_photo"))


def is_routable(cs: dict) -> bool:
    s = cs["slots"]
    return bool(s.get("category") and s.get("problem") and has_identity(cs))


def next_required_slot(cs: dict) -> str | None:
    """Next empty required slot to ask. If a usable photo is present, brand/model
    are skippable."""
    s = cs["slots"]
    for slot in REQUIRED_SLOTS:
        if slot in ("brand", "model") and s.get("nameplate_photo"):
            continue
        if not s.get(slot) or s.get(slot) == "unknown":
            if slot in ("brand", "model") and (s.get(slot) == "unknown"):
                continue  # gave up on it
            if not s.get(slot):
                return slot
    return None


def flush_to_session(conversation, cs: dict, *, machine=None, problem_category=None):
    """Write the structured subset of CaseState into the canonical Session.
    Admin-edited fields are not clobbered here — only orchestrator-owned facts."""
    from crm.models import Session

    s = cs["slots"]
    session, _ = Session.objects.get_or_create(conversation=conversation)
    session.machine = machine or session.machine
    session.manufacturer = s.get("brand") or session.manufacturer
    session.model = s.get("model") or session.model
    session.serial = s.get("serial") or session.serial
    session.error_code = s.get("error_code") or session.error_code
    if problem_category is not None:
        session.problem_category = problem_category
        session.category = problem_category.category
    if cs.get("severity"):
        session.severity = cs["severity"]
    if cs.get("confidence"):
        session.confidence_score = cs["confidence"]
    if cs.get("decision"):
        session.decision = cs["decision"]
    session.state = cs.get("state", "")
    rep = cs.get("report", {})
    if rep.get("troubleshooting_performed"):
        session.troubleshooting_performed = rep["troubleshooting_performed"]
    for f in ("resolved", "service_recommended", "booking_requested"):
        if rep.get(f) is not None:
            setattr(session, f, rep[f])
    session.save()
    return session
