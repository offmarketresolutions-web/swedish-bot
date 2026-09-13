"""The analytics window has to leave the page.

The chart can only show the shapes we thought to build; the owner reports to people who
use a spreadsheet. The CSV must therefore carry the same window the chart is showing, one
row per day, and the success scoreboard with its targets.
"""
from __future__ import annotations

import csv
import datetime
import io

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client):
    user = get_user_model().objects.create_user(
        username="reporter", password="x", is_staff=True, is_superuser=True)
    client.force_login(user)
    return client


def _rows(resp):
    body = resp.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(body)))


def _daily(rows):
    """Just the day rows: everything between the date header and the totals line."""
    i = rows.index(["date", "sessions", "resolved", "leads"]) + 1
    out = []
    while i < len(rows) and rows[i] and rows[i][0] not in ("", "total"):
        out.append(rows[i])
        i += 1
    return out


def test_the_export_has_a_row_per_day_of_the_window(staff_client):
    resp = staff_client.get(reverse("dash-analytics-export"), {"days": 7})
    assert resp.status_code == 200
    assert "text/csv" in resp["Content-Type"]
    assert "attachment" in resp["Content-Disposition"]

    days = _daily(_rows(resp))
    assert len(days) == 7, f"a 7-day window must export 7 days, got {len(days)}"

    dates = [datetime.date.fromisoformat(r[0]) for r in days]
    assert dates == sorted(dates), "days must be in order"
    assert dates[-1] == timezone.localdate(), "the window must end today"


def test_the_window_follows_the_chart(staff_client):
    for days in (7, 30, 90):
        got = _daily(_rows(staff_client.get(reverse("dash-analytics-export"), {"days": days})))
        assert len(got) == days


def test_a_junk_window_falls_back_rather_than_erroring(staff_client):
    for bad in ("abc", "-1", "9999"):
        resp = staff_client.get(reverse("dash-analytics-export"), {"days": bad})
        assert resp.status_code == 200
        assert len(_daily(_rows(resp))) == 30, "an unusable window must fall back to the 30-day default"


def test_the_scoreboard_travels_with_its_targets(staff_client):
    rows = _rows(staff_client.get(reverse("dash-analytics-export")))
    header = rows.index(["metric", "value", "target", "met"])
    metrics = [r for r in rows[header + 1:] if r]
    assert metrics, "the success scoreboard must be in the export"
    labels = {r[0] for r in metrics}
    assert "Resolution rate" in labels
    for r in metrics:
        assert r[3] in ("yes", "no"), f"met must be a plain yes/no, got {r[3]!r}"


def test_the_export_is_staff_only(client):
    resp = client.get(reverse("dash-analytics-export"))
    assert resp.status_code in (302, 403), "analytics must not be public"


def test_the_page_offers_the_download_and_the_chart_data(staff_client):
    html = staff_client.get(reverse("dash-analytics"), {"days": 7}).content.decode()
    assert 'data-testid="analytics-export"' in html
    assert 'id="trend-tip"' in html, "the chart needs its tooltip element"
    assert 'id="trend-data"' in html, "the chart needs its data island"
    assert "spark-leads" in html, "leads were already computed and should be plotted"
