"""CRM staff console — Nordland VVS.

Session is the canonical reporting row, so SessionAdmin is the workhorse: rich
list view, deep filters, and read-only AI-derived columns that admin edits must
never clobber. Customer is PII but staff-only, so we surface it here (never on a
public surface). LeadDelivery gets a colored status so the on-call eye can scan
the delivery queue at a glance.

Only fields that exist on crm.models are referenced.
"""
from __future__ import annotations

from django.contrib import admin
from django.db.models import Count
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

from crm import models


# --------------------------------------------------------------------------- #
# Inlines
# --------------------------------------------------------------------------- #
class CustomerFileInline(admin.TabularInline):
    model = models.CustomerFile
    extra = 0
    can_delete = False
    fields = ("file", "kind", "sha256_short", "source_message", "created_at")
    readonly_fields = ("file", "kind", "sha256_short", "source_message", "created_at")
    show_change_link = True

    @admin.display(description="SHA-256")
    def sha256_short(self, obj):
        return (obj.sha256 or "")[:12] or "—"

    def has_add_permission(self, request, obj=None):
        return False


class SessionInline(admin.TabularInline):
    """Sessions belonging to a customer — quick context on the customer page."""
    model = models.Session
    extra = 0
    fk_name = "customer"
    fields = ("manufacturer", "model", "severity", "status", "resolved",
              "service_recommended", "created_at")
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class ServiceRequestInline(admin.TabularInline):
    """Leads created off a session (FK-related: ServiceRequest.session)."""
    model = models.ServiceRequest
    extra = 0
    fields = ("escalation_reason", "idempotency_key", "created_at")
    readonly_fields = ("idempotency_key", "created_at")
    show_change_link = True


class LeadDeliveryInline(admin.TabularInline):
    """Delivery attempts per service request (FK-related: LeadDelivery.service_request)."""
    model = models.LeadDelivery
    extra = 0
    fields = ("sink", "colored_status", "attempts", "last_error", "updated_at")
    readonly_fields = ("sink", "colored_status", "attempts", "last_error", "updated_at")
    show_change_link = True

    @admin.display(description="Status")
    def colored_status(self, obj):
        return _status_badge(obj.status)

    def has_add_permission(self, request, obj=None):
        return False


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
_STATUS_COLORS = {
    "success": "#1a8a3a",   # green
    "pending": "#b8860b",   # amber
    "skipped": "#6b7280",   # grey
    "failed": "#d9370c",    # Nordland action orange-red
}


def _status_badge(status: str):
    color = _STATUS_COLORS.get(status, "#1c1e20")
    return format_html(
        '<b style="color:{};">{}</b>',
        color,
        (status or "—").title(),
    )


def _bool_dash(value):
    """Tri-state booleans (resolved / service_recommended) render as ✓ / ✗ / —."""
    if value is None:
        return "—"
    return "✓" if value else "✗"


