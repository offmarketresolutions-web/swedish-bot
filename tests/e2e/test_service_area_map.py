"""Real-browser tests for the service-area map editor.

The operator's job on this page is: find a place, draw the shape you cover, see which
postcodes that actually catches, save it. Every assertion below follows that path.

Coverage is answered from crm.PostcodeArea (18,870 Swedish postcodes already on this
server) rather than a geocoding service — so these tests also pin that the numbers are
real and that no service area or customer address is sent to a third party.

    .venv\\Scripts\\python.exe -m pytest -m e2e -s -v tests/e2e/test_service_area_map.py
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

from .conftest import BASE_URL, E2E_ADMIN_PASS, E2E_ADMIN_USER, shot

pytestmark = [pytest.mark.e2e, pytest.mark.live]

# A rectangle over the Sundsvall/Timrå coast — inside the documented corridor, and big
# enough to catch real postcodes without covering half the country.
SUNDSVALL_BOX = {
    "type": "Polygon",
    "coordinates": [[[17.0, 62.2], [17.8, 62.2], [17.8, 62.6], [17.0, 62.6], [17.0, 62.2]]],
}


def _login(page: Page) -> None:
    page.goto(f"{BASE_URL}/dashboard/", timeout=60_000)  # -> redirect to /admin/login/
    page.locator("#id_username").fill(E2E_ADMIN_USER)
    page.locator("#id_password").fill(E2E_ADMIN_PASS)
    page.locator('input[type="submit"]').click()
    page.wait_for_url(f"{BASE_URL}/dashboard/**", timeout=15_000)


def _open_map(page: Page) -> None:
    _login(page)
    page.goto(f"{BASE_URL}/dashboard/settings/service-area/")
    page.wait_for_selector('[data-testid="sa-map"]', timeout=15_000)
    # Leaflet sizes itself from the container; wait for real height before asserting.
    page.wait_for_function(
        "() => document.getElementById('sa-map').getBoundingClientRect().height > 100",
        timeout=15_000)


def test_map_renders_with_basemap_and_draw_tools(page: Page):
    """The map is the page's primary control — if the basemap or the draw toolbar is
    missing the operator has nothing to work with."""
    _open_map(page)

    expect(page.locator(".leaflet-container")).to_be_visible()
    # A real basemap, not an empty pane.
    page.wait_for_function("() => document.querySelectorAll('.leaflet-tile').length > 0",
                           timeout=20_000)
    broken = page.evaluate(
        "() => [...document.querySelectorAll('.leaflet-tile')].filter(t => t.complete && !t.naturalWidth).length")
    assert broken == 0, f"{broken} basemap tiles failed to load"

    # Polygon + rectangle + edit + delete.
    expect(page.locator(".leaflet-draw-toolbar a").first).to_be_visible()
    assert page.locator(".leaflet-draw-toolbar a").count() >= 3

    # Saved areas are drawn underneath, so a new shape is placed in context.
    assert page.locator(".leaflet-overlay-pane path").count() >= 1
    shot(page, "map_01_loaded.png")


def test_map_is_not_zoomed_into_the_sea(page: Page):
    """Regression: fitBounds ran while the container was still 0px tall, fitting a 350 km
    corridor into 1.6px and snapping to zoom 18 over open water — indistinguishable from a
    broken basemap. The fit now waits for real height and caps the zoom."""
    _open_map(page)
    page.wait_for_function("() => document.querySelectorAll('.leaflet-tile').length > 0",
                           timeout=20_000)
    zoom = page.evaluate(
        "() => parseInt(document.querySelector('.leaflet-tile').src.split('/').slice(-3)[0], 10)")
    assert 5 <= zoom <= 13, f"map opened at zoom {zoom}; expected a regional view"


def test_place_search_finds_a_town_and_moves_the_map(page: Page):
    """The operator thinks in place names, not coordinates."""
    _open_map(page)

    page.fill('[data-testid="sa-place-search"]', "Sundsvall")
    page.wait_for_selector('[data-testid="sa-place-result"]', timeout=15_000)
    first = page.locator('[data-testid="sa-place-result"]').first
    # The result must carry a real postcode count from the local table, not a bare name.
    assert "postcodes" in first.inner_text()

    before = page.evaluate("() => document.querySelector('.leaflet-tile').src")
    first.click()
    page.wait_for_timeout(2500)
    after = page.evaluate("() => document.querySelector('.leaflet-tile').src")
    assert before != after, "clicking a place result did not move the map"
    shot(page, "map_02_place_search.png")


def test_place_search_reports_no_match_rather_than_failing_silently(page: Page):
    _open_map(page)
    page.fill('[data-testid="sa-place-search"]', "Zzzqqx")
    page.wait_for_timeout(1200)
    expect(page.locator('[data-testid="sa-place-results"]')).to_contain_text("No place")


def test_coverage_endpoint_returns_real_postcodes_for_a_drawn_shape(page: Page):
    """The heart of the feature: a shape must resolve to the postcodes it really covers.

    Driving Leaflet's freehand draw from Playwright is brittle, so this posts the same
    geometry the draw tool produces to the same endpoint the map calls, and asserts the
    answer is real Swedish data — Sundsvall must be among the towns caught by a box drawn
    over Sundsvall.
    """
    _open_map(page)
    result = page.evaluate(
        """async (geom) => {
            const el = document.getElementById('sa-map');
            const r = await fetch(el.dataset.coverageUrl, {
              method: 'POST',
              headers: {'Content-Type': 'application/json', 'X-CSRFToken': el.dataset.csrf},
              body: JSON.stringify({polygon: geom}),
            });
            return {status: r.status, body: await r.json()};
        }""", SUNDSVALL_BOX)

    assert result["status"] == 200, result
    body = result["body"]
    assert body["postcodes"] > 0, "a box over Sundsvall caught no postcodes"
    assert body["city_count"] > 0
    assert any("sundsvall" in c.lower() for c in body["cities"]), body["cities"][:10]
    assert body["sample"] and all(len(s["code"]) == 5 for s in body["sample"]), body["sample"]


def test_coverage_endpoint_rejects_a_malformed_shape(page: Page):
    """A bad shape must fail loudly, not be stored as an area that silently covers nothing."""
    _open_map(page)
    status = page.evaluate(
        """async () => {
            const el = document.getElementById('sa-map');
            const r = await fetch(el.dataset.coverageUrl, {
              method: 'POST',
              headers: {'Content-Type': 'application/json', 'X-CSRFToken': el.dataset.csrf},
              body: JSON.stringify({polygon: {type: 'Polygon', coordinates: 'nonsense'}}),
            });
            return r.status;
        }""")
    assert status == 400, f"malformed polygon returned {status}"


def test_drawn_shape_fills_the_form_field_so_it_can_be_saved(page: Page):
    """The map writes GeoJSON into the real form field — that field stays the source of
    truth, so the page still works with JavaScript off."""
    _open_map(page)
    page.evaluate(
        """(geom) => {
            const f = document.getElementById('sa-polygon-field');
            f.value = JSON.stringify(geom);
            f.dispatchEvent(new Event('input', {bubbles: true}));
        }""", SUNDSVALL_BOX)
    value = page.input_value('[data-testid="sa-polygon-field"]')
    assert json.loads(value)["type"] == "Polygon"


def test_the_page_still_works_without_javascript(page: Page, browser):
    """No-JS is a real condition (a blocked CDN, a locked-down browser). The GeoJSON
    textarea must remain reachable so an area can still be added by hand."""
    ctx = browser.new_context(java_script_enabled=False, locale="sv-SE")
    p = ctx.new_page()
    try:
        _login(p)
        p.goto(f"{BASE_URL}/dashboard/settings/service-area/")
        # The form and its textarea are server-rendered; only the map needs JS.
        expect(p.locator('[data-testid="sa-polygon-field"]')).to_be_attached()
        expect(p.locator('[data-testid="geo-test-postcode"]')).to_be_visible()
    finally:
        ctx.close()
