"""load_root_manuals: loads the repo-root manual .txt files into real Machine +
MachineDocument rows (Sprint S1 old standing item). Uses a synthetic --source-dir
fixture (not the real gitignored root .txt files) so these tests are hermetic."""
import pytest
from django.core.management import call_command

from kb.models import Machine, MachineDocument

pytestmark = pytest.mark.django_db

FILES = {
    "geo_troubleshooting.txt": "Geo troubleshooting content A.",
    "geo_perceivable_errors.txt": "Geo perceivable errors content B.",
    "vent_content.txt": "Vent content C.",
    "vent_maintenance_full.txt": "Vent maintenance content D.",
    "greenline_content.txt": "Greenline content E.",
}


def _write_files(tmp_path, files=FILES):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")


def test_creates_machines_and_documents(tmp_path):
    call_command("seed_kb")
    _write_files(tmp_path)
    call_command("load_root_manuals", "--source-dir", str(tmp_path))

    geo = Machine.objects.get(model_name="Geo 412C")
    assert geo.vendor.name == "IVT"
    assert geo.category.slug == "water_to_water"
    assert geo.documents.count() == 2
    assert {d.parsed_text for d in geo.documents.all()} == {
        "Geo troubleshooting content A.", "Geo perceivable errors content B."}
    assert all(d.kind == "manual" and d.lang == "sv" for d in geo.documents.all())

    vent = Machine.objects.get(model_name="Vent 402")
    assert vent.category.slug == "exhaust_air"
    assert vent.documents.count() == 2

    greenline = Machine.objects.get(model_name="Greenline HE")
    assert greenline.vendor.name == "Bosch"
    assert greenline.documents.count() == 1


def test_idempotent_no_duplicate_docs_or_machines(tmp_path):
    call_command("seed_kb")
    _write_files(tmp_path)
    call_command("load_root_manuals", "--source-dir", str(tmp_path))
    call_command("load_root_manuals", "--source-dir", str(tmp_path))

    assert Machine.objects.filter(model_name="Geo 412C").count() == 1
    assert Machine.objects.get(model_name="Geo 412C").documents.count() == 2
    assert Machine.objects.get(model_name="Vent 402").documents.count() == 2
    assert Machine.objects.get(model_name="Greenline HE").documents.count() == 1


def test_missing_category_skips_without_crash():
    # no seed_kb -> no categories at all
    Machine.objects.all().delete()
    call_command("load_root_manuals", "--source-dir", "C:/nonexistent-dir-for-test")
    assert Machine.objects.filter(model_name="Geo 412C").count() == 0


def test_missing_file_logs_and_continues(tmp_path):
    call_command("seed_kb")
    partial = dict(FILES)
    del partial["geo_perceivable_errors.txt"]
    _write_files(tmp_path, partial)
    call_command("load_root_manuals", "--source-dir", str(tmp_path))

    geo = Machine.objects.get(model_name="Geo 412C")
    assert geo.documents.count() == 1  # only the file that existed
    # other machines unaffected
    assert Machine.objects.get(model_name="Vent 402").documents.count() == 2


def test_dry_run_writes_nothing(tmp_path):
    call_command("seed_kb")
    _write_files(tmp_path)
    call_command("load_root_manuals", "--source-dir", str(tmp_path), "--dry-run")
    assert not Machine.objects.filter(model_name="Geo 412C").exists()
    assert MachineDocument.objects.count() == 0


def test_coexists_with_test_scenarios_conftest_fixture(tmp_path):
    """tests/test_scenarios/conftest.py's `seeded` fixture creates the same 3
    machines independently via get_or_create (test-only, no manual text) — this
    command must not conflict with or duplicate that when both touch the same
    (vendor, model_name) rows in one test DB."""
    call_command("seed_kb")
    from kb.models import Category, Vendor

    ivt = Vendor.objects.get(name="IVT")
    bosch = Vendor.objects.get(name="Bosch")
    water_to_water = Category.objects.get(slug="water_to_water")
    exhaust_air = Category.objects.get(slug="exhaust_air")
    Machine.objects.get_or_create(
        vendor=ivt, model_name="Geo 412C",
        defaults=dict(category=water_to_water, aliases=["geo412c"], slug="geo-412c-fixture"))
    Machine.objects.get_or_create(
        vendor=ivt, model_name="Vent 402",
        defaults=dict(category=exhaust_air, aliases=["vent402"], slug="ivt-vent-402-fixture"))
    Machine.objects.get_or_create(
        vendor=bosch, model_name="Greenline HE",
        defaults=dict(category=water_to_water, aliases=["greenline"], slug="greenline-he-fixture"))

    _write_files(tmp_path)
    call_command("load_root_manuals", "--source-dir", str(tmp_path))

    # still exactly one Machine per (vendor, model_name) — no crash, no duplicate
    assert Machine.objects.filter(vendor=ivt, model_name="Geo 412C").count() == 1
    assert Machine.objects.filter(vendor=ivt, model_name="Vent 402").count() == 1
    assert Machine.objects.filter(vendor=bosch, model_name="Greenline HE").count() == 1
    # and the command still attached the real manual documents
    assert Machine.objects.get(vendor=ivt, model_name="Geo 412C").documents.count() == 2
