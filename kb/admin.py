"""Admin = the editor for the whole agent architecture (plan §7)."""
from django.contrib import admin

from kb import models


class MachineDocumentInline(admin.TabularInline):
    model = models.MachineDocument
    extra = 1


class MachineNoteInline(admin.TabularInline):
    model = models.MachineNote
    extra = 1


@admin.register(models.Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "order")
    prepopulated_fields = {"slug": ("name",)}
    list_filter = ("parent",)


@admin.register(models.Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("model_name", "vendor", "category", "is_supported")
    list_filter = ("vendor", "category", "is_supported")
    search_fields = ("model_name", "aliases", "search_text")
    prepopulated_fields = {"slug": ("model_name",)}
    inlines = [MachineDocumentInline, MachineNoteInline]


@admin.register(models.MachineDocument)
class MachineDocumentAdmin(admin.ModelAdmin):
    list_display = ("machine", "lang", "kind", "token_estimate", "updated_at")
    list_filter = ("lang", "kind")


@admin.register(models.BrandNote)
class BrandNoteAdmin(admin.ModelAdmin):
    list_display = ("vendor", "category", "created_at")
    list_filter = ("vendor", "category")


@admin.register(models.ProblemCategory)
class ProblemCategoryAdmin(admin.ModelAdmin):
    list_display = ("category", "slug", "label")
    list_filter = ("category",)


class FAQEntryTextInline(admin.TabularInline):
    model = models.FAQEntryText
    extra = 1


@admin.register(models.FAQEntry)
class FAQEntryAdmin(admin.ModelAdmin):
    list_display = ("category", "key", "order")
    list_filter = ("category",)
    inlines = [FAQEntryTextInline]


@admin.register(models.GenericGuide)
class GenericGuideAdmin(admin.ModelAdmin):
    list_display = ("category", "key", "lang")
    list_filter = ("category", "lang")


class QuickReplyChipTextInline(admin.TabularInline):
    model = models.QuickReplyChipText
    extra = 1


@admin.register(models.QuickReplyChip)
class QuickReplyChipAdmin(admin.ModelAdmin):
    list_display = ("intake_step", "value", "category", "order", "is_active")
    list_filter = ("intake_step", "category", "is_active")
    inlines = [QuickReplyChipTextInline]


@admin.register(models.AgentPrompt)
class AgentPromptAdmin(admin.ModelAdmin):
    list_display = ("role", "model_id", "prompt_version", "is_active", "updated_at")
    list_filter = ("is_active",)


@admin.register(models.PolicyDocument)
class PolicyDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "lang", "is_active", "updated_at")
    list_filter = ("kind", "lang", "is_active")
    search_fields = ("title",)
