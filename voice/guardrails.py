"""Code-owned voice safety helpers (ported shape from budtender/voice/guardrails.py).

swedish-bot's voice channel has no cost/margin leak surface (unlike cannabis retail), so
``scrub_leak`` is an identity pass kept for the ported call sites (dispatch / callfetch) — the
seam exists if a sensitive field is ever added. ``redact_pii`` masks phone-like digit runs before
any tool-call arg / fetched transcript is PERSISTED (the DB keeps only the peppered hash).
"""

from __future__ import annotations

import re

_PHONE_RE = re.compile(r"\+?\d[\d\-.\s()]{5,}\d")


def scrub_leak(payload):
    """Identity pass — no forbidden fields on the HVAC voice surface. The central seam callers
    (``tools.dispatch``) still route through it so a future forbidden-field rule has one home."""
    return payload


def assert_no_leak(payload) -> None:  # noqa: D401 - contract parity with the ported webhook
    """No-op — kept for parity with the ported webhook's belt-and-suspenders assert."""
    return None


def redact_pii(payload):
    """Structure-preserving mask of phone-like digit runs in every string value."""
    if isinstance(payload, dict):
        return {k: redact_pii(v) for k, v in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [redact_pii(v) for v in payload]
    if isinstance(payload, str):
        return _PHONE_RE.sub("[redacted]", payload)
    return payload
