"""Cross-family review queue (spec §5 backlog: 92 pending FAQEntry + 10
pending SiteFAQ, previously only reviewable three family pages at a time).

Three surfaces, all built on the existing dash-faq-approve/reject endpoints
(dashboard/views.py) so approval logic lives in exactly one place:
  - dash-knowledge-review-queue: every pending entry, any family, one page,
    with corpus-wide "reviewed of total" progress and per-row checkboxes.
  - dash-knowledge-review-bulk-approve: approves only the checked ids.
  - dash-knowledge-review-next: one pending entry at a time with
    Approve/Edit/Reject/Skip, advancing through a deterministic queue order.

Assertions target data-testid/bindings, never English prose, per this repo's
rule that dashboard UI language can switch."""
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
def cats():
    hp = Category.objects.create(slug="heat_pump", name="Heat pump", group="heat")
    well = Category.objects.create(slug="water_pump_well", name="Water pump & well", group="water")
    return {"hp": hp, "well": well}


def _entry(cat, key, q="Q?", a="A.", **kw):
    e = FAQEntry.objects.create(category=cat, key=key, **kw)
    FAQEntryText.objects.create(faq=e, lang="sv", question=q, answer=a)
    return e


# ── Review queue page: cross-family listing + progress ─────────────────────

def test_review_queue_lists_pending_across_families(staff, client, cats):
    _entry(cats["hp"], "a", q="UNIQ_HP_PENDING", is_approved=False)
    _entry(cats["well"], "b", q="UNIQ_WELL_PENDING", is_approved=False)
    SiteFAQ.objects.create(slug="s1", question="UNIQ_SITE_PENDING", answer="A", is_approved=False)
    html = client.get(reverse("dash-knowledge-review-queue")).content.decode()
    assert "UNIQ_HP_PENDING" in html
    assert "UNIQ_WELL_PENDING" in html
    assert "UNIQ_SITE_PENDING" in html


def test_review_queue_excludes_approved(staff, client, cats):
    _entry(cats["hp"], "a", q="UNIQ_APPROVED_ROW", is_approved=True)
    html = client.get(reverse("dash-knowledge-review-queue")).content.decode()
    assert "UNIQ_APPROVED_ROW" not in html


def test_review_progress_counts_are_corpus_wide(staff, client, cats):
    _entry(cats["hp"], "a", is_approved=True)
    _entry(cats["hp"], "b", is_approved=False)
    _entry(cats["well"], "c", is_approved=False)
    SiteFAQ.objects.create(slug="s1", question="Q", answer="A", is_approved=True)
    resp = client.get(reverse("dash-knowledge-review-queue"))
    assert resp.status_code == 200
    ctx = resp.context
    # 2 approved (1 entry + 1 site) of 4 total rows
    assert ctx["reviewed_count"] == 2
    assert ctx["total_count"] == 4


def test_review_queue_requires_staff(client, cats):
    resp = client.get(reverse("dash-knowledge-review-queue"))
    assert resp.status_code == 302
    assert "login" in resp["Location"]


# ── Bulk approve: only explicitly selected ids ──────────────────────────────

def test_bulk_approve_only_touches_selected_ids(staff, client, cats):
    e1 = _entry(cats["hp"], "a", is_approved=False)
    e2 = _entry(cats["hp"], "b", is_approved=False)
    s1 = SiteFAQ.objects.create(slug="s1", question="Q1", answer="A", is_approved=False)
    resp = client.post(reverse("dash-knowledge-review-bulk-approve"),
                        {"selected": [f"entry:{e1.pk}", f"site:{s1.pk}"]})
    assert resp.status_code == 200
    e1.refresh_from_db(); e2.refresh_from_db(); s1.refresh_from_db()
    assert e1.is_approved is True
    assert e2.is_approved is False  # not selected — left untouched
    assert s1.is_approved is True


def test_bulk_approve_with_nothing_selected_approves_nothing(staff, client, cats):
    e1 = _entry(cats["hp"], "a", is_approved=False)
    resp = client.post(reverse("dash-knowledge-review-bulk-approve"), {})
    assert resp.status_code == 200
    e1.refresh_from_db()
    assert e1.is_approved is False


def test_bulk_approve_requires_post(staff, client, cats):
    resp = client.get(reverse("dash-knowledge-review-bulk-approve"))
    assert resp.status_code == 405


