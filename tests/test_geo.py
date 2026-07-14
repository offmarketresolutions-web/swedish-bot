"""crm.geo tests (plan S5): pure-python point-in-polygon, distance, GeoJSON
validation, service-area status resolution, and the importer/seeder commands."""
from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from crm import geo
from crm.models import GeoSettings, PostcodeArea, ServiceArea
from kb.models import Category

pytestmark = pytest.mark.django_db(transaction=False)


# ── point_in_ring / point_in_polygon ───────────────────────────────────────

SQUARE = [[10.0, 60.0], [11.0, 60.0], [11.0, 61.0], [10.0, 61.0], [10.0, 60.0]]


def test_point_in_ring_square_inside_and_outside():
    assert geo.point_in_ring((10.5, 60.5), SQUARE) is True
    assert geo.point_in_ring((12.0, 60.5), SQUARE) is False
    assert geo.point_in_ring((9.0, 60.5), SQUARE) is False


def test_point_in_polygon_with_hole():
    hole = [[10.4, 60.4], [10.6, 60.4], [10.6, 60.6], [10.4, 60.6], [10.4, 60.4]]
    geometry = {"type": "Polygon", "coordinates": [SQUARE, hole]}
    assert geo.point_in_polygon((10.5, 60.5), geometry) is False  # inside the hole
    assert geo.point_in_polygon((10.1, 60.1), geometry) is True   # inside outer, outside hole
    assert geo.point_in_polygon((15.0, 60.5), geometry) is False  # fully outside


def test_point_in_multipolygon():
    other_square = [[20.0, 60.0], [21.0, 60.0], [21.0, 61.0], [20.0, 61.0], [20.0, 60.0]]
    geometry = {"type": "MultiPolygon", "coordinates": [[SQUARE], [other_square]]}
    assert geo.point_in_polygon((10.5, 60.5), geometry) is True
    assert geo.point_in_polygon((20.5, 60.5), geometry) is True
    assert geo.point_in_polygon((15.0, 60.5), geometry) is False


def test_point_on_edge_of_square_is_deterministic():
    # Ray-cast edge behavior is a documented convention, not "correctness" per se —
    # assert it doesn't crash and is stable across repeated calls.
    edge_point = (10.0, 60.5)
    r1 = geo.point_in_polygon(edge_point, {"type": "Polygon", "coordinates": [SQUARE]})
    r2 = geo.point_in_polygon(edge_point, {"type": "Polygon", "coordinates": [SQUARE]})
    assert r1 == r2


# ── distance_to_edge_km ─────────────────────────────────────────────────────

def test_distance_to_edge_km_buffer_border():
    geometry = {"type": "Polygon", "coordinates": [SQUARE]}
    # Just outside the square's east edge (lng=11.0) at lat 60.5 -> small distance.
    d = geo.distance_to_edge_km((11.05, 60.5), geometry)
    assert 0 < d < 10
    # Point inside has distance 0 to itself... but distance_to_edge_km measures to
    # the boundary regardless of containment, so a point well inside is far from edges.
    d_center = geo.distance_to_edge_km((10.5, 60.5), geometry)
    assert d_center > 0


def test_distance_sanity_between_known_cities():
    # Sundsvall (62.39, 17.31) vs Gävle (60.67, 17.14) — real-world ~191 km.
    sundsvall = (17.31, 62.39)
    point_geom = {"type": "Polygon", "coordinates": [[list(sundsvall)] * 3]}
    d = geo.distance_to_edge_km((17.14, 60.67), point_geom)
    assert 172 <= d <= 210  # ±10% of ~191km


# ── clean_polygon (fail-closed) ─────────────────────────────────────────────

def test_clean_polygon_accepts_bare_polygon():
    geometry, warn, err = geo.clean_polygon({"type": "Polygon", "coordinates": [SQUARE]})
    assert err is None and geometry["type"] == "Polygon"
    assert warn is False  # this square (lng 10-11, lat 60-61) falls inside the rough Sweden bbox


def test_clean_polygon_unwraps_feature():
    feature = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [SQUARE]}}
    geometry, warn, err = geo.clean_polygon(feature)
    assert err is None and geometry["type"] == "Polygon"


def test_clean_polygon_unwraps_feature_collection():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [SQUARE]}}]}
    geometry, warn, err = geo.clean_polygon(fc)
    assert err is None and geometry["type"] == "Polygon"


def test_clean_polygon_rejects_non_dict():
    geometry, warn, err = geo.clean_polygon("not a dict")
    assert geometry is None and err


