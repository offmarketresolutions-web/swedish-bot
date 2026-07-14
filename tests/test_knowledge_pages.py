"""General Knowledge curation pages: one dashboard page per category family
(heat-pump / water-pump-well / water-filtration / site) with search + filters,
approve/unapprove, full-metadata create/edit, and delete."""
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from kb.models import Category, FAQEntry, FAQEntryText, SiteFAQ, Vendor

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def cats():
    hp = Category.objects.create(slug="heat_pump", name="Heat pump", group="heat")
    rad = Category.objects.create(slug="radiators", name="Radiators", parent=hp, group="heat")
    floor = Category.objects.create(slug="floor_heating", name="Floor heating", parent=hp, group="heat")
    w2w = Category.objects.create(slug="water_to_water", name="Water to water", parent=hp, group="heat")
    well = Category.objects.create(slug="water_pump_well", name="Water pump & well", group="water")
    filt = Category.objects.create(slug="water_filtration", name="Water filtration", group="water")
    return {"hp": hp, "rad": rad, "floor": floor, "w2w": w2w, "well": well, "filt": filt}


def _entry(cat, key, q="Q?", a="A.", **kw):
    e = FAQEntry.objects.create(category=cat, key=key, **kw)
    FAQEntryText.objects.create(faq=e, lang="sv", question=q, answer=a)
    return e


def test_index_redirects_to_heat_pump(staff, client, cats):
    resp = client.get(reverse("dash-knowledge-index"))
    assert resp.status_code == 302
    assert reverse("dash-knowledge", args=["heat-pump"]) in resp["Location"]


def test_each_family_page_200(staff, client, cats):
    for fam in ("heat-pump", "water-pump-well", "water-filtration", "site"):
        assert client.get(reverse("dash-knowledge", args=[fam])).status_code == 200


def test_unknown_family_404(staff, client, cats):
    assert client.get(reverse("dash-knowledge", args=["bogus"])).status_code == 404


def test_heat_pump_scoping_includes_leaves_excludes_water(staff, client, cats):
    _entry(cats["rad"], "rad1", q="UNIQ_RADIATOR_Q")
    _entry(cats["floor"], "floor1", q="UNIQ_FLOOR_Q")
    _entry(cats["hp"], "hp1", q="UNIQ_HP_Q")
    _entry(cats["well"], "well1", q="UNIQ_WELL_Q")
    _entry(cats["filt"], "filt1", q="UNIQ_FILT_Q")
    html = client.get(reverse("dash-knowledge", args=["heat-pump"])).content.decode()
    assert "UNIQ_RADIATOR_Q" in html
    assert "UNIQ_FLOOR_Q" in html
    assert "UNIQ_HP_Q" in html
    assert "UNIQ_WELL_Q" not in html
    assert "UNIQ_FILT_Q" not in html


def test_water_pages_scoped(staff, client, cats):
    _entry(cats["well"], "well1", q="UNIQ_WELL_Q")
    _entry(cats["filt"], "filt1", q="UNIQ_FILT_Q")
    well_html = client.get(reverse("dash-knowledge", args=["water-pump-well"])).content.decode()
    filt_html = client.get(reverse("dash-knowledge", args=["water-filtration"])).content.decode()
    assert "UNIQ_WELL_Q" in well_html and "UNIQ_FILT_Q" not in well_html
    assert "UNIQ_FILT_Q" in filt_html and "UNIQ_WELL_Q" not in filt_html


def test_search_filters_by_question_answer_keywords(staff, client, cats):
    _entry(cats["hp"], "a", q="Kompressorn låter konstigt")
    _entry(cats["hp"], "b", q="Annat", a="Svar om expansionskärl")
    _entry(cats["hp"], "c", q="Tredje", keywords=["frostskydd", "glykol"])
    url = reverse("dash-knowledge", args=["heat-pump"])
    html = client.get(url, {"q": "kompressor"}).content.decode()
    assert "Kompressorn" in html and "expansionskärl" not in html
    html = client.get(url, {"q": "expansionskärl"}).content.decode()
    assert "expansionskärl" in html and "Kompressorn" not in html
    html = client.get(url, {"q": "frostskydd"}).content.decode()
    assert "Tredje" in html and "Kompressorn" not in html


def test_subtype_filter(staff, client, cats):
    _entry(cats["hp"], "a", q="UNIQ_RAD_ONLY", applicable_subtypes=["radiators"])
    _entry(cats["hp"], "b", q="UNIQ_W2W_ONLY", applicable_subtypes=["water_to_water"])
    url = reverse("dash-knowledge", args=["heat-pump"])
    html = client.get(url, {"subtype": "radiators"}).content.decode()
    assert "UNIQ_RAD_ONLY" in html and "UNIQ_W2W_ONLY" not in html


