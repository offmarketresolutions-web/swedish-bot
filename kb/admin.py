"""Admin = the editor for the whole agent architecture (plan §7).

Adding a vendor / machine / PDF, or editing a prompt / brand note / FAQ / chip,
is pure data entry here — it changes agent behaviour with no redeploy. This module
is tuned to make that data entry fast and legible: rich list columns (incl. computed
counts + token estimates), quick-toggle editing, autocomplete FK pickers, inlines for
the i18n + per-machine surfaces, and grouped fieldsets on the heavier forms.
"""
from django.contrib import admin
from django.db.models import Count, Sum
from django.utils.html import format_html

from kb import models


# ── reusable display helpers ─────────────────────────────────────────


def _bool_dot(value, true_label="Active", false_label="Inactive"):
    """Colored status pill using the Nordland palette (blue=on, orange-red=off)."""
    color = "#1a74bf" if value else "#d9370c"
    label = true_label if value else false_label
    return format_html(
        '<span style="display:inline-block;padding:2px 9px;border-radius:10px;'
        'font-size:11px;font-weight:600;color:#fff;background:{};">{}</span>',
        color, label,
    )


# ── inlines ──────────────────────────────────────────────────────────


class MachineDocumentInline(admin.TabularInline):
    model = models.MachineDocument
    extra = 1
    fields = ("lang", "kind", "pdf", "token_estimate", "sha256", "updated_at")
    readonly_fields = ("token_estimate", "sha256", "updated_at")


