"""Vapi webhook signature verification — fail-closed at the edge.

Ported from happytime-budtender/voice/voice/signing.py. ``verify_signature(request)`` is called
FIRST inside ``voice/webhooks.py`` (NOT middleware, so a bad signature returns a Vapi-shaped 401 —
a middleware 401 confuses Vapi's retry). Two modes, both constant-time (``hmac.compare_digest``),
both reject-by-default:

  * Mode A — HMAC body signature: ``X-Vapi-Signature: hex(hmac_sha256(secret, raw_body))``.
  * Mode B — shared-secret echo: ``X-Vapi-Secret: <VAPI_WEBHOOK_SECRET>``.

Fail-closed posture: an unconfigured secret, a missing header, or a wrong proof → reject. The
header NAMES are env-driven (``VAPI_SIGNATURE_HEADER`` / ``VAPI_SECRET_HEADER``).

DEBUG-only bypass: ``VOICE_WEBHOOK_DEV_BYPASS=1`` is honored ONLY when ``settings.DEBUG`` is True,
so local dev works with unset secrets while production stays fail-closed (the prod compose forces
DEBUG=0). Never a silent default.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def compute_signature(raw_body: bytes, secret: str) -> str:
    """Hex HMAC-SHA256 over the raw request body with the shared secret (Mode A proof)."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def dev_bypass_active() -> bool:
    """True only when DEBUG and the explicit dev-bypass flag are BOTH set (never in prod)."""
    return bool(getattr(settings, "DEBUG", False)) and bool(
        getattr(settings, "VOICE_WEBHOOK_DEV_BYPASS", False)
    )


def verify_signature(request) -> tuple[bool, str]:
    """Authenticate an inbound Vapi webhook. Returns ``(ok, reason)``; ``ok=False`` means the
    caller must reject with 401 BEFORE parsing the body (fail-closed).

    Order: DEBUG dev-bypass → allow; unconfigured-secret → reject; Mode-A signature header →
    HMAC compare; else Mode-B secret header → constant-time compare; else no proof → reject."""
    if dev_bypass_active():
        return True, "dev-bypass (DEBUG only)"

    secret = getattr(settings, "VAPI_WEBHOOK_SECRET", "") or ""
    if not secret:
        return False, "webhook secret not configured"

    sig_header = getattr(settings, "VAPI_SIGNATURE_HEADER", "X-Vapi-Signature")
    secret_header = getattr(settings, "VAPI_SECRET_HEADER", "X-Vapi-Secret")

    sig = request.headers.get(sig_header, "")
    if sig:
        expected = compute_signature(request.body, secret)
        return (hmac.compare_digest(expected, sig), "bad hmac signature")

    provided = request.headers.get(secret_header, "")
    if provided:
        return (hmac.compare_digest(provided, secret), "bad shared secret")

    return False, "no signature header"


# ── Meta WhatsApp Cloud API signature (X-Hub-Signature-256) ────────────────────
def verify_meta_signature(request) -> tuple[bool, str]:
    """Verify Meta's ``X-Hub-Signature-256: sha256=<hmac_sha256(app_secret, raw_body)>``.
    Fail-closed: unset ``WA_APP_SECRET`` or a missing/bad header → reject. DEBUG dev-bypass
    honored identically to the Vapi path (local dev only)."""
    if dev_bypass_active():
        return True, "dev-bypass (DEBUG only)"

    secret = getattr(settings, "WA_APP_SECRET", "") or ""
    if not secret:
        return False, "WA_APP_SECRET not configured"

    header = request.headers.get("X-Hub-Signature-256", "")
    if not header.startswith("sha256="):
        return False, "no X-Hub-Signature-256 header"
    provided = header.split("=", 1)[1]
    expected = compute_signature(request.body, secret)
    return (hmac.compare_digest(expected, provided), "bad meta signature")