def test_status_filter(staff, client, cats):
    _entry(cats["hp"], "a", q="UNIQ_APPROVED", is_approved=True)
    _entry(cats["hp"], "b", q="UNIQ_PENDING", is_approved=False)
    url = reverse("dash-knowledge", args=["heat-pump"])
    html = client.get(url, {"status": "pending"}).content.decode()
    assert "UNIQ_PENDING" in html and "UNIQ_APPROVED" not in html
    html = client.get(url, {"status": "approved"}).content.decode()
    assert "UNIQ_APPROVED" in html and "UNIQ_PENDING" not in html


def test_create_entry_with_full_metadata(staff, client, cats):
    vendor = Vendor.objects.create(name="IVT", slug="ivt")
    url = reverse("dash-knowledge-new", args=["heat-pump"])
    assert client.get(url).status_code == 200
    resp = client.post(url, {
        "category": cats["hp"].pk,
        "question": "UNIQ_NEW_Q", "answer": "UNIQ_NEW_A",
        "applicable_subtypes": ["radiators", "floor_heating"],
        "onset_type": "sudden",
        "safe_customer_checks": "Kolla filtret.",
        "service_trigger": "Läckage",
        "keywords": "kompressor, glykol",
        "manufacturer": vendor.pk,
        "exclusions": "Inte för luft-luft.",
    })
    assert resp.status_code == 302
    e = FAQEntry.objects.get(texts__question="UNIQ_NEW_Q")
    assert e.category == cats["hp"]
    assert e.applicable_subtypes == ["radiators", "floor_heating"]
    assert e.onset_type == "sudden"
    assert e.safe_customer_checks == "Kolla filtret."
    assert e.service_trigger == "Läckage"
    assert e.keywords == ["kompressor", "glykol"]
    assert e.manufacturer == vendor
    assert e.exclusions == "Inte för luft-luft."
    html = client.get(reverse("dash-knowledge", args=["heat-pump"])).content.decode()
    assert "UNIQ_NEW_Q" in html


def test_edit_preserves_approval(staff, client, cats):
    e = _entry(cats["hp"], "a", q="OLD_Q", is_approved=True)
    url = reverse("dash-knowledge-entry-edit", args=[e.pk])
    resp = client.post(url, {
        "category": cats["hp"].pk, "question": "NEW_Q", "answer": "NEW_A",
        "onset_type": "", "safe_customer_checks": "", "service_trigger": "",
        "keywords": "", "exclusions": "",
    })
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.is_approved is True
    assert e.text("sv").question == "NEW_Q"


def test_toggle_approval(staff, client, cats):
    e = _entry(cats["hp"], "a", is_approved=True)
    url = reverse("dash-knowledge-toggle", args=["entry", e.pk])
    resp = client.post(url + "?family=heat-pump")
    assert resp.status_code == 200
    e.refresh_from_db()
    assert e.is_approved is False
    client.post(url + "?family=heat-pump")
    e.refresh_from_db()
    assert e.is_approved is True


def test_delete_entry_post_only(staff, client, cats):
    e = _entry(cats["hp"], "a")
    url = reverse("dash-knowledge-delete", args=["entry", e.pk])
    assert client.get(url + "?family=heat-pump").status_code == 405
    assert FAQEntry.objects.filter(pk=e.pk).exists()
    resp = client.post(url + "?family=heat-pump")
    assert resp.status_code == 200
    assert not FAQEntry.objects.filter(pk=e.pk).exists()


def test_site_page_shows_site_faqs(staff, client, cats):
    SiteFAQ.objects.create(slug="s1", question="UNIQ_SITE_Q", answer="A", topic="rot")
    html = client.get(reverse("dash-knowledge", args=["site"])).content.decode()
    assert "UNIQ_SITE_Q" in html


def test_site_faq_toggle_and_delete(staff, client, cats):
    s = SiteFAQ.objects.create(slug="s1", question="Q", answer="A", is_approved=True)
    resp = client.post(reverse("dash-knowledge-toggle", args=["site", s.pk]) + "?family=site")
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.is_approved is False
    resp = client.post(reverse("dash-knowledge-delete", args=["site", s.pk]) + "?family=site")
    assert resp.status_code == 200
    assert not SiteFAQ.objects.filter(pk=s.pk).exists()


def test_site_faq_edit_preserves_approval(staff, client, cats):
    s = SiteFAQ.objects.create(slug="s1", question="OLD", answer="A", is_approved=True)
    url = reverse("dash-knowledge-site-edit", args=[s.pk])
    resp = client.post(url, {"topic": "rot", "question": "NEW", "answer": "B", "lang": "sv"})
    assert resp.status_code == 302
    s.refresh_from_db()
    assert s.question == "NEW" and s.is_approved is True


def test_non_staff_redirected(client, cats):
    for name, args in (
        ("dash-knowledge-index", []),
        ("dash-knowledge", ["heat-pump"]),
        ("dash-knowledge-new", ["heat-pump"]),
    ):
        resp = client.get(reverse(name, args=args))
        assert resp.status_code == 302
        assert "login" in resp["Location"]
