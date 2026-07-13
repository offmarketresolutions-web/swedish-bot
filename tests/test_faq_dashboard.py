"""Dashboard FAQ approval UI (V2 plan §D2 / Sprint S1): unapproved FAQEntry/
SiteFAQ rows show in a "Väntar på godkännande" section on the FAQ page, with
per-row Approve/Reject HTMX actions (mirrors the guardrail_toggle pattern)."""
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from kb.models import Category, FAQEntry, FAQEntryText, SiteFAQ

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def cat():
    return Category.objects.create(slug="heat_pump", name="Heat pump")


def test_faq_page_lists_pending_entry(staff, client, cat):
    entry = FAQEntry.objects.create(category=cat, key="pending1", is_approved=False,
                                    applicable_subtypes=["water_to_water"], onset_type="sudden")
    FAQEntryText.objects.create(faq=entry, lang="sv", question="UNIQ_PENDING_Q", answer="UNIQ_PENDING_A")
    html = client.get(reverse("dash-faq")).content.decode()
    assert "UNIQ_PENDING_Q" in html
    assert "Väntar på godkännande" in html
    assert "water_to_water" in html


def test_faq_page_lists_pending_site_faq(staff, client):
    SiteFAQ.objects.create(slug="pending-site", question="UNIQ_SITE_PENDING_Q",
                           answer="A", is_approved=False)
    html = client.get(reverse("dash-faq")).content.decode()
    assert "UNIQ_SITE_PENDING_Q" in html


def test_approved_entries_not_in_pending_section(staff, client, cat):
    entry = FAQEntry.objects.create(category=cat, key="approved1", is_approved=True)
    FAQEntryText.objects.create(faq=entry, lang="sv", question="UNIQ_APPROVED_Q", answer="A")
    html = client.get(reverse("dash-faq")).content.decode()
    assert "UNIQ_APPROVED_Q" not in html  # approved rows aren't in the pending list
    # (public site-FAQ listing above only shows SiteFAQ, not FAQEntry, by design)


def test_faq_approve_entry_flips_flag_and_removes_from_pending(staff, client, cat):
    entry = FAQEntry.objects.create(category=cat, key="pending2", is_approved=False)
    resp = client.post(reverse("dash-faq-approve", args=["entry", entry.pk]))
    assert resp.status_code == 200
    entry.refresh_from_db()
    assert entry.is_approved is True
    assert "HX-Trigger" in resp


def test_faq_reject_entry_deletes_it(staff, client, cat):
    entry = FAQEntry.objects.create(category=cat, key="pending3", is_approved=False)
    resp = client.post(reverse("dash-faq-reject", args=["entry", entry.pk]))
    assert resp.status_code == 200
    assert not FAQEntry.objects.filter(pk=entry.pk).exists()


def test_faq_approve_site_faq(staff, client):
    faq = SiteFAQ.objects.create(slug="approve-me", question="Q", answer="A", is_approved=False)
    resp = client.post(reverse("dash-faq-approve", args=["site", faq.pk]))
    assert resp.status_code == 200
    faq.refresh_from_db()
    assert faq.is_approved is True


def test_faq_reject_site_faq_deletes(staff, client):
    faq = SiteFAQ.objects.create(slug="reject-me", question="Q", answer="A", is_approved=False)
    resp = client.post(reverse("dash-faq-reject", args=["site", faq.pk]))
    assert resp.status_code == 200
    assert not SiteFAQ.objects.filter(pk=faq.pk).exists()


def test_faq_approve_requires_staff(client, cat):
    entry = FAQEntry.objects.create(category=cat, key="pending4", is_approved=False)
    resp = client.post(reverse("dash-faq-approve", args=["entry", entry.pk]))
    assert resp.status_code in (302, 403)  # redirected to login / forbidden
    entry.refresh_from_db()
    assert entry.is_approved is False


def test_faq_approve_bad_kind_404s(staff, client):
    resp = client.post(reverse("dash-faq-approve", args=["bogus", 1]))
    assert resp.status_code == 404


def test_faq_approve_requires_post(staff, client, cat):
    entry = FAQEntry.objects.create(category=cat, key="pending5", is_approved=False)
    resp = client.get(reverse("dash-faq-approve", args=["entry", entry.pk]))
    assert resp.status_code == 405
