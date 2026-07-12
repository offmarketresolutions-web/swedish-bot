"""Durable voice/WhatsApp records.

Frozen shapes, mirroring swedish-bot's Session/ServiceRequest durability + idempotency idioms:

  * ``VapiCall``     — one row per phone call, idempotent on the Vapi ``call_id``; holds the
    captured live-call ``control_url`` (from the status-update webhook) so the mid-call photo push
    knows where to POST.
  * ``ToolCallLog``  — one row per tool invocation (args + result), keyed by the Vapi ``call_id``
    string (tool-calls can arrive before the eocr creates the ``VapiCall``).
  * ``PhotoContext`` — extracted WhatsApp-photo facts keyed by the peppered ``phone_hash`` (the
    cross-channel join to ``crm.Customer``); ``delivered`` guards a re-push.
  * ``VapiObject``   — the provisioner's local id-map + the zero-drift hash oracle.

PII discipline: only the peppered ``phone_hash`` is stored — never a raw phone number.
"""

from __future__ import annotations

from django.db import models


class Outcome(models.TextChoices):
    RESOLVED = "resolved", "Resolved"
    ESCALATION = "escalation", "Escalation"
    CALLBACK = "callback", "Callback"
    ABANDONED = "abandoned", "Abandoned"
    ERROR = "error", "Error"


class VapiCall(models.Model):
    """One row per inbound call — the durable record, keyed on the Vapi ``call_id`` (idempotency
    key) so an end-of-call-report re-delivery upserts, never duplicates."""

    call_id = models.CharField(max_length=64, unique=True, db_index=True)
    # Peppered; the raw number is NEVER stored (PII discipline).
    caller_phone_hash = models.CharField(max_length=64, blank=True, db_index=True)
    # Captured from the status-update webhook's monitor.controlUrl — the mid-call push target.
    control_url = models.URLField(max_length=500, blank=True)
    status = models.CharField(max_length=24, blank=True)  # last Vapi status-update status
    outcome = models.CharField(max_length=24, choices=Outcome.choices, blank=True)
    escalated = models.BooleanField(default=False)
    reason = models.CharField(max_length=64, blank=True)
    duration_s = models.IntegerField(null=True, blank=True)
    transcript = models.TextField(blank=True)
    ai_summary = models.TextField(blank=True)
    assistant_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"VapiCall<{self.call_id}> {self.outcome or '—'}"


class ToolCallLog(models.Model):
    """One row per tool invocation in a call — the args the assistant SENT + the result it got.
    Keyed by the Vapi ``call_id`` string (not a FK) because tool-calls arrive BEFORE the eocr
    creates the ``VapiCall`` row. Idempotent on ``(call_id, tool_call_id, name)``."""

    call_id = models.CharField(max_length=64, db_index=True)
    tool_call_id = models.CharField(max_length=80, blank=True)
    name = models.CharField(max_length=64)
    args = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=16, default="webhook")  # webhook | vapi_fetch
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("call_id", "tool_call_id", "name")]
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"ToolCallLog<{self.call_id}/{self.name}>"


class PhotoContext(models.Model):
    """WhatsApp-photo-derived facts, keyed by the peppered ``phone_hash`` (the cross-channel join).
    The image itself lives on ``crm.CustomerFile`` (dedup by sha256); this row carries only the
    laundered text facts the voice agent can speak. ``delivered`` guards the mid-call re-push."""

    phone_hash = models.CharField(max_length=64, db_index=True)
    facts = models.JSONField(default=dict, blank=True)  # {brand, model, serial, error_code, ocr_text}
    image_sha256 = models.CharField(max_length=64, blank=True)
    n_photos = models.IntegerField(default=1)
    call_id = models.CharField(max_length=64, blank=True, db_index=True)
    control_url = models.URLField(max_length=500, blank=True)
    delivered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("phone_hash", "image_sha256")]

    def __str__(self) -> str:
        return f"PhotoContext<{self.phone_hash[:8]} {self.facts.get('model', '?')}>"


class VapiObject(models.Model):
    """The local id-map written back by the provisioner. One row per provisioned Vapi object
    keyed by ``(kind, name)`` so a re-run is GET-then-PATCH, never a blind POST.

    ``last_provision_hash`` is the ZERO-DRIFT oracle: when
    ``sha256(canonical_json(redact_payload(payload))) == last_provision_hash`` the reconcile is
    ``nodrift`` and NO Vapi write is issued."""

    KIND_CHOICES = [
        ("assistant", "Assistant"),
        ("tool", "Tool"),
        ("phone_number", "Phone number"),
    ]
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    name = models.CharField(max_length=128)
    vapi_id = models.CharField(max_length=64, blank=True)
    last_provision_hash = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("kind", "name")]
        ordering = ["kind", "name"]

    def __str__(self) -> str:
        return f"VapiObject<{self.kind}/{self.name}={self.vapi_id or '—'}>"
