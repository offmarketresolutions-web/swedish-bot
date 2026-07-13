"""kb.management.commands.import_general_knowledge — imports the FAQ package
(zip or bare json) into FAQEntry (faq_type=category) / SiteFAQ (faq_type=site),
all landing UNAPPROVED (owner reviews in the dashboard). Idempotent by faq_id.
Uses a small synthetic fixture package (not the real 102-entry zip) so these
tests stay fast and deterministic; the real package is run manually per the
Sprint S1 plan."""
import json
import zipfile

import pytest
from django.core.management import call_command

from kb.management.commands.import_general_knowledge import (
    CATEGORY_SLUG_MAP, normalize_subtypes,
)
from kb.models import Category, FAQEntry, SiteFAQ

pytestmark = pytest.mark.django_db

FIXTURE_ENTRIES = [
    {
        "faq_id": "SITE-001", "faq_type": "site", "category_slug": "site_general",
        "category_label_sv": "Allmänt", "subcategory_slug": "service_scope",
        "question_sv": "Vilka typer av anläggningar servar Nordland VVS?",
        "answer_sv": "Vi servar de flesta märken.",
        "applicable_subtypes": [], "onset_type": "any",
        "safe_customer_checks": "", "service_trigger": "",
        "source_type": "Nordland VVS conversation-derived knowledge",
        "verification_status": "Review required before production",
        "public_site_candidate": True, "keywords": ["service"], "developer_notes": "",
    },
    {
        "faq_id": "HP-GEN-001", "faq_type": "category", "category_slug": "heat_pump",
        "category_label_sv": "Värmepump", "subcategory_slug": "sudden_vs_long_term",
        "question_sv": "Är det för kallt inne?",
        "answer_sv": "Kontrollera larm och driftläge först.",
        "applicable_subtypes": ["all"], "onset_type": "any",
        "safe_customer_checks": "Kontrollera larm; driftläge",
        "service_trigger": "Plötslig förändring",
        "source_type": "Nordland VVS conversation-derived knowledge",
        "verification_status": "Review required before production",
        "public_site_candidate": False, "keywords": ["kallt"], "developer_notes": "",
    },
    {
        "faq_id": "HPW-001", "faq_type": "category", "category_slug": "heat_pump_liquid_water",
        "category_label_sv": "Bergvärme", "subcategory_slug": "brine_bubbling",
        "question_sv": "Bubblar det i brine-kretsen?",
        "answer_sv": "Det kan vara luft i systemet.",
        "applicable_subtypes": ["liquid_to_water"], "onset_type": "sudden",
        "safe_customer_checks": "Kontrollera tryck", "service_trigger": "Ihållande bubbel",
        "source_type": "Nordland VVS conversation-derived knowledge",
        "verification_status": "Review required before production",
        "public_site_candidate": False, "keywords": ["brine"], "developer_notes": "",
    },
    {
        "faq_id": "RAD-001", "faq_type": "category", "category_slug": "radiators",
        "category_label_sv": "Radiatorer", "subcategory_slug": "gurgling",
        "question_sv": "Varför låter radiatorn?",
        "answer_sv": "Luft i systemet — lufta radiatorn.",
        "applicable_subtypes": [], "onset_type": "any",
        "safe_customer_checks": "Lufta radiatorn", "service_trigger": "",
        "source_type": "Nordland VVS conversation-derived knowledge",
        "verification_status": "Review required before production",
        "public_site_candidate": False, "keywords": ["radiator"], "developer_notes": "",
    },
    {
        "faq_id": "WPW-001", "faq_type": "category", "category_slug": "water_pump_well",
        "category_label_sv": "Vattenpump", "subcategory_slug": "no_water",
        "question_sv": "Inget vatten alls?",
        "answer_sv": "Kontrollera säkringar och tryckvakt.",
        "applicable_subtypes": ["submersible_pump", "jet_pump", "pressure_system", "well"],
        "onset_type": "sudden", "safe_customer_checks": "Kontrollera säkringar",
        "service_trigger": "Inget vatten kvarstår",
        "source_type": "Nordland VVS conversation-derived knowledge",
        "verification_status": "Review required before production",
        "public_site_candidate": False, "keywords": ["vatten"], "developer_notes": "",
    },
]


def _package(tmp_path, entries=FIXTURE_ENTRIES):
    payload = {"schema_version": "1.0", "generated_date": "2026-07-13", "language": "sv",
               "notes": {}, "entries": entries}
    json_path = tmp_path / "faq_import.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    zip_path = tmp_path / "faq_import.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(json_path, arcname="faq_import.json")
        zf.writestr("README.txt", "readme")
    return json_path, zip_path


# ── pure helpers ────────────────────────────────────────────────────────
def test_normalize_subtypes_maps_liquid_to_water():
    assert normalize_subtypes(["liquid_to_water", "air_to_water"]) == ["water_to_water", "air_to_water"]


def test_normalize_subtypes_all_becomes_empty():
    assert normalize_subtypes(["all"]) == []


def test_normalize_subtypes_empty_stays_empty():
    assert normalize_subtypes([]) == []


