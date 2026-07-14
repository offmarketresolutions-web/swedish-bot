"""Prefill token helpers (plan S6/D2 — website form integration).

Pure, side-effect-free functions so either the widget-chip code (this sprint) or
the sibling's form-button code (a later sprint) can import without collision or
circular imports. No Django view logic here — see chat/views.py for the endpoint.
"""
from __future__ import annotations

from django.core import signing

PREFILL_SALT = "prefill"
PREFILL_MAX_AGE = 1800  # 30 minutes


def make_prefill_token(session) -> str:
    """session -> a signed, time-limited token embedding the Session pk."""
    return signing.dumps({"sid": session.pk}, salt=PREFILL_SALT)


def read_prefill_token(token: str, max_age: int = PREFILL_MAX_AGE) -> int | None:
    """token -> Session pk, or None if invalid/expired. Never raises."""
    try:
        data = signing.loads(token, salt=PREFILL_SALT, max_age=max_age)
        return data.get("sid")
    except signing.BadSignature:
        return None
    except Exception:  # noqa: BLE001 — malformed/expired tokens fail soft
        return None


def build_form_url(base_url: str, session) -> str:
    """base_url (a FormButton.url) + session -> the URL to send the customer to,
    with the prefill token appended as ?nl_case=<token> (preserves any existing
    query string)."""
    token = make_prefill_token(session)
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}nl_case={token}"
