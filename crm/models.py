"""CRM: Customer + Session (canonical reporting store) + lead models.

Session is the single source of truth for the dashboard + admin edits — the
orchestrator flushes the structured subset of CaseState into these typed columns
on every state transition (plan §7, resolves crit 0.0/0.1). Admin edits are never
overwritten by a later summary back-fill.

ServiceRequest + LeadDelivery are defined here but wired to sinks in Phase 6.
"""
from __future__ import annotations

from django.db import models

from core.enums import SEVERITY_CHOICES


def phone_hash(phone: str) -> str:
    """Peppered SHA-256 of the normalized phone (V2 P-F). The hash is the lookup key
    for returning customers, so a DB leak doesn't expose a reversible phone index.
    Pepper is in env, distinct from SECRET_KEY (crit 0.6)."""
    import hashlib

    from django.conf import settings

    from chat.sanitize import clean_phone
    # Normalize to E.164 so the same number matches whatever format it's typed in
    # ('070-123 45 67' and '+46 70 123 45 67' hash identically). Fall back to a raw
    # digit strip for any value clean_phone can't parse.
    # ponytail: existing rows re-hash on their next save; fine for opt-in recognition.
    norm = clean_phone(phone) or "".join(c for c in (phone or "") if c.isdigit() or c == "+")
    if not norm:
        return ""
    pepper = getattr(settings, "PHONE_HASH_PEPPER", "")
    return hashlib.sha256((pepper + norm).encode()).hexdigest()


class Customer(models.Model):
    """Collected lazily, only when escalation is decided (plan §6.1)."""

    name = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    phone_hash = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=16, blank=True)
    city = models.CharField(max_length=120, blank=True)
    property_type = models.CharField(max_length=60, blank=True)
    consent_to_contact = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # CRM 360 — denormalized from the customer's most recent escalated Session so the
    # profile itself "logs everything" and links straight to the right machine/brand/type.
    # Written deterministically by crm.profile.enrich_customer_from_session (never by an LLM).
    primary_machine = models.ForeignKey(
        "kb.Machine", null=True, blank=True, on_delete=models.SET_NULL, related_name="owner_customers")
    primary_category = models.ForeignKey(
        "kb.Category", null=True, blank=True, on_delete=models.SET_NULL, related_name="owner_customers")
    primary_brand = models.ForeignKey(
        "kb.Vendor", null=True, blank=True, on_delete=models.SET_NULL, related_name="owner_customers")
    equipment_summary = models.CharField(max_length=255, blank=True)  # "IVT Geo 412C · Grundfos SQ"
    profile_summary = models.TextField(blank=True)                    # AI summary captured at profile creation

    def save(self, *args, **kwargs):
        self.phone_hash = phone_hash(self.phone)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name or self.phone or f"Customer<{self.pk}>"


class CustomerFile(models.Model):
    """Every photo/PDF a customer uploaded, retained on their CRM profile (V2 P-E).
    Copied out of the transcript so it survives conversation purges."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="customer_files/")
    kind = models.CharField(max_length=16, default="photo")  # photo | pdf | other
    sha256 = models.CharField(max_length=64, blank=True)
    source_message = models.ForeignKey(
        "chat.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("customer", "sha256")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"File<cust={self.customer_id} {self.kind}>"


class Session(models.Model):
    """One support session — the canonical reporting row (1:1 with Conversation)."""

    conversation = models.OneToOneField(
        "chat.Conversation", on_delete=models.CASCADE, related_name="session"
    )
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    machine = models.ForeignKey(
        "kb.Machine", null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    category = models.ForeignKey(
        "kb.Category", null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    problem_category = models.ForeignKey(
        "kb.ProblemCategory", null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )

    # Denormalized identification (kept even if the FK machine is later removed).
    manufacturer = models.CharField(max_length=120, blank=True)
    model = models.CharField(max_length=160, blank=True)
    serial = models.CharField(max_length=120, blank=True)
    error_code = models.CharField(max_length=64, blank=True)

    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, blank=True)
    confidence_score = models.FloatField(null=True, blank=True)

    troubleshooting_performed = models.JSONField(default=list, blank=True)
    resolved = models.BooleanField(null=True, blank=True)
    service_recommended = models.BooleanField(null=True, blank=True)
    booking_requested = models.BooleanField(null=True, blank=True)

    ai_summary = models.TextField(blank=True)
    decision = models.CharField(max_length=16, blank=True)  # solve | escalate
    state = models.CharField(max_length=24, blank=True)     # orchestrator FSM state
    reply_turns = models.IntegerField(default=0)
    status = models.CharField(max_length=16, default="active")  # active|resolved|escalated|closed

    # Case-state expansion (plan S2). postal_code/onset/installer are mined early;
    # escalation_reason closes a known reporting gap; service-area + form columns are
    # written by later sprints (S5/S6) but the columns + flush plumbing land now.
    postal_code = models.CharField(max_length=16, blank=True)
    service_area_status = models.CharField(max_length=16, blank=True)  # inside|border|outside|unknown
    service_area_name = models.CharField(max_length=120, blank=True)
    onset = models.CharField(max_length=16, blank=True)               # sudden|gradual|always
    installer = models.CharField(max_length=32, blank=True)           # nordland|bylunds|nordborr|other
    form_shown = models.BooleanField(null=True, blank=True)
    form_url = models.CharField(max_length=200, blank=True)
    form_category = models.CharField(max_length=32, blank=True)
    escalation_reason = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session<{self.pk}> {self.manufacturer} {self.model}".strip()


class ServiceRequest(models.Model):
    """Unified structured lead created on escalation approval (plan §7/§9)."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="service_requests")
    idempotency_key = models.CharField(max_length=128, unique=True)
    payload_json = models.JSONField(default=dict)
    escalation_reason = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ServiceRequest<{self.pk}> {self.escalation_reason}"


class LeadDelivery(models.Model):
    """One delivery attempt per (request, sink) — the idempotency boundary
    (plan §9, resolves crit 0.13). cron re-sends rows with status != success."""

    STATUS = [("pending", "Pending"), ("success", "Success"), ("failed", "Failed"), ("skipped", "Skipped")]

    service_request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="deliveries")
    sink = models.CharField(max_length=32)  # db | email | webhook | wordpress
    status = models.CharField(max_length=16, choices=STATUS, default="pending")
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("service_request", "sink")]

    def __str__(self):
        return f"LeadDelivery<{self.pk}> {self.sink}={self.status}"
