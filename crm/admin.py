from django.contrib import admin

from crm import models


class CustomerFileInline(admin.TabularInline):
    model = models.CustomerFile
    extra = 0
    readonly_fields = ("file", "kind", "sha256", "created_at")


@admin.register(models.Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "postal_code", "consent_to_contact", "created_at")
    search_fields = ("name", "phone", "email")
    inlines = [CustomerFileInline]


class LeadDeliveryInline(admin.TabularInline):
    model = models.LeadDelivery
    extra = 0
    readonly_fields = ("sink", "status", "attempts", "last_error", "updated_at")


@admin.register(models.Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("id", "manufacturer", "model", "severity", "decision", "resolved",
                    "service_recommended", "status", "created_at")
    list_filter = ("severity", "decision", "status", "resolved", "service_recommended")
    search_fields = ("manufacturer", "model", "error_code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(models.ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "escalation_reason", "created_at")
    inlines = [LeadDeliveryInline]
    readonly_fields = ("idempotency_key", "payload_json", "created_at")