# --------------------------------------------------------------------------- #
# Customer
# --------------------------------------------------------------------------- #
@admin.register(models.Customer)
class CustomerAdmin(admin.ModelAdmin):
    save_on_top = True
    list_per_page = 50
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    list_display = ("name", "phone", "email", "postal_code", "city",
                    "consent_to_contact", "session_count", "created_at")
    list_filter = ("consent_to_contact", "city", "property_type")
    search_fields = ("name", "phone", "email", "postal_code", "city")
    readonly_fields = ("phone_hash", "created_at")
    inlines = [SessionInline, CustomerFileInline]

    fieldsets = (
        ("Contact (PII — staff only)", {
            "fields": ("name", "phone", "email", "address", "postal_code", "city"),
        }),
        ("Property & consent", {
            "fields": ("property_type", "consent_to_contact"),
        }),
        ("System", {
            "classes": ("collapse",),
            "fields": ("phone_hash", "created_at"),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _session_count=Count("sessions", distinct=True)
        )

    @admin.display(description="Sessions", ordering="_session_count")
    def session_count(self, obj):
        return getattr(obj, "_session_count", obj.sessions.count())


# --------------------------------------------------------------------------- #
# Session — the canonical reporting row
# --------------------------------------------------------------------------- #
@admin.register(models.Session)
class SessionAdmin(admin.ModelAdmin):
    save_on_top = True
    list_per_page = 50
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("customer", "category", "conversation")

    list_display = ("id", "equipment", "category", "severity", "status",
                    "resolved_icon", "service_recommended_icon", "created_at")
    list_filter = ("severity", "status", "resolved", "service_recommended",
                   "category", "decision")
    search_fields = ("customer__name", "customer__phone", "customer__email",
                     "manufacturer", "model", "error_code", "serial")
    readonly_fields = ("confidence_score", "ai_summary", "created_at", "updated_at",
                       "conversation_link")
    autocomplete_fields = ("customer",)
    inlines = [ServiceRequestInline]

    fieldsets = (
        ("Equipment", {
            "fields": ("manufacturer", "model", "serial", "error_code",
                       "machine", "category", "problem_category"),
        }),
        ("Assessment", {
            "fields": ("severity", "decision", "state", "status",
                       "resolved", "service_recommended", "booking_requested",
                       "troubleshooting_performed", "reply_turns"),
        }),
        ("Customer", {
            "fields": ("customer",),
        }),
        ("AI-derived (read-only — admin edits above are never overwritten)", {
            "fields": ("confidence_score", "ai_summary", "conversation_link"),
        }),
        ("System", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="Equipment", ordering="manufacturer")
    def equipment(self, obj):
        label = " ".join(p for p in (obj.manufacturer, obj.model) if p).strip()
        if obj.error_code:
            label = f"{label} [{obj.error_code}]" if label else f"[{obj.error_code}]"
        return label or "—"

    @admin.display(description="Resolved", ordering="resolved")
    def resolved_icon(self, obj):
        return _bool_dash(obj.resolved)

    @admin.display(description="Service?", ordering="service_recommended")
    def service_recommended_icon(self, obj):
        return _bool_dash(obj.service_recommended)

    @admin.display(description="Conversation")
    def conversation_link(self, obj):
        if not obj.conversation_id:
            return "—"
        # chat.Conversation may not be registered in the admin; degrade gracefully.
        try:
            url = reverse("admin:chat_conversation_change", args=[obj.conversation_id])
        except NoReverseMatch:
            return format_html("Conversation #{}", obj.conversation_id)
        return format_html('<a href="{}" target="_blank">View transcript →</a>', url)


# --------------------------------------------------------------------------- #
# ServiceRequest
# --------------------------------------------------------------------------- #
@admin.register(models.ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    save_on_top = True
    list_per_page = 50
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("session",)

    list_display = ("id", "session", "escalation_reason", "delivery_summary", "created_at")
    list_filter = ("escalation_reason",)
    search_fields = ("idempotency_key", "escalation_reason",
                     "session__manufacturer", "session__model")
    readonly_fields = ("idempotency_key", "payload_json", "created_at")
    autocomplete_fields = ("session",)
    inlines = [LeadDeliveryInline]

    @admin.display(description="Deliveries")
    def delivery_summary(self, obj):
        rows = obj.deliveries.all()
        if not rows:
            return "—"
        return format_html(
            " ".join("{}" for _ in rows),
            *[format_html("{}:{} ", r.sink, _status_badge(r.status)) for r in rows],
        )


# --------------------------------------------------------------------------- #
# LeadDelivery
# --------------------------------------------------------------------------- #
@admin.register(models.LeadDelivery)
class LeadDeliveryAdmin(admin.ModelAdmin):
    save_on_top = True
    list_per_page = 50
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("service_request",)

    list_display = ("id", "service_request", "sink", "colored_status",
                    "attempts", "short_error", "created_at")
    list_filter = ("status", "sink")
    search_fields = ("sink", "last_error",
                     "service_request__idempotency_key")
    readonly_fields = ("attempts", "created_at", "updated_at")
    autocomplete_fields = ("service_request",)

    @admin.display(description="Status", ordering="status")
    def colored_status(self, obj):
        return _status_badge(obj.status)

    @admin.display(description="Last error")
    def short_error(self, obj):
        if not obj.last_error:
            return "—"
        return (obj.last_error[:60] + "…") if len(obj.last_error) > 60 else obj.last_error


# --------------------------------------------------------------------------- #
# CustomerFile
# --------------------------------------------------------------------------- #
@admin.register(models.CustomerFile)
class CustomerFileAdmin(admin.ModelAdmin):
    save_on_top = True
    list_per_page = 50
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("customer",)

    list_display = ("id", "customer", "kind", "sha256_short", "created_at")
    list_filter = ("kind",)
    search_fields = ("customer__name", "customer__phone", "sha256")
    readonly_fields = ("sha256", "created_at")
    autocomplete_fields = ("customer",)

    @admin.display(description="SHA-256", ordering="sha256")
    def sha256_short(self, obj):
        return (obj.sha256 or "")[:12] or "—"
