"""ModelForms for the create-everything dashboard (KB brands/machines + CRM customers).

Kept deliberately small: only real model fields, with auto-slug where the model
requires a unique slug the staff user shouldn't have to hand-type."""
from __future__ import annotations

from django import forms
from django.utils.text import slugify

from crm.models import Customer
from kb.models import (BrandNote, Category, FAQEntry, FAQEntryText, LANG_CHOICES,
                       Machine, SiteFAQ, Vendor)

# Shared Tailwind input styling so forms match the existing shell.
_INPUT = ("w-full rounded-md border border-nl-border bg-white px-3 py-2 text-sm "
          "focus:border-nl-primary focus:outline-none focus:ring-1 focus:ring-nl-primary")
_CHECK = "h-4 w-4 rounded border-nl-border text-nl-primary focus:ring-nl-primary"


def _style(fields, *, area=()):
    """Apply the shared input class to every widget (textarea/checkbox aware)."""
    for name, field in fields.items():
        w = field.widget
        if isinstance(w, forms.CheckboxInput):
            w.attrs.setdefault("class", _CHECK)
        elif name in area or isinstance(w, forms.Textarea):
            w.attrs.setdefault("class", _INPUT)
            w.attrs.setdefault("rows", 3)
        else:
            w.attrs.setdefault("class", _INPUT)


def _unique_slug(model, base: str, *, exclude_pk=None) -> str:
    """slugify(base) with a numeric suffix if needed to satisfy the unique slug."""
    base = slugify(base) or "item"
    slug, n = base, 2
    qs = model.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["name", "notes", "agent_notes", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields, area=("notes", "agent_notes"))

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.slug:
            obj.slug = _unique_slug(Vendor, obj.name, exclude_pk=obj.pk)
        if commit:
            obj.save()
        return obj


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent", "group", "order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].required = False
        self.fields["parent"].help_text = "Optional — a sub-type rolls up to its parent (e.g. Air-to-air → Heat pump)."
        _style(self.fields)

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.slug:
            obj.slug = _unique_slug(Category, obj.name, exclude_pk=obj.pk)
        if commit:
            obj.save()
        return obj


class MachineForm(forms.ModelForm):
    # aliases is a JSONField(list); expose it as a comma-separated text box.
    aliases_text = forms.CharField(
        required=False, label="Aliases",
        help_text="Comma-separated alternate names / SKUs.",
    )

    class Meta:
        model = Machine
        fields = ["vendor", "category", "model_name", "is_supported"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["aliases_text"].initial = ", ".join(self.instance.aliases or [])
        _style(self.fields)

    def clean_aliases_text(self):
        raw = self.cleaned_data.get("aliases_text", "")
        return [a.strip() for a in raw.split(",") if a.strip()]

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.aliases = self.cleaned_data.get("aliases_text", [])
        if not obj.slug:
            obj.slug = _unique_slug(Machine, obj.model_name, exclude_pk=obj.pk)
        if commit:
            obj.save()
        return obj


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        # contact details + the equipment this customer owns (CRM 360), so staff can
        # log everything in one go. The equipment FKs are optional.
        fields = ["name", "phone", "email", "address", "postal_code", "city",
                  "property_type", "consent_to_contact",
                  "primary_brand", "primary_machine", "primary_category"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("primary_brand", "primary_machine", "primary_category"):
            self.fields[f].required = False
        self.fields["primary_brand"].label = "Brand"
        self.fields["primary_machine"].label = "Machine"
        self.fields["primary_category"].label = "Equipment type"
        _style(self.fields, area=("address",))


def _unique_faq_key(category, base: str) -> str:
    """A unique FAQEntry.key within a category (the model needs category+key unique)."""
    base = (slugify(base) or "faq")[:50]
    key, n = base, 2
    while FAQEntry.objects.filter(category=category, key=key).exists():
        key, n = f"{base}-{n}", n + 1
    return key


class FAQEntryForm(forms.Form):
    """Add a CATEGORY FAQ — what the specialist injects (FAQEntry + FAQEntryText)."""
    category = forms.ModelChoiceField(queryset=Category.objects.order_by("name"), label="Category")
    lang = forms.ChoiceField(choices=LANG_CHOICES, initial="sv")
    question = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))
    answer = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields, area=("question", "answer"))

    def save(self):
        cat = self.cleaned_data["category"]
        entry = FAQEntry.objects.create(category=cat, key=_unique_faq_key(cat, self.cleaned_data["question"]))
        FAQEntryText.objects.create(faq=entry, lang=self.cleaned_data["lang"],
                                    question=self.cleaned_data["question"], answer=self.cleaned_data["answer"])
        return entry


ONSET_CHOICES = [("", "—"), ("any", "Any"), ("sudden", "Sudden"), ("long_term", "Long-term")]