def test_bulk_approve_requires_staff(client, cats):
    e1 = _entry(cats["hp"], "a", is_approved=False)
    resp = client.post(reverse("dash-knowledge-review-bulk-approve"), {"selected": [f"entry:{e1.pk}"]})
    assert resp.status_code == 302
    e1.refresh_from_db()
    assert e1.is_approved is False


# ── Review-next: one at a time, Approve/Edit/Reject/Skip ────────────────────

def test_review_next_shows_first_pending_item(staff, client, cats):
    _entry(cats["hp"], "a", q="UNIQ_FIRST_PENDING", is_approved=False)
    html = client.get(reverse("dash-knowledge-review-next")).content.decode()
    assert "UNIQ_FIRST_PENDING" in html
    assert 'data-testid="review-next-item"' in html


def test_review_next_empty_state_when_nothing_pending(staff, client, cats):
    resp = client.get(reverse("dash-knowledge-review-next"))
    assert resp.status_code == 200
    assert resp.context["item"] is None


def test_review_next_approve_advances_to_next_entry(staff, client, cats):
    e1 = _entry(cats["hp"], "a", q="UNIQ_ONE", is_approved=False)
    e2 = _entry(cats["hp"], "b", q="UNIQ_TWO", is_approved=False)
    resp = client.get(reverse("dash-knowledge-review-next"))
    approve_url = resp.context["approve_url"]
    this_url = resp.context["this_url"]
    assert approve_url == reverse("dash-faq-approve", args=["entry", e1.pk])

    resp2 = client.post(approve_url, {"next": this_url})
    assert resp2.status_code == 302
    e1.refresh_from_db()
    assert e1.is_approved is True

    resp3 = client.get(resp2["Location"])
    html = resp3.content.decode()
    assert "UNIQ_TWO" in html
    assert "UNIQ_ONE" not in html


def test_review_next_reject_deletes_and_advances(staff, client, cats):
    e1 = _entry(cats["hp"], "a", q="UNIQ_REJECT_ME", is_approved=False)
    e2 = _entry(cats["hp"], "b", q="UNIQ_SURVIVOR", is_approved=False)
    resp = client.get(reverse("dash-knowledge-review-next"))
    reject_url = resp.context["reject_url"]
    this_url = resp.context["this_url"]

    resp2 = client.post(reject_url, {"next": this_url})
    assert resp2.status_code == 302
    assert not FAQEntry.objects.filter(pk=e1.pk).exists()

    html = client.get(resp2["Location"]).content.decode()
    assert "UNIQ_SURVIVOR" in html


def test_review_next_skip_moves_past_without_changing_approval(staff, client, cats):
    e1 = _entry(cats["hp"], "a", q="UNIQ_SKIP_ME", is_approved=False)
    e2 = _entry(cats["hp"], "b", q="UNIQ_AFTER_SKIP", is_approved=False)
    resp = client.get(reverse("dash-knowledge-review-next"))
    skip_url = resp.context["skip_url"]

    html = client.get(skip_url).content.decode()
    assert "UNIQ_AFTER_SKIP" in html
    assert "UNIQ_SKIP_ME" not in html

    e1.refresh_from_db()
    assert e1.is_approved is False  # skip never touches approval state


def test_review_next_edit_link_returns_to_queue_position(staff, client, cats):
    _entry(cats["hp"], "a", q="UNIQ_EDIT_TARGET", is_approved=False)
    resp = client.get(reverse("dash-knowledge-review-next"))
    edit_url = resp.context["edit_url"]
    assert edit_url.startswith(reverse("dash-knowledge-entry-edit", args=[resp.context["pk"]]))
    assert "next=" in edit_url


def test_review_next_requires_staff(client, cats):
    resp = client.get(reverse("dash-knowledge-review-next"))
    assert resp.status_code == 302
    assert "login" in resp["Location"]


# ── Edit never silently approves (existing behaviour, must survive) ────────

def test_edit_from_review_flow_does_not_approve(staff, client, cats):
    e = _entry(cats["hp"], "a", q="OLD_Q", is_approved=False)
    url = reverse("dash-knowledge-entry-edit", args=[e.pk])
    resp = client.post(url, {
        "category": cats["hp"].pk, "question": "NEW_Q", "answer": "NEW_A",
        "onset_type": "", "safe_customer_checks": "", "service_trigger": "",
        "keywords": "", "exclusions": "",
    })
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.is_approved is False
    assert e.text("sv").question == "NEW_Q"
