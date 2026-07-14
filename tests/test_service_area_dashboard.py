"""Service-area settings tab (plan S5): GeoSettings form, ServiceArea HTMX CRUD,
postcode test box, dataset status, export."""
from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import User

from crm.models import GeoSettings, PostcodeArea, ServiceArea

pytestmark = pytest.mark.django_db

SQUARE = [[17.0, 62.0], [17.5, 62.0], [17.5, 62.5], [17.0, 62.5], [17.0, 62.0]]
POLYGON_JSON = json.dumps({"type": "Polygon", "coordinates": [SQUARE]})


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


def test_service_area_page_is_staff_only(client):
    assert client.get("/dashboard/settings/service-area/").status_code in (302, 403)


def test_service_area_page_renders(staff, client):
    r = client.get("/dashboard/settings/service-area/")
    assert r.status_code == 200
    assert b"Service area" in r.content


def test_geo_settings_save(staff, client):
    r = client.post("/dashboard/settings/service-area/", {
        "enabled": "on",
        "previous_installer_names": "Nordland VVS, Acme Rör",
        "fallback_contact_url": "https://nordlandvvs.se/kontakt",
    })
    assert r.status_code == 302
    cfg = GeoSettings.load()
    assert cfg.enabled is True
    assert cfg.previous_installer_names == ["Nordland VVS", "Acme Rör"]
    assert cfg.fallback_contact_url == "https://nordlandvvs.se/kontakt"


def test_service_area_add_valid_polygon(staff, client):
    r = client.post("/dashboard/settings/service-area/add", {
        "name": "Main corridor", "kind": "inside", "border_km": "10", "is_active": "on",
        "polygon": POLYGON_JSON,
    })
    assert r.status_code == 200
    area = ServiceArea.objects.get(name="Main corridor")
    assert area.kind == "inside"
    assert area.polygon["type"] == "Polygon"


def test_service_area_add_rejects_bad_geojson(staff, client):
    r = client.post("/dashboard/settings/service-area/add", {
        "name": "Bad", "kind": "inside", "border_km": "10",
        "polygon": '{"type": "Point", "coordinates": [1, 2]}',
    })
    assert r.status_code == 200
    assert not ServiceArea.objects.filter(name="Bad").exists()
    assert "error" in r.headers.get("HX-Trigger", "")


def test_service_area_add_rejects_invalid_json(staff, client):
    r = client.post("/dashboard/settings/service-area/add", {
        "name": "Bad json", "kind": "inside", "border_km": "10", "polygon": "{not json",
    })
    assert r.status_code == 200
    assert not ServiceArea.objects.filter(name="Bad json").exists()


def test_service_area_add_requires_name(staff, client):
    r = client.post("/dashboard/settings/service-area/add", {
        "name": "", "kind": "inside", "border_km": "10", "polygon": POLYGON_JSON,
    })
    assert ServiceArea.objects.count() == 0
    assert "error" in r.headers.get("HX-Trigger", "")


def test_service_area_toggle_and_delete(staff, client):
    area = ServiceArea.objects.create(name="Toggleme", kind="inside",
                                       polygon={"type": "Polygon", "coordinates": [SQUARE]})
    r = client.post(f"/dashboard/settings/service-area/{area.pk}/toggle")
    area.refresh_from_db()
    assert area.is_active is False
    r = client.post(f"/dashboard/settings/service-area/{area.pk}/delete")
    assert r.status_code == 200
    assert not ServiceArea.objects.filter(pk=area.pk).exists()


def test_service_area_export_returns_geojson(staff, client):
    area = ServiceArea.objects.create(name="Exportme", kind="inside", border_km=8,
                                       polygon={"type": "Polygon", "coordinates": [SQUARE]})
    r = client.get(f"/dashboard/settings/service-area/{area.pk}/export")
    assert r.status_code == 200
    assert r["Content-Type"] == "application/geo+json"
    data = json.loads(r.content)
    assert data["type"] == "Feature"
    assert data["properties"]["name"] == "Exportme"
    assert data["geometry"]["type"] == "Polygon"


def test_postcode_test_box_works_even_when_disabled(staff, client):
    PostcodeArea.objects.create(code="62345", lat=62.25, lng=17.25, city="Testby")
    ServiceArea.objects.create(name="Main", kind="inside", polygon={"type": "Polygon", "coordinates": [SQUARE]})
    assert GeoSettings.load().enabled is False
    r = client.get("/dashboard/settings/service-area/test", {"postcode": "62345"})
    assert r.status_code == 200
    assert b"feature disabled" in r.content
    assert b"Inside service area" in r.content


def test_postcode_test_box_shows_status_when_enabled(staff, client):
    PostcodeArea.objects.create(code="62345", lat=62.25, lng=17.25, city="Testby")
    ServiceArea.objects.create(name="Main", kind="inside", polygon={"type": "Polygon", "coordinates": [SQUARE]})
    GeoSettings.objects.create(enabled=True)
    r = client.get("/dashboard/settings/service-area/test", {"postcode": "62345"})
    assert b"feature disabled" not in r.content
    assert b"Inside service area" in r.content


def test_dataset_status_shows_postcode_count(staff, client):
    PostcodeArea.objects.create(code="11111", lat=60.0, lng=17.0, city="A")
    PostcodeArea.objects.create(code="22222", lat=61.0, lng=17.0, city="B")
    r = client.get("/dashboard/settings/service-area/")
    assert b"2 postcodes loaded" in r.content


def test_settings_tabs_include_service_area_link(staff, client):
    r = client.get("/dashboard/settings/")
    assert r.status_code == 200
    assert b"Service area" in r.content
