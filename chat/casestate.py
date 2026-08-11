"""CaseState — the orchestrator's transient working blob, persisted on
Conversation.case_state and flushed to the typed crm.Session columns on every
state transition (plan §7). Session is the canonical reporting store.
"""
from __future__ import annotations

from core.enums import STATE_INTAKE

# Intake slots gathered before routing. Contact slots (name/phone/email/postal)
# are gathered lazily at escalation, exempt from the reply budget (plan §6.1/§6.2).
# postal_code is asked EARLY (right after category) — it never blocks routing
# (is_routable ignores it) but seeds the S5 service-area check (plan S2/D1).
REQUIRED_SLOTS = ["category", "postal_code", "problem", "brand", "model"]
OPTIONAL_SLOTS = ["error_code", "serial"]
# Multi-fact slots mined per-turn (bulk_extract + specialist extracted_facts). Kept
# JSON-only unless a Session column exists (plan D1). slots.model stays RAW customer
# text — never overwritten by a catalog machine name (enforced in every merge site).
EXTRA_SLOTS = ["subtype", "alarm_text", "onset", "operating_context", "installer", "warranty"]
# address (the installation street address) is asked LAST, right before the send-approval
# step, and is skippable exactly like email (decline → blank, never blocks the lead).
CONTACT_SLOTS = ["name", "phone", "email", "postal_code", "address"]


def _fit(value, limit: int) -> str:
    """Clamp an agent-supplied value to its Session column width. The prompts declare
    enums (onset, installer, severity) and short codes, but a model that answers in
    prose reaches these columns via extracted_facts / the router with no enum check —
    an unclamped write is a DataError that kills the whole turn."""
    return str(value or "").strip()[:limit]


def new_case_state() -> dict:
    return {
        "state": STATE_INTAKE,
        "current_slot": None,
        "reask": 0,
        "off_domain_streak": 0,
        "slots": {k: None for k in REQUIRED_SLOTS + OPTIONAL_SLOTS + EXTRA_SLOTS}
        | {"nameplate_photo": False, "ocr_text": None, "readings": []},
        "contact": {k: None for k in CONTACT_SLOTS} | {"consent": None},
        "contact_slot": None,
        "awaiting_approval": False,
        "escalation_reason": "",
        "machine_id": None,
        "model_confirmed": False,
        "await_model_confirm": False,
        "pending_candidate_ids": [],
        "model_search_mode": False,
        "model_gave_up": False,
        "service_area": "unknown",
        "specialist_mode": "manual",
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
            "checks": [],
            "form_type": "",
            "form_status": "none",
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
    # No-auto-bind (plan S3): only persist a catalog Machine once the customer has
    # CONFIRMED the exact model. An unconfirmed / general-mode case never sets Session.machine
    # (Session.model still keeps the raw customer text below).
    if machine is not None and cs.get("model_confirmed"):
        session.machine = machine
    session.manufacturer = _fit(s.get("brand"), 120) or session.manufacturer
    session.model = _fit(s.get("model"), 160) or session.model
    session.serial = _fit(s.get("serial"), 120) or session.serial
    session.error_code = _fit(s.get("error_code"), 64) or session.error_code
    if problem_category is not None:
        session.problem_category = problem_category
        session.category = problem_category.category
    if cs.get("severity"):
        session.severity = _fit(cs["severity"], 16)
    if cs.get("confidence"):
        session.confidence_score = cs["confidence"]
    if cs.get("decision"):
        session.decision = _fit(cs["decision"], 16)
    session.state = cs.get("state", "")
    # New typed columns (plan S2 migration). postal_code/onset/installer come from the
    # early-mined slots; escalation_reason closes a known reporting gap; service-area +
    # form fields are populated by later sprints but the flush plumbing lands now.
    if s.get("postal_code") and s.get("postal_code") != "unknown":
        session.postal_code = _fit(s["postal_code"], 16)
    if s.get("onset"):
        session.onset = _fit(s["onset"], 16)
    if s.get("installer"):
        session.installer = _fit(s["installer"], 32)
    if cs.get("escalation_reason"):
        session.escalation_reason = cs["escalation_reason"][:64]
    if cs.get("service_area") and cs["service_area"] != "unknown":
        session.service_area_status = cs["service_area"][:16]
    rep = cs.get("report", {})
    if rep.get("service_area_name"):
        session.service_area_name = rep["service_area_name"][:120]
    if rep.get("form_status") == "shown":
        session.form_shown = True
    if rep.get("form_url"):
        session.form_url = rep["form_url"][:200]
    if rep.get("form_category"):
        session.form_category = rep["form_category"][:32]
    if rep.get("troubleshooting_performed"):
        session.troubleshooting_performed = rep["troubleshooting_performed"]
    for f in ("resolved", "service_recommended", "booking_requested"):
        if rep.get(f) is not None:
            setattr(session, f, rep[f])
    session.save()
    # Transient (non-column) hint for crm.profile.build_problem_descriptor — the raw
    # slots.problem text has no Session field of its own (deterministic string assembly
    # only needs it at enrichment time, which always runs on this same in-memory
    # instance within the same escalation turn; no migration needed for this).
    session._problem_text = s.get("problem") or ""
    return session
