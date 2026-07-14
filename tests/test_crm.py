"""Sophisticated CRM: FK auto-assignment from conversations, chat-replica popup,
hyperlinked conversation/customer/brand/machine/type pages, and the from-session
customer-create flow."""
import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


@pytest.fixture
def staff(client):
    u = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(u)
    return u


def _machine():
    from kb.models import Machine
    return Machine.objects.filter(vendor__slug="ivt").select_related("vendor", "category").first()


def _session(**kw):
    from chat.models import Conversation
    from crm.models import Session
    conv = Conversation.objects.create(language=kw.pop("lang", "en"))
    return Session.objects.create(conversation=conv, **kw)


# ── enrichment: FK assignment from the conversation ───────────────────
def test_enrich_assigns_machine_brand_type_and_summary(seeded):
    from crm.models import Customer
    from crm.profile import enrich_customer_from_session
    m = _machine()
    sess = _session(machine=m, category=m.category, manufacturer=m.vendor.name,
                    model=m.model_name, error_code="E2", ai_summary="No heat; checked filter.")
    cust = Customer.objects.create(name="Test", phone="070-0000001")
    sess.customer = cust
    sess.save()
    enrich_customer_from_session(cust, sess)
    cust.refresh_from_db()
    assert cust.primary_machine_id == m.id
    assert cust.primary_brand_id == m.vendor_id
    assert cust.primary_category_id == m.category_id
    assert m.model_name in cust.equipment_summary
    # profile_summary is now a deterministic concise problem descriptor (senaste
    # ärende), not a raw copy of session.ai_summary — see crm.profile.build_problem_descriptor.
    assert m.model_name in cust.profile_summary
    assert "E2" in cust.profile_summary


def test_enrich_best_effort_brand_when_unsupported(seeded):
    from crm.models import Customer
    from crm.profile import enrich_customer_from_session
    from kb.models import Vendor
    v = Vendor.objects.exclude(slug="ivt").first() or Vendor.objects.first()  # any known brand
    sess = _session(manufacturer=v.name, model="Some Unit")  # no machine FK (unsupported)
    cust = Customer.objects.create(name="T", phone="070-0000002")
    sess.customer = cust
    sess.save()
    enrich_customer_from_session(cust, sess)
    cust.refresh_from_db()
    assert cust.primary_brand_id == v.id          # matched the typed brand to a known Vendor
    assert cust.primary_machine_id is None


# ── chat-replica popup ────────────────────────────────────────────────
def test_conversation_replica_renders_all_turn_types(staff, client, seeded):
    from chat.models import Message
    sess = _session()
    Message.objects.create(conversation=sess.conversation, role="user", content="UMSG")
    Message.objects.create(conversation=sess.conversation, role="assistant", content="BMSG")
    Message.objects.create(conversation=sess.conversation, role="tool", tool_name="vision_extract", tool_result={})
    r = client.get(f"/dashboard/sessions/{sess.pk}/replica")
    assert r.status_code == 200
    assert b"UMSG" in r.content and b"BMSG" in r.content and b"vision_extract" in r.content
    assert b'data-testid="chat-replica"' in r.content


def test_replica_requires_auth(client, seeded):
    sess = _session()
    assert client.get(f"/dashboard/sessions/{sess.pk}/replica").status_code == 302


# ── hyperlinking ──────────────────────────────────────────────────────
def test_customer_360_links_machine_brand_type_and_has_chat_popup(staff, client, seeded):
    from crm.models import Customer
    from crm.profile import enrich_customer_from_session
    m = _machine()
    sess = _session(machine=m, category=m.category, ai_summary="S")
    cust = Customer.objects.create(name="Erik", phone="070-0000003")
    sess.customer = cust
    sess.save()
    enrich_customer_from_session(cust, sess)
    html = client.get(f"/dashboard/customers/{cust.pk}/").content.decode()
    assert f"/dashboard/kb/machine/{m.pk}/" in html
    assert f"/dashboard/kb/vendor/{m.vendor_id}/" in html
    assert f"/dashboard/kb/category/{m.category_id}/" in html
    assert "open-replica" in html


def test_session_detail_hyperlinks_machine_and_type(staff, client, seeded):
    m = _machine()
    sess = _session(machine=m, category=m.category)
    html = client.get(f"/dashboard/sessions/{sess.pk}/").content.decode()
    assert f"/dashboard/kb/machine/{m.pk}/" in html
    assert f"/dashboard/kb/category/{m.category_id}/" in html
    assert "open-replica" in html


def test_session_list_has_customer_column_linked(staff, client, seeded):
    from crm.models import Customer
    cust = Customer.objects.create(name="Lena", phone="070-0000004")
    _session(customer=cust)
    html = client.get("/dashboard/sessions/").content.decode()
    assert "Customer" in html and f"/dashboard/customers/{cust.pk}/" in html


def test_kb_vendor_and_machine_show_related_crm(staff, client, seeded):
    m = _machine()
    assert b'data-testid="related-crm"' in client.get(f"/dashboard/kb/vendor/{m.vendor_id}/").content
    assert b'data-testid="related-crm"' in client.get(f"/dashboard/kb/machine/{m.pk}/").content


# ── equipment-type (category) pages ───────────────────────────────────
def test_category_list_and_detail(staff, client, seeded):
    from kb.models import Category
    cat = Category.objects.filter(machines__isnull=False).first()
    assert client.get("/dashboard/kb/categories/").status_code == 200
    r = client.get(f"/dashboard/kb/category/{cat.pk}/")
    assert r.status_code == 200 and cat.name.encode() in r.content


def test_category_pages_require_auth(client, seeded):
    assert client.get("/dashboard/kb/categories/").status_code == 302


# ── create-from-conversation ──────────────────────────────────────────
def test_customer_new_from_session_assigns_fks(staff, client, seeded):
    from crm.models import Customer
    m = _machine()
    sess = _session(machine=m, category=m.category, ai_summary="From convo")
    r = client.post(f"/dashboard/customers/new/?from_session={sess.pk}",
                    data={"name": "New Cust", "phone": "070-0000005"})
    assert r.status_code in (302, 200)
    cust = Customer.objects.get(name="New Cust")
    assert cust.primary_machine_id == m.id and cust.primary_brand_id == m.vendor_id
    # profile_summary is a deterministic concise problem descriptor (senaste ärende),
    # not a raw copy of session.ai_summary — see crm.profile.build_problem_descriptor.
    assert m.model_name in cust.profile_summary
