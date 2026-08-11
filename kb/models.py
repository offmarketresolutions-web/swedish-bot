"""Knowledge base = the editable agent architecture (plan §7/§8).

Adding a vendor / machine / PDF, or editing a prompt / brand note / FAQ / chip,
is pure data entry in the admin — it changes agent behaviour with no redeploy.
"""
from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from core.enums import AGENT_ROLE_CHOICES, DOC_KIND_CHOICES, LANG_CHOICES, SEVERITY_CHOICES


def manual_upload_path(instance, filename):
    """Self-organize manuals by vendor/machine so admin upload/replace is predictable
    (V2 §D). e.g. manuals/ivt/geo-600c/<filename>."""
    v = instance.machine.vendor.slug if instance.machine_id else "misc"
    m = instance.machine.slug if instance.machine_id else "misc"
    return f"manuals/{v}/{m}/{filename}"


class Vendor(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    notes = models.TextField(blank=True, help_text="Short brand-level note.")
    agent_notes = models.TextField(
        blank=True,
        help_text="Per-vendor guidance appended to the specialist for this vendor's machines (V2).")
    official_domains = models.JSONField(
        default=list, blank=True,
        help_text="Allowlist of official manufacturer hostnames (e.g. ['nibe.eu','nibe.se']). "
                  "chat.consult.consult_web will only digest web sources from these domains; "
                  "empty means no web research for this brand.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


CATEGORY_GROUP_CHOICES = [
    ("heat", "Heat"), ("air", "Air"), ("water", "Water"),
    ("hybrid", "Hybrid"), ("other", "Other"),
]


class Category(models.Model):
    """Equipment category tree: heat_pump > {water_to_water, air_to_water,
    air_to_air, exhaust_air}, water_pump_well, water_filtration. Extensible.
    `group` is the top-level KB grouping shown to staff (Heat/Air/Water/Hybrid/Other)."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    group = models.CharField(max_length=12, choices=CATEGORY_GROUP_CHOICES, default="other",
                             help_text="Top-level KB grouping (Heat/Air/Water/Hybrid/Other).")
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
        # trigram index created in migration 0002 (after the pg_trgm extension);
        # declared here so model state matches migration state.
        indexes = [
            GinIndex(name="kb_machine_search_trgm", fields=["search_text"],
                     opclasses=["gin_trgm_ops"]),
        ]

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
    pdf = models.FileField(upload_to=manual_upload_path)
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
    # Approval + general-knowledge metadata (V2 §D2 — extends FAQEntry rather than a
    # new model). default=True keeps existing hand-authored rows live; imported rows
    # explicitly land unapproved (README: "review required before production").
    is_approved = models.BooleanField(default=True)
    source_type = models.CharField(max_length=64, blank=True)
    source_id = models.CharField(max_length=32, blank=True, db_index=True,
                                  help_text="External id (e.g. FAQ import faq_id) for idempotent re-import.")
    applicable_subtypes = models.JSONField(default=list, blank=True,
                                            help_text="Category-leaf slugs this entry applies to; empty = all.")
    onset_type = models.CharField(max_length=12, blank=True, help_text="any|sudden|long_term")
    safe_customer_checks = models.TextField(blank=True)
    service_trigger = models.TextField(blank=True)
    keywords = models.JSONField(default=list, blank=True)
    manufacturer = models.ForeignKey(
        Vendor, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Optional — narrows this entry to one manufacturer.")
    exclusions = models.TextField(blank=True)

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
    """Model-independent safe guidance, by category + language. `kind` lets the admin
    keep FAQs, generic guides, and best-practices as one editable surface (V2 P-D)."""

    GUIDE_KINDS = [("faq", "FAQ"), ("guide", "Guide"), ("best_practice", "Best practice")]

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="guides")
    key = models.SlugField(max_length=64)
    kind = models.CharField(max_length=16, choices=GUIDE_KINDS, default="guide")
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


class Tool(models.Model):
    """The 'MCP-style' tool registry (V2 S9): a capability an agent can be given
    with one click. `handler_ref` is a dotted path to the real function today —
    this model does not execute anything itself, it only records which agents
    are allowed to use which capability. The orchestrator-side consumer is
    kb.tooling.enabled_tools_for_role (read-only helper; wiring is a separate
    conversation-core task)."""

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=16, default="internal",
                             help_text="Capability kind, e.g. 'internal' (today) or 'mcp' (future).")
    handler_ref = models.CharField(max_length=200, blank=True,
                                    help_text="Dotted path to the function/module implementing this tool.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AgentPrompt(models.Model):
    """The editable system-prompt + model id per agent role. model_id here is the
    single source of truth for which model an agent uses (plan §7, resolves crit 0.3)."""

    role = models.CharField(max_length=32, choices=AGENT_ROLE_CHOICES, unique=True)
    body = models.TextField()
    language_directive = models.TextField(
        blank=True, help_text="Appended {language} block; use {locale} placeholder."
    )
    model_id = models.CharField(max_length=64)
    # Editable runtime config (V2 P-C). Null/0 => use code defaults.
    temperature = models.FloatField(null=True, blank=True)
    thinking_enabled = models.BooleanField(default=False)
    thinking_budget = models.IntegerField(default=0, help_text="Gemini thinking tokens (0 = off).")
    max_output_tokens = models.IntegerField(null=True, blank=True)
    # FAQ / guide injection into this agent's knowledge context (specialist).
    inject_faq = models.BooleanField(
        default=True, help_text="Inject category FAQ/guides into the specialist context.")
    faq_categories = models.ManyToManyField(
        Category, blank=True, related_name="+",
        help_text="If set, inject FAQ only from these categories; empty = the matched machine's category.")
    prompt_version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Freeform owner notes (V2 S9). Not yet injected into any prompt — the
    # conversation-core agent owns wiring this into context assembly; this is
    # just the field + editor. HOOK: chat/prompts.py config_for(role) is where
    # per-role context is assembled today (see AgentPrompt.inject_faq handling)
    # — that is the natural place to splice common_issues in later.
    common_issues = models.TextField(
        blank=True,
        help_text="Freeform notes: common issues & solutions staff have seen for this agent.")
    tools = models.ManyToManyField(
        Tool, blank=True, related_name="agents",
        help_text="Tools this agent may call ('MCP-style' 1-click enable).")

    def __str__(self):
        return f"{self.role} (v{self.prompt_version}, {self.model_id})"


class AgentGuardrail(models.Model):
    """Staff-authored guardrail rules injected per agent (ADD-ONLY). These AUGMENT —
    never weaken — the hard-coded safety baseline: the _FORBIDDEN keyword veto and the
    safety classifier still run in code on every reply regardless of what's set here
    (the LLM is never the security boundary). Read fresh every turn → a save is live
    immediately, no redeploy."""

    role = models.CharField(max_length=32, choices=AGENT_ROLE_CHOICES)
    rule = models.TextField(help_text="One guardrail rule, in plain language.")
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role", "order", "id"]

    def __str__(self):
        return f"{self.role}: {self.rule[:40]}"


class FlowConfig(models.Model):
    """The editable visual flow (the canvas), stored as one JSON graph (singleton).

    Ponytail: one row, one JSON field — no per-node/edge tables. `agent` steps just
    reference an AgentPrompt by role, so the prompt/model stays the single source of
    truth and edits there are already live in production. The hardcoded safety
    guardrails live in code and are NOT configurable here — the canvas can arrange
    and document the flow + collect-fields, never weaken the safety backstop.
    """

    graph = models.JSONField(default=dict, help_text="{nodes:[...], edges:[...]}")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        n = len((self.graph or {}).get("nodes", []))
        return f"FlowConfig(#{self.pk}, {n} steps)"


class MachineNote(models.Model):
    """Per-machine experience notes, auto-injected into the specialist context (V2).
    Staff-authored; shown as a Notes tab in the admin. Canonical owner of machine
    notes (one model — crit 1.0)."""

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="notes")
    body = models.TextField()
    created_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Note<{self.machine}>"


class PolicyDocument(models.Model):
    """Company-level terms/policy docs (Konsumentvillkor). Cited when routing to
    booking/quote/maintenance + consumer-rights — NEVER injected into the
    troubleshooting/specialist context (separate surface = smaller injection blast)."""

    POLICY_KINDS = [
        ("vvs_installation", "VVS installation terms"),
        ("groundwork", "Groundwork / excavation terms"),
        ("heatpump_brine", "Heat pump brine-water villa terms"),
        ("well_drilling", "Energy well drilling terms"),
        ("other", "Other policy"),
    ]
    kind = models.CharField(max_length=32, choices=POLICY_KINDS)
    title = models.CharField(max_length=200)
    lang = models.CharField(max_length=5, choices=LANG_CHOICES, default="sv")
    pdf = models.FileField(upload_to="terms/")
    parsed_text = models.TextField(blank=True)
    token_estimate = models.IntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    cite_on = models.JSONField(default=list, blank=True,
                               help_text='e.g. ["booking","quote","maintenance","consumer_rights"]')
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} [{self.kind}]"


class RoutingRule(models.Model):
    """Admin-configurable rule (V2 P-D): when the conditions match, take this routing
    action (e.g. send the customer straight to a maintenance/service request).
    Consulted by the orchestrator right after identification."""

    ACTIONS = [
        ("troubleshoot", "Troubleshoot normally"),
        ("route_maintenance", "Route to maintenance / service request"),
        ("urgent_contact", "Urgent — escalate immediately"),
    ]
    name = models.CharField(max_length=120)
    match_category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    match_problem_category = models.ForeignKey(
        ProblemCategory, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    match_severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, blank=True)
    match_keyword = models.CharField(max_length=120, blank=True,
                                     help_text="Substring in the problem text (case-insensitive).")
    action = models.CharField(max_length=24, choices=ACTIONS, default="route_maintenance")
    priority = models.IntegerField(default=0, help_text="Higher priority rules are checked first.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-priority", "id"]

    def __str__(self):
        return f"{self.name} -> {self.action}"


class SiteFAQ(models.Model):
    """Company FAQ imported from nordlandvvs.se (the public 'Vanliga frågor'). Not
    machine-specific — general questions (troubleshooting, ROT, payment, legal,
    leakage, DIY). Surfaced to staff + fed to the agent via semantic search."""

    topic = models.CharField(max_length=64, blank=True, help_text="Source topic (frågeämne) slug.")
    slug = models.SlugField(max_length=200, unique=True)
    question = models.CharField(max_length=300)
    answer = models.TextField()
    lang = models.CharField(max_length=5, choices=LANG_CHOICES, default="sv")
    source_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["topic", "question"]
        verbose_name = "Site FAQ"

    def __str__(self):
        return self.question[:70]


class Embedding(models.Model):
    """Persisted per-scope embedding vector (S10) — replaces the volatile
    Django-cache vectors in kb/semantic.py's `_corpus_vectors` for registry-declared
    corpora, so a cold cache no longer means a full re-embed on the next request.

    Keyed by (source_model, object_id, lang, scope): the same row can carry a
    different vector per agent-role scope in principle (a scope tag, not a second
    source of truth for the text itself — the text always comes from the source
    row). `content_hash` makes `build_embeddings` idempotent and incremental: a row
    is only re-embedded when its text actually changed.
    """

    source_model = models.CharField(max_length=32, help_text="e.g. FAQEntry, GenericGuide, SiteFAQ.")
    object_id = models.PositiveIntegerField()
    lang = models.CharField(max_length=5, choices=LANG_CHOICES, default="en")
    scope = models.CharField(max_length=32, help_text="Agent role this embedding is scoped to (kb.corpus registry).")
    content_hash = models.CharField(max_length=64)
    vector = models.JSONField(help_text="768-float embedding vector (core.constants.EMBED_DIM).")
    model_name = models.CharField(max_length=64, help_text="Embedding model that produced this vector.")
    embedded_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("source_model", "object_id", "lang", "scope")]
        indexes = [models.Index(fields=["scope", "source_model"])]

    def __str__(self):
        return f"Embedding<{self.source_model}:{self.object_id}/{self.lang}@{self.scope}>"
