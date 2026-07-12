"""Dashboard credentials — the editable catalog + apply-to-runtime helpers (ported from budtender).

``set_credential`` persists the value AND makes it live by writing both ``os.environ[name]`` and
``settings.<name>`` (Django settings is a live module object, so ``getattr(settings, name)`` readers
see the new value immediately). ``VoiceConfig.ready`` calls ``apply_all`` at boot so DB overrides
re-assert over the ``.env`` defaults.

This catalog holds only OUR secrets: the Vapi API key + webhook secret, the WhatsApp Cloud API
credentials, and the n8n webhook URL. ElevenLabs/Deepgram provider keys live in Vapi's own dashboard
(there is no public Vapi credential API).
"""

from __future__ import annotations

import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

# group, name (ENV/settings var), label, secret?, help. Order = display order.
CREDENTIAL_CATALOG: list[dict] = [
    {"group": "Vapi", "name": "VAPI_PRIVATE_KEY", "label": "Vapi private key", "secret": True,
     "help": "Bearer key for the Vapi REST API (provision, publish, call fetch). Live immediately."},
    {"group": "Vapi", "name": "VAPI_WEBHOOK_SECRET", "label": "Vapi webhook secret", "secret": True,
     "help": "Shared secret the inbound webhook verifies (fail-closed)."},
    {"group": "Vapi", "name": "VAPI_PHONE_NUMBER_ID", "label": "Vapi phone number id", "secret": False,
     "help": "Inbound number the assistant is attached to."},
    {"group": "Vapi", "name": "VAPI_ASSISTANT_ID", "label": "Vapi assistant id", "secret": False,
     "help": "Provisioned assistant id (publish target; set by provision)."},
    {"group": "Vapi", "name": "VAPI_VOICE_ID", "label": "ElevenLabs Swedish voice id", "secret": False,
     "help": "The 11labs sv-SE voice id used on the assistant."},
    {"group": "WhatsApp", "name": "WA_PHONE_NUMBER_ID", "label": "WhatsApp phone number id", "secret": False,
     "help": "Meta Cloud API phone-number id used to send the photo prompt."},
    {"group": "WhatsApp", "name": "WA_ACCESS_TOKEN", "label": "WhatsApp access token", "secret": True,
     "help": "Bearer token for the Graph API (media fetch + send)."},
    {"group": "WhatsApp", "name": "WA_APP_SECRET", "label": "WhatsApp app secret", "secret": True,
     "help": "Verifies X-Hub-Signature-256 on inbound webhooks (fail-closed)."},
    {"group": "WhatsApp", "name": "WA_VERIFY_TOKEN", "label": "WhatsApp verify token", "secret": True,
     "help": "Echoed during the Meta subscription handshake (GET verify)."},
    {"group": "WhatsApp", "name": "WA_PHOTO_TEMPLATE_NAME", "label": "Photo-prompt template", "secret": False,
     "help": "Approved WhatsApp template name for the 'send a photo' prompt (blank = plain text)."},
    {"group": "Integrations", "name": "N8N_WEBHOOK_URL", "label": "n8n webhook URL", "secret": False,
     "help": "Optional n8n workflow the bot can trigger + the lead fan-out sink (blank = disabled)."},
]

_CATALOG_BY_NAME = {c["name"]: c for c in CREDENTIAL_CATALOG}


def is_known(name: str) -> bool:
    return name in _CATALOG_BY_NAME


def current_value(name: str) -> str:
    return os.environ.get(name, "") or str(getattr(settings, name, "") or "")


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "••••"
    return f"{value[:3]}…{value[-2:]}"


def set_credential(name: str, value: str) -> None:
    from .models import Credential

    Credential.objects.update_or_create(name=name, defaults={"value": value})
    _apply_one(name, value)


def _apply_one(name: str, value: str) -> None:
    os.environ[name] = value
    setattr(settings, name, value)


def apply_all() -> int:
    """Re-assert every stored Credential over the .env defaults (called from app startup)."""
    try:
        from .models import Credential

        rows = list(Credential.objects.all())
    except Exception:  # noqa: BLE001 — DB not ready (first migrate) → nothing to apply yet
        return 0
    for c in rows:
        if c.value:
            _apply_one(c.name, c.value)
    return len(rows)


def catalog_with_values() -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for c in CREDENTIAL_CATALOG:
        val = current_value(c["name"])
        groups.setdefault(c["group"], []).append(
            {**c, "is_set": bool(val), "preview": mask(val) if c["secret"] else val}
        )
    return [{"group": g, "items": items} for g, items in groups.items()]
