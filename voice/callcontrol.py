"""Vapi Live Call Control — POST to a call's ``controlUrl`` to inject into the live conversation.

The mid-call photo push (design §5, option B): the instant the vision pipeline finishes, Django
POSTs an ``add-message`` (role ``system``, ``triggerResponseEnabled: true``) to the call's captured
``controlUrl`` so the agent spontaneously confirms what it can see. ``say`` speaks a verbatim line
(a filler / canned confirmation) without an LLM turn.

Degrade-safe: a blank control_url or any HTTP error returns ``False`` — the caller falls back to the
``check_photos`` cue path. Never raises into the webhook/thread.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


def _post(control_url: str, body: dict) -> bool:
    if not control_url:
        return False
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(control_url, json=body)
        if resp.status_code >= 300:
            logger.warning("controlUrl POST → HTTP %s", resp.status_code)
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("controlUrl POST failed: %s", exc)
        return False


def add_message(control_url: str, content: str, *, role: str = "system",
                trigger_response: bool = True) -> bool:
    """Inject a message into the live conversation; ``trigger_response`` makes the agent speak."""
    return _post(control_url, {
        "type": "add-message",
        "message": {"role": role, "content": content},
        "triggerResponseEnabled": trigger_response,
    })


def say(control_url: str, content: str, *, end_call_after: bool = False) -> bool:
    """Speak a verbatim line without an LLM turn (filler / canned confirmation)."""
    return _post(control_url, {"type": "say", "content": content, "endCallAfterSpoken": end_call_after})
