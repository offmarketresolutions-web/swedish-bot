"""Publish-to-Vapi — the control-plane action (design §7), zero-drift.

One payload builder, two callers: this delegates to ``voice.provision.build_assistant_payload`` so
the dashboard "Publish" button and the CLI provisioner emit the identical shape. Zero-drift: when
``sha256(canonical_json(redact_payload(payload))) == VapiObject.last_provision_hash`` the preview is
``nodrift`` and a publish issues zero Vapi writes. Auto-publish is OFF for swedish-bot — publish is an
explicit button.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.services import vapi
from voice import constants as C
from voice import provision


@dataclass
class PublishPreview:
    action: str = "nodrift"          # nodrift | drift | skipped
    drift: bool = False
    changed_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)   # redacted, safe to render
    hash: str = ""
    stored_hash: str = ""


def _stored_hash() -> str:
    from voice.models import VapiObject

    rec = VapiObject.objects.filter(kind="assistant", name=C.ASSISTANT_NAME).first()
    return rec.last_provision_hash if rec else ""


def preview() -> PublishPreview:
    """Compute the publish diff WITHOUT any Vapi write. ``nodrift`` when the hash matches the last
    published payload (a no-edit publish is a proven no-op)."""
    payload, warnings = provision.build_assistant_payload()
    p = PublishPreview(warnings=warnings, payload=vapi.redact_payload(payload))
    if any(w.startswith("tool not provisioned") for w in warnings):
        p.action = "skipped"
        return p
    p.hash = provision.payload_hash(payload)
    p.stored_hash = _stored_hash()
    if p.hash == p.stored_hash and p.stored_hash:
        p.action = "nodrift"
        return p
    p.action = "drift"
    p.drift = True
    # Best-effort field-level diff against the live assistant (only when Vapi is reachable).
    p.changed_fields = _live_diff(payload)
    return p


def _live_diff(payload: dict) -> list[str]:
    from voice.models import VapiObject

    if not vapi.configured():
        return list(payload.keys())
    rec = VapiObject.objects.filter(kind="assistant", name=C.ASSISTANT_NAME).first()
    if not (rec and rec.vapi_id):
        return list(payload.keys())
    try:
        current = vapi.get_assistant(rec.vapi_id) or {}
    except vapi.VapiError:
        return list(payload.keys())
    return [k for k, v in payload.items() if current.get(k) != v]


def publish() -> dict:
    """Publish the assistant (GET-then-PATCH or create) via the idempotent provisioner. Zero-drift
    keeps a no-edit publish a cheap no-op. Returns a status dict for the toast."""
    r = provision.ensure_assistant()
    return {"action": r.action, "id": r.vapi_id, "warnings": r.warnings, "error": r.error}
