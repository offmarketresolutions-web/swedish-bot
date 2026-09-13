"""Real-browser test for the daily-activity chart tooltip.

The owner reads this chart to answer "what happened on the 3rd?". Before this, the chart
was two unlabelled lines: no dates, no values, nothing on hover. These tests drive a real
mouse across it and assert the readout tracks the pointer.

Assertions are deliberately locale-agnostic — this dashboard runs in Swedish by default,
so pinning the word "Sessions" would test the translation catalogue, not the chart.

    .venv\\Scripts\\python.exe -m pytest -m e2e -s -v tests/e2e/test_analytics_chart.py
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import BASE_URL, E2E_ADMIN_PASS, E2E_ADMIN_USER, shot

pytestmark = [pytest.mark.e2e, pytest.mark.live]


@pytest.fixture(scope="module", autouse=True)
def activity_today(orm):
    """Guarantee the window is non-empty.

    The chart hides itself when nothing happened — correct behaviour, but it means these
    tests would otherwise assert against a chart that is legitimately not rendered. The
    dev DB's newest sessions are weeks old, so the 7-day window is blank.
    """
    from django.utils import timezone

    with orm.unblock():
        from chat.models import Conversation
        from crm.models import Session

        if not Session.objects.filter(created_at__date=timezone.localdate()).exists():
            Session.objects.create(
                conversation=Conversation.objects.create(language="sv"),
                severity="normal",
                ai_summary="E2E seed: one session today so the trend chart has a window.")


def _open_analytics(page: Page, days: int = 30) -> None:
    page.goto(f"{BASE_URL}/dashboard/", timeout=60_000)  # -> redirect to /admin/login/
    page.locator("#id_username").fill(E2E_ADMIN_USER)
    page.locator("#id_password").fill(E2E_ADMIN_PASS)
    page.locator('input[type="submit"]').click()
    page.wait_for_url(f"{BASE_URL}/dashboard/**", timeout=15_000)
    page.goto(f"{BASE_URL}/dashboard/analytics/?days={days}")
    page.wait_for_selector("#trend-wrap", timeout=15_000)
    # The chart is below the fold; without this the mouse coordinates below land on
    # whatever happens to be at the top of the viewport instead.
    page.locator("#trend-wrap").scroll_into_view_if_needed()
    page.wait_for_function(
        "() => document.getElementById('trend-wrap').getBoundingClientRect().width > 100",
        timeout=10_000)


def _hover_fraction(page: Page, frac: float) -> None:
    """Move the real mouse to `frac` across the chart (0 = first day, 1 = last)."""
    box = page.locator("#trend-wrap").bounding_box()
    page.mouse.move(box["x"] + box["width"] * frac, box["y"] + box["height"] / 2)


def _day(page: Page) -> str:
    """The date line of the tooltip — its first line."""
    return page.locator("#trend-tip").inner_text().strip().splitlines()[0]


def test_the_tooltip_follows_the_cursor_and_names_the_day(page: Page):
    _open_analytics(page)
    tip = page.locator("#trend-tip")
    expect(tip).to_be_hidden()

    _hover_fraction(page, 0.5)
    expect(tip).to_be_visible()

    middle = tip.inner_text().strip()
    assert middle, "the tooltip must say something"
    # A date line plus one row per series, each ending in its number.
    lines = [ln for ln in middle.splitlines() if ln.strip()]
    assert len(lines) >= 4, f"expected a date and three series, got {lines!r}"
    assert any(ch.isdigit() for ch in middle), f"the tooltip must carry values: {middle!r}"

    expect(page.locator("#trend-cross")).to_be_visible()
    assert page.locator("#trend-dots > *").count() == 3, "one dot per series"

    # Moving to a different day must show a DIFFERENT day.
    middle_day = _day(page)
    _hover_fraction(page, 0.05)
    assert _day(page) != middle_day, "the tooltip did not follow the cursor"

    shot(page, "analytics_tooltip.png")


def test_leaving_the_chart_hides_the_readout(page: Page):
    _open_analytics(page)
    _hover_fraction(page, 0.5)
    expect(page.locator("#trend-tip")).to_be_visible()
    page.mouse.move(5, 5)
    expect(page.locator("#trend-tip")).to_be_hidden()
    expect(page.locator("#trend-cross")).to_be_hidden()


def test_the_chart_is_readable_without_a_mouse(page: Page):
    """Keyboard focus lands on the last day; arrows walk it."""
    _open_analytics(page)
    page.locator("#trend-wrap").focus()
    expect(page.locator("#trend-tip")).to_be_visible()
    last = _day(page)

    page.keyboard.press("ArrowLeft")
    assert _day(page) != last, "ArrowLeft must move to the previous day"

    page.keyboard.press("Home")
    home = _day(page)
    page.keyboard.press("End")
    assert _day(page) == last, "End must return to the last day"
    assert home != last

    # The same numbers reach a screen reader.
    assert page.locator("#trend-readout").inner_text().strip()


def test_the_axis_is_dated_and_the_window_is_totalled(page: Page):
    _open_analytics(page, days=7)
    assert page.locator("#trend-axis").inner_text().strip(), "the chart must date its axis"
    for key in ("sessions", "resolved", "leads"):
        total = page.locator(f'[data-total="{key}"]').inner_text().strip()
        assert total.isdigit(), f"{key} total should be a number, got {total!r}"


def test_the_csv_download_matches_the_window(page: Page):
    _open_analytics(page, days=7)
    with page.expect_download(timeout=20_000) as dl:
        page.locator('[data-testid="analytics-export"]').click()
    download = dl.value
    assert download.suggested_filename.endswith(".csv")
    assert "7d" in download.suggested_filename, download.suggested_filename