def test_clean_polygon_rejects_bad_type():
    geometry, warn, err = geo.clean_polygon({"type": "Point", "coordinates": [10.0, 60.0]})
    assert geometry is None and "Polygon or MultiPolygon" in err


def test_clean_polygon_rejects_too_few_vertices():
    geometry, warn, err = geo.clean_polygon({"type": "Polygon", "coordinates": [[[10.0, 60.0], [11.0, 60.0]]]})
    assert geometry is None and err


def test_clean_polygon_rejects_out_of_range_coords():
    bad_ring = [[10.0, 60.0], [11.0, 200.0], [11.0, 61.0], [10.0, 61.0], [10.0, 60.0]]
    geometry, warn, err = geo.clean_polygon({"type": "Polygon", "coordinates": [bad_ring]})
    assert geometry is None and err


def test_clean_polygon_auto_closes_ring():
    open_ring = SQUARE[:-1]  # drop the closing point
    geometry, warn, err = geo.clean_polygon({"type": "Polygon", "coordinates": [open_ring]})
    assert err is None
    assert geometry["coordinates"][0][0] == geometry["coordinates"][0][-1]


def test_clean_polygon_rejects_too_many_vertices():
    # >5000 vertices across a single ring.
    huge_ring = [[float(i % 360 - 180), 60.0] for i in range(5010)]
    geometry, warn, err = geo.clean_polygon({"type": "Polygon", "coordinates": [huge_ring]})
    assert geometry is None and "too many vertices" in err


def test_clean_polygon_sweden_bbox_warning_flag():
    # A polygon nowhere near Sweden (e.g. off the coast of Portugal) should warn.
    portugal_ring = [[-9.5, 38.5], [-9.0, 38.5], [-9.0, 39.0], [-9.5, 39.0], [-9.5, 38.5]]
    geometry, warn, err = geo.clean_polygon({"type": "Polygon", "coordinates": [portugal_ring]})
    assert err is None and warn is True


def test_clean_polygon_no_warning_when_inside_sweden():
    sweden_ring = [[17.0, 62.0], [17.5, 62.0], [17.5, 62.5], [17.0, 62.5], [17.0, 62.0]]
    geometry, warn, err = geo.clean_polygon({"type": "Polygon", "coordinates": [sweden_ring]})
    assert err is None and warn is False


# ── check_service_area / check_with_override ────────────────────────────────

SWEDEN_SQUARE = [[17.0, 62.0], [17.5, 62.0], [17.5, 62.5], [17.0, 62.5], [17.0, 62.0]]


@pytest.fixture
def enabled_geo():
    cfg = GeoSettings.load()
    cfg.enabled = True
    cfg.save()
    return cfg


@pytest.fixture
def inside_postcode():
    return PostcodeArea.objects.create(code="62345", lat=62.25, lng=17.25, city="Testby")


@pytest.fixture
def outside_postcode():
    return PostcodeArea.objects.create(code="99999", lat=55.0, lng=13.0, city="Farville")


