"""KB model + trigram identification tests. Uses the real Postgres test DB
(pg_trgm enabled by migration kb.0002)."""
import pytest
from django.core.management import call_command

from core.constants import MODELS
from kb import models as m
from kb.identification import best_match, identify_machine

pytestmark = pytest.mark.django_db


def _machine(vendor_name, cat_slug, model_name, aliases=None, supported=True):
    vendor, _ = m.Vendor.objects.get_or_create(
        slug=vendor_name.lower().replace(" ", "-"), defaults={"name": vendor_name})
    cat, _ = m.Category.objects.get_or_create(slug=cat_slug, defaults={"name": cat_slug})
    return m.Machine.objects.create(
        vendor=vendor, category=cat, model_name=model_name,
        aliases=aliases or [], slug=model_name.lower().replace(" ", "-"),
        is_supported=supported)


def test_search_text_is_lowercased_blob():
    mach = _machine("IVT", "exhaust_air", "IVT 490", ["IVT490"])
    assert "ivt 490" in mach.search_text
    assert "ivt490" in mach.search_text
    assert mach.search_text == mach.search_text.lower()


def test_identify_exact_model():
    target = _machine("IVT", "exhaust_air", "IVT 490", ["ivt490"])
    _machine("IVT", "exhaust_air", "IVT 402", ["ivt402"])
    _machine("Grundfos", "water_pump_well", "Grundfos SQ", ["sq"])
    mach, score = identify_machine("IVT 490")
    assert mach is not None
    assert mach.pk == target.pk
    assert score >= 0.4


def test_identify_from_noisy_nameplate_text():
    target = _machine("IVT", "exhaust_air", "IVT 490", ["ivt490"])
    _machine("Grundfos", "water_pump_well", "Grundfos SQ", ["sq"])
    # nameplate OCR / customer free text with noise around the model token
    mach, score = identify_machine("model IVT 490 serial 12345 alarm")
    assert mach is not None and mach.pk == target.pk


def test_correct_machine_outranks_wrong_one():
    ivt = _machine("IVT", "exhaust_air", "IVT 490")
    _machine("Grundfos", "water_pump_well", "Grundfos SQ")
    top, _ = best_match("IVT 490")
    assert top.pk == ivt.pk


def test_gibberish_is_unsupported():
    _machine("IVT", "exhaust_air", "IVT 490")
    mach, score = identify_machine("zzqqxx totally unrelated nonsense")
    assert mach is None
    assert score < 0.30


def test_unsupported_machine_excluded():
    _machine("IVT", "exhaust_air", "IVT 490", supported=False)
    mach, _ = identify_machine("IVT 490")
    assert mach is None  # excluded from the supported catalog


def test_empty_query_returns_none():
    assert identify_machine("") == (None, 0.0)


def test_faq_i18n_fallback_to_english():
    cat, _ = m.Category.objects.get_or_create(slug="heat_pump", defaults={"name": "Heat pump"})
    faq = m.FAQEntry.objects.create(category=cat, key="k1")
    m.FAQEntryText.objects.create(faq=faq, lang="en", question="Q", answer="A")
    assert faq.text("sv").answer == "A"  # falls back to en
    assert faq.text("en").answer == "A"


def test_chip_label_fallback():
    chip = m.QuickReplyChip.objects.create(intake_step="category", value="heat_pump")
    m.QuickReplyChipText.objects.create(chip=chip, lang="en", label="Heat pump")
    assert chip.label("sv") == "Heat pump"  # falls back to en
    chip2 = m.QuickReplyChip.objects.create(intake_step="brand", value="IVT")
    assert chip2.label("en") == "IVT"  # no text row → value


def test_seed_kb_is_idempotent_and_seeds_prompts():
    call_command("seed_kb")
    call_command("seed_kb")  # second run must not duplicate
    assert m.AgentPrompt.objects.count() == 6
    assert m.AgentPrompt.objects.get(role="specialist").model_id == MODELS["flash"]
    assert m.Machine.objects.filter(model_name="IVT 490").count() == 1
    # identification works on seeded data
    mach, _ = identify_machine("IVT 490")
    assert mach is not None and mach.model_name == "IVT 490"