class MachineNoteInline(admin.StackedInline):
    model = models.MachineNote
    extra = 1
    fields = ("body", "created_by", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


class FAQEntryTextInline(admin.StackedInline):
    model = models.FAQEntryText
    extra = 1
    fields = ("lang", "question", "answer")


class QuickReplyChipTextInline(admin.TabularInline):
    model = models.QuickReplyChipText
    extra = 1
    fields = ("lang", "label")


# ── core taxonomy ────────────────────────────────────────────────────


@admin.register(models.Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "machine_count", "brand_note_count", "active_pill")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "notes", "agent_notes")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)
    list_per_page = 50
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)
    fieldsets = (
        (None, {"fields": ("name", "slug", "is_active")}),
        ("Notes", {
            "fields": ("notes", "agent_notes"),
            "description": "agent_notes is appended to the specialist context for this "
                           "vendor's machines.",
        }),
        ("Meta", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _machines=Count("machines", distinct=True),
            _notes=Count("brand_notes", distinct=True),
        )

    @admin.display(description="Machines", ordering="_machines")
    def machine_count(self, obj):
        return obj._machines

    @admin.display(description="Brand notes", ordering="_notes")
    def brand_note_count(self, obj):
        return obj._notes

    @admin.display(description="Status", ordering="is_active", boolean=False)
    def active_pill(self, obj):
        return _bool_dot(obj.is_active)


@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "machine_count", "order")
    list_editable = ("order",)
    list_filter = ("parent",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("parent",)
    ordering = ("order", "name")
    list_per_page = 50
    list_select_related = ("parent",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _machines=Count("machines", distinct=True),
        )

    @admin.display(description="Machines", ordering="_machines")
    def machine_count(self, obj):
        return obj._machines


@admin.register(models.Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("model_name", "vendor", "category", "document_count",
                    "note_count", "supported_pill")
    list_filter = ("vendor", "category", "is_supported")
    search_fields = ("model_name", "aliases", "search_text", "vendor__name")
    prepopulated_fields = {"slug": ("model_name",)}
    autocomplete_fields = ("vendor", "category")
    ordering = ("vendor__name", "model_name")
    list_per_page = 50
    list_select_related = ("vendor", "category")
    date_hierarchy = "created_at"
    save_on_top = True
    readonly_fields = ("search_text", "created_at")
    inlines = [MachineDocumentInline, MachineNoteInline]
    fieldsets = (
        (None, {"fields": ("vendor", "category", "model_name", "slug")}),
        ("Identification", {
            "fields": ("aliases", "is_supported", "search_text"),
            "description": "search_text is a denormalized lowercased blob rebuilt on save "
                           "and used for trigram identification.",
        }),
        ("Meta", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _docs=Count("documents", distinct=True),
            _notes=Count("notes", distinct=True),
        )

    @admin.display(description="Docs", ordering="_docs")
    def document_count(self, obj):
        return obj._docs

    @admin.display(description="Notes", ordering="_notes")
    def note_count(self, obj):
        return obj._notes

    @admin.display(description="Supported", ordering="is_supported", boolean=False)
    def supported_pill(self, obj):
        return _bool_dot(obj.is_supported, "Supported", "Intake")


@admin.register(models.MachineDocument)
class MachineDocumentAdmin(admin.ModelAdmin):
    list_display = ("machine", "lang", "kind", "token_estimate", "has_text", "updated_at")
    list_filter = ("lang", "kind", "machine__vendor")
    search_fields = ("machine__model_name", "machine__vendor__name", "sha256")
    autocomplete_fields = ("machine",)
    ordering = ("-updated_at",)
    list_per_page = 50
    list_select_related = ("machine", "machine__vendor")
    date_hierarchy = "updated_at"
    save_on_top = True
    readonly_fields = ("parsed_text", "token_estimate", "sha256", "updated_at")
    fieldsets = (
        (None, {"fields": ("machine", "lang", "kind", "pdf")}),
        ("Parsed (read-only)", {
            "fields": ("token_estimate", "sha256", "parsed_text", "updated_at"),
            "classes": ("collapse",),
            "description": "Populated automatically when the PDF is parsed.",
        }),
    )

    @admin.display(description="Parsed", boolean=True)
    def has_text(self, obj):
        return bool(obj.parsed_text)


@admin.register(models.BrandNote)
class BrandNoteAdmin(admin.ModelAdmin):
    list_display = ("vendor", "category", "body_preview", "created_at")
    list_filter = ("vendor", "category")
    search_fields = ("vendor__name", "category__name", "body")
    autocomplete_fields = ("vendor", "category")
    ordering = ("-created_at",)
    list_per_page = 50
    list_select_related = ("vendor", "category")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)

    @admin.display(description="Note")
    def body_preview(self, obj):
        return (obj.body[:80] + "…") if len(obj.body) > 80 else obj.body


@admin.register(models.MachineNote)
class MachineNoteAdmin(admin.ModelAdmin):
    list_display = ("machine", "body_preview", "created_by", "updated_at")
    list_filter = ("machine__vendor", "machine__category")
    search_fields = ("machine__model_name", "machine__vendor__name", "body", "created_by")
    autocomplete_fields = ("machine",)
    ordering = ("-updated_at",)
    list_per_page = 50
    list_select_related = ("machine", "machine__vendor")
    date_hierarchy = "updated_at"
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("machine", "body", "created_by")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Note")
    def body_preview(self, obj):
        return (obj.body[:80] + "…") if len(obj.body) > 80 else obj.body


@admin.register(models.ProblemCategory)
class ProblemCategoryAdmin(admin.ModelAdmin):
    list_display = ("label", "slug", "category")
    list_filter = ("category",)
    search_fields = ("label", "slug", "category__name")
    autocomplete_fields = ("category",)
    ordering = ("category__name", "label")
    list_per_page = 50
    list_select_related = ("category",)


# ── i18n content surfaces ────────────────────────────────────────────


@admin.register(models.FAQEntry)
class FAQEntryAdmin(admin.ModelAdmin):
    list_display = ("key", "category", "lang_count", "order")
    list_editable = ("order",)
    list_filter = ("category",)
    search_fields = ("key", "category__name", "texts__question", "texts__answer")
    autocomplete_fields = ("category",)
    ordering = ("category__name", "order", "key")
    list_per_page = 50
    list_select_related = ("category",)
    inlines = [FAQEntryTextInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _langs=Count("texts", distinct=True),
        )

    @admin.display(description="Languages", ordering="_langs")
    def lang_count(self, obj):
        return obj._langs


@admin.register(models.SiteFAQ)
class SiteFAQAdmin(admin.ModelAdmin):
    # Company FAQ scraped from the public site; fed to the agent via semantic search.
    list_display = ("question", "topic", "lang", "is_active", "updated_at")
    list_editable = ("is_active",)
    list_filter = ("topic", "lang", "is_active")
    search_fields = ("question", "answer")
    prepopulated_fields = {"slug": ("question",)}
    ordering = ("topic", "question")
    list_per_page = 50
    date_hierarchy = "updated_at"
    save_on_top = True
    readonly_fields = ("updated_at",)
    fieldsets = (
        (None, {"fields": ("topic", "slug", "lang", "is_active")}),
        ("Content", {"fields": ("question", "answer")}),
        ("Source", {"fields": ("source_url", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(models.GenericGuide)
class GenericGuideAdmin(admin.ModelAdmin):
    # filter kind=best_practice for the Best Practices view.
    list_display = ("key", "category", "kind", "lang", "body_preview")
    list_filter = ("kind", "lang", "category")
    search_fields = ("key", "category__name", "body")
    autocomplete_fields = ("category",)
    ordering = ("category__name", "key", "lang")
    list_per_page = 50
    list_select_related = ("category",)
    fieldsets = (
        (None, {"fields": ("category", "key", "kind", "lang")}),
        ("Content", {"fields": ("body",)}),
    )

    @admin.display(description="Body")
    def body_preview(self, obj):
        return (obj.body[:80] + "…") if len(obj.body) > 80 else obj.body


@admin.register(models.QuickReplyChip)
class QuickReplyChipAdmin(admin.ModelAdmin):
    list_display = ("value", "intake_step", "category", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("intake_step", "category", "is_active")
    search_fields = ("intake_step", "value", "category__name", "texts__label")
    autocomplete_fields = ("category",)
    ordering = ("intake_step", "order")
    list_per_page = 50
    list_select_related = ("category",)
    inlines = [QuickReplyChipTextInline]


# ── runtime / agent config ───────────────────────────────────────────


@admin.register(models.AgentPrompt)
class AgentPromptAdmin(admin.ModelAdmin):
    list_display = ("role", "model_id", "prompt_version", "thinking_enabled",
                    "temperature", "is_active", "updated_at")
    # role is the natural first column + unique, so it is NOT editable; model_id is a
    # safe quick-swap, is_active a safe quick-toggle.
    list_editable = ("model_id", "is_active")
    list_filter = ("is_active", "thinking_enabled", "role")
    search_fields = ("role", "model_id", "body", "language_directive")
    ordering = ("role",)
    list_per_page = 50
    date_hierarchy = "updated_at"
    save_on_top = True
    readonly_fields = ("updated_at",)
    fieldsets = (
        ("Prompt", {
            "fields": ("role", "body", "language_directive"),
            "description": "body is the editable system prompt. language_directive is an "
                           "appended {language} block — use the {locale} placeholder.",
        }),
        ("Model & runtime", {
            "fields": ("model_id", "temperature", "thinking_enabled", "thinking_budget",
                       "max_output_tokens"),
            "description": "model_id is the single source of truth for which model this "
                           "agent uses. Null/0 runtime values fall back to code defaults; "
                           "thinking_budget is Gemini thinking tokens (0 = off).",
        }),
        ("Status", {"fields": ("prompt_version", "is_active", "updated_at")}),
    )

    @admin.display(description="Status", ordering="is_active", boolean=False)
    def active_pill(self, obj):
        return _bool_dot(obj.is_active)


@admin.register(models.PolicyDocument)
class PolicyDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "lang", "token_estimate", "active_pill", "updated_at")
    list_filter = ("kind", "lang", "is_active")
    search_fields = ("title", "sha256")
    ordering = ("kind", "title")
    list_per_page = 50
    date_hierarchy = "updated_at"
    save_on_top = True
    readonly_fields = ("parsed_text", "token_estimate", "sha256", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "kind", "lang", "is_active")}),
        ("File", {"fields": ("pdf",)}),
        ("Citation", {
            "fields": ("cite_on",),
            "description": 'When to cite this doc, e.g. '
                           '["booking","quote","maintenance","consumer_rights"].',
        }),
        ("Parsed (read-only)", {
            "fields": ("token_estimate", "sha256", "parsed_text", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Status", ordering="is_active", boolean=False)
    def active_pill(self, obj):
        return _bool_dot(obj.is_active)


@admin.register(models.RoutingRule)
class RoutingRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "action", "match_category", "match_problem_category",
                    "match_severity", "match_keyword", "priority", "is_active")
    list_editable = ("priority", "is_active")
    list_filter = ("action", "is_active", "match_severity", "match_category")
    search_fields = ("name", "match_keyword", "match_category__name",
                     "match_problem_category__label")
    autocomplete_fields = ("match_category", "match_problem_category")
    ordering = ("-priority", "id")
    list_per_page = 50
    list_select_related = ("match_category", "match_problem_category")
    save_on_top = True
    fieldsets = (
        (None, {"fields": ("name", "action", "priority", "is_active")}),
        ("Match conditions", {
            "fields": ("match_category", "match_problem_category", "match_severity",
                       "match_keyword"),
            "description": "When all set conditions match, the action is taken. "
                           "Higher-priority rules are checked first.",
        }),
    )
