"""Knowledge base = the editable agent architecture (plan §7/§8).

Adding a vendor / machine / PDF, or editing a prompt / brand note / FAQ / chip,
is pure data entry in the admin — it changes agent behaviour with no redeploy.
"""
from __future__ import annotations

from django.db import models

from core.enums import AGENT_ROLE_CHOICES, DOC_KIND_CHOICES, LANG_CHOICES


class Vendor(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    notes = models.TextField(blank=True, help_text="Short brand-level note.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Category(models.Model):
    """Equipment category tree: heat_pump > {water_to_water, air_to_water,
    air_to_air, exhaust_air}, water_pump_well, water_filtration. Extensible."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.parent} › {self.name}" if self.parent_id else self.name


class Machine(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="machines")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="machines")
    model_name = models.CharField(max_length=160)
    aliases = models.JSONField(default=list, blank=True, help_text="Alternate names/SKUs.")
    slug = models.SlugField(max_length=180, unique=True)
    # Denormalized, lowercased blob for trigram identification (built on save).
    search_text = models.CharField(max_length=512, editable=False, default="")
    is_supported = models.BooleanField(
        default=True, help_text="We service this and have a manual; else intelligent-intake."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("vendor", "model_name")]
        ordering = ["vendor__name", "model_name"]

    def save(self, *args, **kwargs):
        parts = [self.model_name, self.vendor.name if self.vendor_id else ""]
        parts += [str(a) for a in (self.aliases or [])]
        self.search_text = " ".join(p for p in parts if p).lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.vendor.name} {self.model_name}"


class MachineDocument(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="documents")
    lang = models.CharField(max_length=5, choices=LANG_CHOICES, default="en")
    kind = models.CharField(max_length=16, choices=DOC_KIND_CHOICES, default="manual")
    pdf = models.FileField(upload_to="manuals/")
    parsed_text = models.TextField(blank=True)
    token_estimate = models.IntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.machine} [{self.lang}/{self.kind}]"


class BrandNote(models.Model):
    """Verified internal experience notes, injected into the specialist context."""

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="brand_notes")
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="brand_notes"
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Note<{self.vendor.name}{'/' + self.category.slug if self.category_id else ''}>"


class ProblemCategory(models.Model):
    """Controlled problem-type vocab per equipment category. Router emits the slug."""

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="problem_categories")
    slug = models.SlugField(max_length=64)
    label = models.CharField(max_length=120)

    class Meta:
        unique_together = [("category", "slug")]
        verbose_name_plural = "problem categories"

    def __str__(self):
        return f"{self.category.slug}/{self.slug}"


# ── i18n content (per-language rows, fallback to en) ──────────────────


def pick_text(manager, lang: str, default_lang: str = "en"):
    row = manager.filter(lang=lang).first()
    if row is None and lang != default_lang:
        row = manager.filter(lang=default_lang).first()
    return row


class FAQEntry(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="faqs")
    key = models.SlugField(max_length=64)
    order = models.IntegerField(default=0)

    class Meta:
        unique_together = [("category", "key")]
        ordering = ["order"]

    def text(self, lang="en"):
        return pick_text(self.texts, lang)

    def __str__(self):
        return f"{self.category.slug}/{self.key}"


class FAQEntryText(models.Model):
    faq = models.ForeignKey(FAQEntry, on_delete=models.CASCADE, related_name="texts")
    lang = models.CharField(max_length=5, choices=LANG_CHOICES)
    question = models.TextField()
    answer = models.TextField()

    class Meta:
        unique_together = [("faq", "lang")]


class GenericGuide(models.Model):
    """Model-independent safe troubleshooting guide, by category + language."""

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="guides")
    key = models.SlugField(max_length=64)
    lang = models.CharField(max_length=5, choices=LANG_CHOICES, default="en")
    body = models.TextField()

    class Meta:
        unique_together = [("category", "key", "lang")]

    def __str__(self):
        return f"{self.category.slug}/{self.key} [{self.lang}]"


class QuickReplyChip(models.Model):
    """A preloaded tappable answer for an intake step (plan §6.1)."""

    intake_step = models.CharField(max_length=32)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.CASCADE, related_name="chips"
    )
    value = models.CharField(max_length=120, help_text="Value sent when tapped.")
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["intake_step", "order"]

    def label(self, lang="en"):
        row = pick_text(self.texts, lang)
        return row.label if row else self.value

    def __str__(self):
        return f"{self.intake_step}:{self.value}"


class QuickReplyChipText(models.Model):
    chip = models.ForeignKey(QuickReplyChip, on_delete=models.CASCADE, related_name="texts")
    lang = models.CharField(max_length=5, choices=LANG_CHOICES)
    label = models.CharField(max_length=120)

    class Meta:
        unique_together = [("chip", "lang")]


class AgentPrompt(models.Model):
    """The editable system-prompt + model id per agent role. model_id here is the
    single source of truth for which model an agent uses (plan §7, resolves crit 0.3)."""

    role = models.CharField(max_length=32, choices=AGENT_ROLE_CHOICES, unique=True)
    body = models.TextField()
    language_directive = models.TextField(
        blank=True, help_text="Appended {language} block; use {locale} placeholder."
    )
    model_id = models.CharField(max_length=64)
    prompt_version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.role} (v{self.prompt_version}, {self.model_id})"
