"""Website & forms settings tab (plan S6/D2): FormButton CRUD, HTMX toast on save."""
from __future__ import annotations

import pytest
from django.contrib.auth.models import User

from crm.models import FormButton

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


def test_forms_page_is_staff_only(client):
    assert client.get("/dashboard/settings/forms/").status_code in (302, 403)


def test_forms_page_creates_the_4_fixed_rows_on_get(staff, client):
    assert FormButton.objects.count() == 0
    r = client.get("/dashboard/settings/forms/")
    assert r.status_code == 200
    assert FormButton.objects.count() == 4
    assert set(FormButton.objects.values_list("category_slug", flat=True)) == {
        "heat_pump", "water_pump_well", "water_filtration", "quote_request",
    }


def test_forms_page_get_is_idempotent(staff, client):
    client.get("/dashboard/settings/forms/")
    client.get("/dashboard/settings/forms/")
    assert FormButton.objects.count() == 4


def test_forms_save_updates_all_rows(staff, client):
    client.get("/dashboard/settings/forms/")  # create-if-missing
    data = {}
    for slug, label in FormButton.CATEGORY:
        data[f"label_{slug}"] = f"{label} — kontakt"
        data[f"url_{slug}"] = f"https://www.nordlandvvs.se/{slug}"
    data["active_heat_pump"] = "on"
    r = client.post("/dashboard/settings/forms/", data)
    assert r.status_code == 302
    assert "HX-Trigger" in r.headers

    hp = FormButton.objects.get(category_slug="heat_pump")
    assert hp.url == "https://www.nordlandvvs.se/heat_pump"
    assert hp.is_active is True

    other = FormButton.objects.get(category_slug="water_pump_well")
    assert other.is_active is False  # checkbox omitted -> unchecked