def test_not_configured_when_disabled(inside_postcode):
    ServiceArea.objects.create(name="Main", kind="inside", polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("62345")
    assert result["status"] == "not_configured"


def test_not_configured_when_no_active_areas(enabled_geo, inside_postcode):
    result = geo.check_service_area("62345")
    assert result["status"] == "not_configured"


def test_unknown_postcode(enabled_geo):
    ServiceArea.objects.create(name="Main", kind="inside", polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("00000")
    assert result["status"] == "unknown_postcode"


def test_inside_area(enabled_geo, inside_postcode):
    ServiceArea.objects.create(name="Main", kind="inside", polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("62345")
    assert result["status"] == "inside_area"
    assert result["area_name"] == "Main"
    assert result["city"] == "Testby"


def test_border_review_for_extension_area(enabled_geo, inside_postcode):
    ServiceArea.objects.create(name="Ext", kind="extension", polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("62345")
    assert result["status"] == "border_review"
    assert result["area_name"] == "Ext"


def test_border_review_within_border_km_of_inside_area(enabled_geo):
    pa = PostcodeArea.objects.create(code="62399", lat=62.25, lng=17.51, city="Nearby")  # just outside the square
    ServiceArea.objects.create(name="Main", kind="inside", border_km=10,
                                polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("62399")
    assert result["status"] == "border_review"


def test_outside_area(enabled_geo, outside_postcode):
    ServiceArea.objects.create(name="Main", kind="inside", border_km=10,
                                polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("99999")
    assert result["status"] == "outside_area"
    assert result["area_name"] == "Main"


def test_category_scoping(enabled_geo, inside_postcode):
    heat = Category.objects.create(name="Heat pump", slug="heat_pump_geo_test")
    water = Category.objects.create(name="Water filtration", slug="water_filtration_geo_test")
    area = ServiceArea.objects.create(name="HeatOnly", kind="inside",
                                       polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    area.categories.set([heat])
    # Scoped to heat_pump only -> matches
    assert geo.check_service_area("62345", "heat_pump_geo_test")["status"] == "inside_area"
    # Scoped to a different category -> not_configured (no matching active area)
    assert geo.check_service_area("62345", "water_filtration_geo_test")["status"] == "not_configured"


def test_category_scoping_empty_applies_to_all(enabled_geo, inside_postcode):
    ServiceArea.objects.create(name="All", kind="inside", polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    assert geo.check_service_area("62345", "anything")["status"] == "inside_area"


def test_check_with_override_upgrades_outside_to_inside(enabled_geo, outside_postcode):
    ServiceArea.objects.create(name="Main", kind="inside", border_km=1,
                                polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("99999")
    assert result["status"] == "outside_area"
    upgraded = geo.check_with_override(result, "Nordland VVS installed it in 2019")
    assert upgraded["status"] == "inside_area"
    assert upgraded["override"] is True


def test_check_with_override_case_insensitive_substring_both_directions(enabled_geo, outside_postcode):
    ServiceArea.objects.create(name="Main", kind="inside", border_km=1,
                                polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("99999")
    upgraded = geo.check_with_override(result, "bylunds")
    assert upgraded["status"] == "inside_area"


def test_check_with_override_no_match_leaves_result_unchanged(enabled_geo, outside_postcode):
    ServiceArea.objects.create(name="Main", kind="inside", border_km=1,
                                polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("99999")
    unchanged = geo.check_with_override(result, "Some Random Plumber AB")
    assert unchanged["status"] == "outside_area"
    assert "override" not in unchanged


def test_check_with_override_does_not_touch_inside(enabled_geo, inside_postcode):
    ServiceArea.objects.create(name="Main", kind="inside", polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    result = geo.check_service_area("62345")
    same = geo.check_with_override(result, "Nordland VVS")
    assert same == result


def test_ignore_enabled_runs_check_regardless_of_geosettings(inside_postcode):
    ServiceArea.objects.create(name="Main", kind="inside", polygon={"type": "Polygon", "coordinates": [SWEDEN_SQUARE]})
    assert GeoSettings.load().enabled is False
    result = geo.check_service_area("62345", ignore_enabled=True)
    assert result["status"] == "inside_area"


# ── import_postcodes idempotence (fixture, no network) ──────────────────────

FIXTURE_TXT = "\n".join(
    f"SE\t{62000 + i}\tTown{i}\tVästernorrland\t22\tMunicipality{i}\t2280\t\t\t{62.0 + i * 0.01}\t17.{i:02d}\t4"
    for i in range(20)
)


def test_import_postcodes_fixture_idempotent(tmp_path):
    fixture = tmp_path / "SE.txt"
    fixture.write_text(FIXTURE_TXT, encoding="utf-8")
    call_command("import_postcodes", str(fixture))
    count_after_first = PostcodeArea.objects.count()
    assert count_after_first == 20
    call_command("import_postcodes", str(fixture))
    assert PostcodeArea.objects.count() == count_after_first  # update, not duplicate


def test_import_postcodes_dry_run_writes_nothing(tmp_path):
    fixture = tmp_path / "SE.txt"
    fixture.write_text(FIXTURE_TXT, encoding="utf-8")
    call_command("import_postcodes", str(fixture), "--dry-run")
    assert PostcodeArea.objects.count() == 0


# ── seed_service_areas idempotence ──────────────────────────────────────────

def test_seed_service_areas_idempotent():
    call_command("seed_service_areas")
    count_after_first = ServiceArea.objects.count()
    assert count_after_first == 3
    assert GeoSettings.load().enabled is False  # stays dormant
    call_command("seed_service_areas")
    assert ServiceArea.objects.count() == count_after_first


def test_seed_service_areas_no_bbox_warnings(capsys):
    call_command("seed_service_areas")
    captured = capsys.readouterr()
    assert "check for a lat/lng swap" not in captured.err.lower()
