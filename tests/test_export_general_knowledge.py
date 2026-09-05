"""kb.management.commands.export_general_knowledge — dumps the corpus back into
the package shape the importer reads.

The load-bearing property is a ROUND TRIP: export -> wipe -> re-import must
reproduce every field. That is what makes the export safe to run against dev and
import into production, which is the only reason this command exists (the
distributed .zip was lost, so the DB was the corpus's single copy)."""
import json

import pytest
from django.core.management import call_command
from django.utils.text import slugify
from test_import_general_knowledge import FIXTURE_ENTRIES, _package

from kb.management.commands.export_general_knowledge import OUR_TO_PACKAGE_SLUG
from kb.management.commands.import_general_knowledge import CATEGORY_SLUG_MAP
from kb.models import Category, FAQEntry, FAQEntryText, SiteFAQ

pytestmark = pytest.mark.django_db


def _snapshot():
    """Every field the package round trip is supposed to preserve."""
    faqs = {
        f.source_id: {
            "category": f.category.slug,
            "key": f.key,
            "subtypes": f.applicable_subtypes,
            "onset": f.onset_type,
            "source_type": f.source_type,
            "checks": f.safe_customer_checks,
            "trigger": f.service_trigger,
            "keywords": f.keywords,
            "q": f.texts.get(lang="sv").question,
            "a": f.texts.get(lang="sv").answer,
        }
        for f in FAQEntry.objects.exclude(source_id="").select_related("category")
    }
    sites = {
        s.slug: {"topic": s.topic, "q": s.question, "a": s.answer, "lang": s.lang}
        for s in SiteFAQ.objects.filter(source_url="")
    }
    return faqs, sites


def test_slug_map_inverts_cleanly():
    """A duplicate value in CATEGORY_SLUG_MAP would silently drop a category on export."""
    assert set(OUR_TO_PACKAGE_SLUG) == set(CATEGORY_SLUG_MAP.values())
    assert len(OUR_TO_PACKAGE_SLUG) == len(CATEGORY_SLUG_MAP)


def test_round_trip_reproduces_every_row(tmp_path):
    json_path, _ = _package(tmp_path)
    call_command("import_general_knowledge", str(json_path))
    before = _snapshot()
    assert len(before[0]) == 4 and len(before[1]) == 1

    dest = tmp_path / "export.json"
    call_command("export_general_knowledge", str(dest))

    FAQEntryText.objects.all().delete()
    FAQEntry.objects.all().delete()
    SiteFAQ.objects.all().delete()
    Category.objects.all().delete()

    call_command("import_general_knowledge", str(dest))
    assert _snapshot() == before


def test_export_skips_hand_authored_rows_and_the_scraped_site_faq(tmp_path):
    """Rows without a source_id (hand-seeded FAQEntry) and SiteFAQ rows carrying a
    source_url (the scraped nordlandvvs.se FAQ) belong to other seeders — exporting
    them would re-import them as unapproved drafts on the target install."""
    json_path, _ = _package(tmp_path)
    call_command("import_general_knowledge", str(json_path))
    cat = Category.objects.get(slug="heat_pump")
    FAQEntry.objects.create(category=cat, key="hand-authored", source_id="")
    SiteFAQ.objects.create(slug="scraped-1", question="Q", answer="A",
                           source_url="https://nordlandvvs.se/faq")

    dest = tmp_path / "export.json"
    call_command("export_general_knowledge", str(dest))
    ids = {e["faq_id"] for e in json.loads(dest.read_text(encoding="utf-8"))["entries"]}
    assert "scraped-1" not in ids
    # SiteFAQ only stores slugify(faq_id), so a site id comes back lowercased. Re-slugifying
    # is idempotent, so the round trip above is still exact.
    assert ids == {slugify(e["faq_id"]) if e["faq_type"] == "site" else e["faq_id"]
                   for e in FIXTURE_ENTRIES}


def test_export_never_carries_approval(tmp_path):
    """Approval is the owner's editorial act on the target install, not a property
    of the package — the importer lands everything unapproved by design."""
    json_path, _ = _package(tmp_path)
    call_command("import_general_knowledge", str(json_path))
    FAQEntry.objects.update(is_approved=True)
    SiteFAQ.objects.update(is_approved=True)

    dest = tmp_path / "export.json"
    call_command("export_general_knowledge", str(dest))
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert all("is_approved" not in e for e in payload["entries"])
