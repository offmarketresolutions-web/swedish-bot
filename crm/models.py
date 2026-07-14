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


# Per-customer folder layout on local disk (Customer File Hub). Every customer gets
# media/customers/<id>/{uploads,invoices,docs}/ materialized by crm.storage.
FILE_FOLDERS = ("uploads", "invoices", "docs")
FILE_SOURCES = ("chat", "whatsapp", "staff")


def customer_file_path(instance, filename):
    """Organize customer files into per-customer folders on disk (Customer File Hub).
    e.g. customers/42/invoices/<filename>. instance.customer_id + instance.folder
    must be set before the file is saved (crm.storage.register_file does this)."""
    folder = instance.folder if instance.folder in FILE_FOLDERS else "uploads"
    cid = instance.customer_id or "unassigned"
    return f"customers/{cid}/{folder}/{filename}"


class CustomerFile(models.Model):
    """Every photo/PDF/invoice on a customer's CRM profile (V2 P-E + File Hub).
    Copied out of the transcript so it survives conversation purges, and mirrored
    to Google Drive via the optional n8n sink on registration."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to=customer_file_path)
    kind = models.CharField(max_length=16, default="photo")  # photo | pdf | other
    folder = models.CharField(max_length=16, default="uploads")  # uploads | invoices | docs
    source = models.CharField(max_length=16, default="staff")    # chat | whatsapp | staff
    original_name = models.CharField(max_length=255, blank=True)
    # Drive mirror link returned by the n8n Google Drive workflow (blank until mirrored).
    drive_url = models.URLField(blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    source_message = models.ForeignKey(
        "chat.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("customer", "sha256")]
        ordering = ["-created_at"]

    @property
    def is_image(self) -> bool:
        return self.kind == "photo"

    def __str__(self):
        return f"File<cust={self.customer_id} {self.folder}/{self.kind}>"


class IntegrationSettings(models.Model):
    """Singleton dashboard-editable config for the outbound n8n Google Drive mirror.
    Default OFF — nothing fires until an operator sets a URL and flips the toggle."""

    n8n_webhook_url = models.URLField(blank=True)
    n8n_shared_secret = models.CharField(max_length=255, blank=True)
    n8n_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "integration settings"

    @classmethod
    def load(cls) -> "IntegrationSettings":
        return cls.objects.first() or cls.objects.create()

    def __str__(self):
        return f"IntegrationSettings<n8n={'on' if self.n8n_enabled else 'off'}>"


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


class PostcodeArea(models.Model):
    """Offline GeoNames SE postal-code table (plan S5/D2) — zero-runtime-network
    geocoding. Loaded via `manage.py import_postcodes SE.zip`."""

    code = models.CharField(max_length=5, unique=True, db_index=True)
    lat = models.FloatField()
    lng = models.FloatField()
    city = models.CharField(max_length=120, blank=True)
    municipality = models.CharField(max_length=120, blank=True)
    county = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return f"{self.code} {self.city}".strip()


class ServiceArea(models.Model):
    """Editable service-area polygon (plan S5/D2). kind=inside is real coverage;
    kind=extension is served but treated as border_review (technician confirms)."""

    KIND_CHOICES = [("inside", "Inside"), ("extension", "Extension")]

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="inside")
    categories = models.ManyToManyField("kb.Category", blank=True, related_name="service_areas")
    polygon = models.JSONField(help_text="Validated GeoJSON Polygon/MultiPolygon geometry (crm.geo.clean_polygon).")
    border_km = models.FloatField(default=10.0)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.kind})"


def _default_previous_installers() -> list[str]:
    return ["Nordland VVS", "Bylunds VVS", "Nordborr i Sundsvall"]


class GeoSettings(models.Model):
    """Singleton service-area config (plan S5/D2). Default OFF — dormant until an
    operator enables it with at least one active ServiceArea."""

    enabled = models.BooleanField(default=False)
    previous_installer_names = models.JSONField(default=_default_previous_installers)
    fallback_contact_url = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "geo settings"

    @classmethod
    def load(cls) -> "GeoSettings":
        return cls.objects.first() or cls.objects.create()

    def __str__(self):
        return f"GeoSettings<{'on' if self.enabled else 'off'}>"


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


class FormButton(models.Model):
    """Owner-configured website-form action buttons (plan S6/D2). The bot never
    invents URLs — a chip with a url is emitted only from an active row here."""

    CATEGORY = [
        ("heat_pump", "Heat pump service"),
        ("water_pump_well", "Water pump / well service"),
        ("water_filtration", "Water filter service"),
        ("quote_request", "Quote request"),
    ]

    category_slug = models.CharField(max_length=32, choices=CATEGORY, unique=True)
    label = models.CharField(max_length=80)
    url = models.URLField()
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"FormButton<{self.category_slug}> {self.label}"
