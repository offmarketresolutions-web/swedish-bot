"""Outbound customer-file mirror sink (Customer File Hub → n8n → Google Drive).

Follows the crm/sinks.py pattern: a single, self-contained, fail-soft outbound
POST that never raises into the caller. Fires when a new CustomerFile is
registered (crm.storage.register_file). Signs the body with an HMAC-SHA256 of the
shared secret so the n8n Webhook node can verify authenticity. Off by default —
does nothing until IntegrationSettings has a URL and n8n_enabled is on.

The n8n workflow (tools/n8n/drive_mirror.workflow.json) ensures a per-customer
Drive folder exists, uploads the file, and responds with the Drive link, which we
store on CustomerFile.drive_url.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Nordland-Signature"


def sign(body: bytes, secret: str) -> str:
    """Hex HMAC-SHA256 of the raw body with the shared secret."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _file_url(customer_file) -> str:
    """Best-effort absolute URL to the file for n8n to fetch. PUBLIC_BASE_URL (env)
    prefixes the media path; blank base yields a relative path (fine for local n8n
    or when n8n shares the media volume)."""
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    try:
        path = customer_file.file.url
    except Exception:  # noqa: BLE001
        path = ""
    return f"{base}{path}" if base else path


def build_payload(customer_file) -> dict:
    c = customer_file.customer
    return {
        "customer_id": c.pk,
        "customer_name": c.name or (c.phone or f"Customer {c.pk}"),
        "file_url": _file_url(customer_file),
        "filename": customer_file.original_name or customer_file.file.name.rsplit("/", 1)[-1],
        "folder": customer_file.folder,
    }


def mirror_customer_file(customer_file) -> str | None:
    """POST the signed file-registration payload to the configured n8n webhook.
    Returns the Drive link from the response if present, else None. Never raises."""
    from crm.models import IntegrationSettings

    cfg = IntegrationSettings.load()
    if not (cfg.n8n_enabled and cfg.n8n_webhook_url):
        return None

    body = json.dumps(build_payload(customer_file)).encode()
    headers = {"Content-Type": "application/json"}
    if cfg.n8n_shared_secret:
        headers[SIGNATURE_HEADER] = "sha256=" + sign(body, cfg.n8n_shared_secret)
    req = urllib.request.Request(cfg.n8n_webhook_url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 (config-controlled URL)
            raw = r.read()
    except Exception as exc:  # noqa: BLE001
        logger.warning("drive mirror sink failed: %s", exc)
        return None
    # The workflow responds with the Drive link; accept a few common key names.
    try:
        data = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(data, dict):
        for key in ("drive_url", "link", "webViewLink", "webContentLink", "url"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None
