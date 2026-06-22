"""ModelForms for the create-everything dashboard (KB brands/machines + CRM customers).

Kept deliberately small: only real model fields, with auto-slug where the model
requires a unique slug the staff user shouldn't have to hand-type."""
from __future__ import annotations

from django import forms
from django.utils.text import slugify

from crm.models import Customer
from kb.models import BrandNote, Machine, Vendor

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
        fields = ["name", "phone", "email", "address", "postal_code", "city",
                  "property_type", "consent_to_contact"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields, area=("address",))


class BrandNoteForm(forms.ModelForm):
    class Meta:
        model = BrandNote
        fields = ["category", "body"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].required = False
        _style(self.fields, area=("body",))
