"""Deterministic call-outcome classification for the end-of-call-report (design §10).

Code owns the label — NO LLM. The model's ``analysis.structuredData`` fills slots; the precedence
here decides the durable ``VapiCall.outcome`` + reason. Highest-severity-wins so an escalation is
never masked by a softer outcome.
"""

from __future__ import annotations

import re


def _structured_data(message: dict) -> dict:
    analysis = message.get("analysis") or {}
    sd = analysis.get("structuredData")
    return sd if isinstance(sd, dict) else {}


_CALLBACK_RE = re.compile(r"\b(call ?back|ring(a)? upp|återkom|schedule|boka)\b", re.IGNORECASE)
_ESCALATE_RE = re.compile(
    r"\b(technician|tekniker|escalat\w*|service visit|servicebesök|book a visit)\b", re.IGNORECASE
)


def classify_outcome(message: dict, transcript: str) -> tuple[str, str]:
    """Return ``(outcome, reason)`` — one of resolved / escalation / callback / abandoned / error."""
    from voice.models import Outcome

    transcript = (transcript or "").strip()
    sd = _structured_data(message)

    # A tool-driven or model-emitted explicit outcome wins.
    sd_outcome = str(sd.get("outcome") or "").strip().lower()
    if sd_outcome in (Outcome.RESOLVED, Outcome.ESCALATION, Outcome.CALLBACK):
        return sd_outcome, str(sd.get("reason") or "")[:64]

    # A create_lead / schedule_callback tool fired during the call → escalation/callback.
    for msg in message.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        name = str(msg.get("name") or msg.get("toolName") or "")
        if name == "schedule_callback":
            return Outcome.CALLBACK, "callback"
        if name == "create_lead":
            return Outcome.ESCALATION, "phone_escalation"

    ended = (message.get("endedReason") or "").lower()
    if "error" in ended or "failed" in ended:
        return Outcome.ERROR, ""
    if not transcript and not (message.get("messages") or []):
        return Outcome.ABANDONED, ""

    if _CALLBACK_RE.search(transcript):
        return Outcome.CALLBACK, "callback"
    if _ESCALATE_RE.search(transcript):
        return Outcome.ESCALATION, "phone_escalation"
    return Outcome.RESOLVED, ""