def test_normalize_subtypes_pump_vocab_verbatim():
    assert normalize_subtypes(["submersible_pump", "jet_pump", "pressure_system", "well"]) == [
        "submersible_pump", "jet_pump", "pressure_system", "well"]


def test_category_slug_map_matches_plan():
    assert CATEGORY_SLUG_MAP["heat_pump_liquid_water"] == "water_to_water"
    assert CATEGORY_SLUG_MAP["heat_pump_air_water"] == "air_to_water"
    assert CATEGORY_SLUG_MAP["heat_pump_air_air"] == "air_to_air"
    assert CATEGORY_SLUG_MAP["heat_pump_exhaust_air"] == "exhaust_air"
    assert CATEGORY_SLUG_MAP["heat_pump"] == "heat_pump"
    assert CATEGORY_SLUG_MAP["water_pump_well"] == "water_pump_well"
    assert CATEGORY_SLUG_MAP["water_filtration"] == "water_filtration"
    assert CATEGORY_SLUG_MAP["radiators"] == "radiators"
    assert CATEGORY_SLUG_MAP["floor_heating"] == "floor_heating"


# ── end-to-end import (json path) ────────────────────────────────────────
def test_import_json_creates_unapproved_rows(tmp_path):
    call_command("seed_kb")
    json_path, _zip_path = _package(tmp_path)
    call_command("import_general_knowledge", str(json_path))

    assert SiteFAQ.objects.filter(slug="site-001").exists()
    site = SiteFAQ.objects.get(slug="site-001")
    assert site.is_approved is False
    assert site.is_active is True
    assert site.topic == "service_scope"

    hp = FAQEntry.objects.get(source_id="HP-GEN-001")
    assert hp.is_approved is False
    assert hp.applicable_subtypes == []
    assert hp.category.slug == "heat_pump"
    assert hp.text("sv").question == "Är det för kallt inne?"
    assert hp.safe_customer_checks == "Kontrollera larm; driftläge"

    hpw = FAQEntry.objects.get(source_id="HPW-001")
    assert hpw.category.slug == "water_to_water"
    assert hpw.applicable_subtypes == ["water_to_water"]
    assert hpw.onset_type == "sudden"

    wpw = FAQEntry.objects.get(source_id="WPW-001")
    assert wpw.applicable_subtypes == ["submersible_pump", "jet_pump", "pressure_system", "well"]


def test_import_creates_missing_leaf_category(tmp_path):
    call_command("seed_kb")
    assert not Category.objects.filter(slug="radiators").exists()
    json_path, _ = _package(tmp_path)
    call_command("import_general_knowledge", str(json_path))

    rad = Category.objects.get(slug="radiators")
    assert rad.parent.slug == "heat_pump"
    assert rad.group == "heat"
    entry = FAQEntry.objects.get(source_id="RAD-001")
    assert entry.category.slug == "radiators"


def test_import_creates_missing_target_category_when_not_seeded(tmp_path):
    """water_to_water etc. come from seed_kb normally; simulate a deploy where the
    target category is missing — import must create the leaf, not crash."""
    heat_pump = Category.objects.create(slug="heat_pump", name="Heat pump", group="heat")
    assert not Category.objects.filter(slug="water_to_water").exists()
    json_path, _ = _package(tmp_path, entries=[e for e in FIXTURE_ENTRIES if e["faq_id"] == "HPW-001"])
    call_command("import_general_knowledge", str(json_path))
    wtw = Category.objects.get(slug="water_to_water")
    assert wtw.parent_id == heat_pump.pk


def test_import_is_idempotent(tmp_path):
    call_command("seed_kb")
    json_path, _ = _package(tmp_path)
    call_command("import_general_knowledge", str(json_path))
    n_faq, n_site = FAQEntry.objects.count(), SiteFAQ.objects.count()
    call_command("import_general_knowledge", str(json_path))
    assert FAQEntry.objects.count() == n_faq
    assert SiteFAQ.objects.count() == n_site
    # re-import must not flip a since-approved row back to unapproved
    entry = FAQEntry.objects.get(source_id="HP-GEN-001")
    entry.is_approved = True
    entry.save(update_fields=["is_approved"])
    call_command("import_general_knowledge", str(json_path))
    entry.refresh_from_db()
    assert entry.is_approved is True


def test_import_dry_run_writes_nothing(tmp_path):
    call_command("seed_kb")
    json_path, _ = _package(tmp_path)
    call_command("import_general_knowledge", str(json_path), "--dry-run")
    assert FAQEntry.objects.filter(source_id__in=["HP-GEN-001", "HPW-001", "RAD-001", "WPW-001"]).count() == 0
    assert not SiteFAQ.objects.filter(slug="site-001").exists()


# ── zip path ──────────────────────────────────────────────────────────
def test_import_accepts_zip(tmp_path):
    call_command("seed_kb")
    _json_path, zip_path = _package(tmp_path)
    call_command("import_general_knowledge", str(zip_path))
    assert FAQEntry.objects.filter(source_id="HP-GEN-001").exists()
    assert SiteFAQ.objects.filter(slug="site-001").exists()