class KnowledgeEntryForm(forms.Form):
    """Create/edit a general-knowledge FAQEntry with ALL v2 metadata + sv text
    (en optional). Editing NEVER touches is_approved — the owner curates approval
    explicitly via the toggle."""

    category = forms.ModelChoiceField(queryset=Category.objects.none(), label="Category")
    question = forms.CharField(label="Question (sv)", widget=forms.Textarea(attrs={"rows": 2}))
    answer = forms.CharField(label="Answer (sv)", widget=forms.Textarea(attrs={"rows": 5}))
    question_en = forms.CharField(label="Question (en)", required=False,
                                  widget=forms.Textarea(attrs={"rows": 2}))
    answer_en = forms.CharField(label="Answer (en)", required=False,
                                widget=forms.Textarea(attrs={"rows": 4}))
    applicable_subtypes = forms.MultipleChoiceField(
        required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Leaf sub-types this entry applies to; none checked = all.")
    onset_type = forms.ChoiceField(choices=ONSET_CHOICES, required=False)
    safe_customer_checks = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    service_trigger = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    keywords = forms.CharField(required=False, help_text="Comma-separated keywords.")
    manufacturer = forms.ModelChoiceField(queryset=Vendor.objects.order_by("name"), required=False)
    exclusions = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, family_categories=None, leaf_slugs=(), instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        cats = family_categories if family_categories is not None else Category.objects.order_by("name")
        self.fields["category"].queryset = (
            cats if hasattr(cats, "model")
            else Category.objects.filter(pk__in=[c.pk for c in cats]).order_by("name"))
        self.fields["applicable_subtypes"].choices = [(s, s) for s in leaf_slugs]
        if instance is not None and not self.is_bound:
            txt = instance.text("sv")
            txt_en = instance.texts.filter(lang="en").first()
            self.initial.update({
                "category": instance.category_id,
                "question": txt.question if txt else "",
                "answer": txt.answer if txt else "",
                "question_en": txt_en.question if txt_en else "",
                "answer_en": txt_en.answer if txt_en else "",
                "applicable_subtypes": instance.applicable_subtypes or [],
                "onset_type": instance.onset_type,
                "safe_customer_checks": instance.safe_customer_checks,
                "service_trigger": instance.service_trigger,
                "keywords": ", ".join(instance.keywords or []),
                "manufacturer": instance.manufacturer_id,
                "exclusions": instance.exclusions,
            })
            # instance may carry subtype slugs outside this family's leaves — keep them valid.
            known = {s for s, _ in self.fields["applicable_subtypes"].choices}
            extra = [s for s in (instance.applicable_subtypes or []) if s not in known]
            if extra:
                self.fields["applicable_subtypes"].choices += [(s, s) for s in extra]
        _style(self.fields, area=("question", "answer", "question_en", "answer_en",
                                  "safe_customer_checks", "service_trigger", "exclusions"))
        self.fields["applicable_subtypes"].widget.attrs["class"] = _CHECK

    def clean_keywords(self):
        raw = self.cleaned_data.get("keywords", "")
        return [k.strip() for k in raw.split(",") if k.strip()]

    def save(self):
        d = self.cleaned_data
        entry = self.instance
        if entry is None:
            entry = FAQEntry(category=d["category"],
                             key=_unique_faq_key(d["category"], d["question"]))
        else:
            entry.category = d["category"]
        entry.applicable_subtypes = d["applicable_subtypes"]
        entry.onset_type = d["onset_type"]
        entry.safe_customer_checks = d["safe_customer_checks"]
        entry.service_trigger = d["service_trigger"]
        entry.keywords = d["keywords"]
        entry.manufacturer = d["manufacturer"]
        entry.exclusions = d["exclusions"]
        entry.save()  # is_approved untouched by design
        FAQEntryText.objects.update_or_create(
            faq=entry, lang="sv", defaults={"question": d["question"], "answer": d["answer"]})
        if d["question_en"] or d["answer_en"]:
            FAQEntryText.objects.update_or_create(
                faq=entry, lang="en",
                defaults={"question": d["question_en"], "answer": d["answer_en"]})
        return entry


class SiteFAQForm(forms.ModelForm):
    """Add a SITE FAQ — the public-style list shown on the FAQ page (SiteFAQ)."""
    class Meta:
        model = SiteFAQ
        fields = ["topic", "question", "answer", "lang"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields, area=("answer",))

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.slug:
            obj.slug = _unique_slug(SiteFAQ, obj.question, exclude_pk=obj.pk)
        if commit:
            obj.save()
        return obj


class BrandNoteForm(forms.ModelForm):
    class Meta:
        model = BrandNote
        fields = ["category", "body"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].required = False
        _style(self.fields, area=("body",))
