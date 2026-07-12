"""Customer File Hub: backfill migration logic, per-customer folder storage, file
registration on upload, the signed n8n Drive-mirror sink, and machine-doc resolution."""
import json

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
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


@pytest.fixture
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _machine():
    from kb.models import Machine
    return Machine.objects.filter(vendor__slug="ivt").select_related("vendor", "category").first()


# ── (1) backfill ───────────────────────────────────────────────────────
def test_backfill_creates_and_links_customer_from_case_state(media_tmp):
    from chat.models import Conversation
    from crm.backfill import backfill_customers
    from crm.models import Customer, Session, phone_hash
    conv = Conversation.objects.create(
        language="en",
        case_state={"contact": {"name": "Erik", "phone": "070-1234567", "email": "e@x.se", "postal_code": "12345"}})
    sess = Session.objects.create(conversation=conv, manufacturer="IVT", model="490")

    linked = backfill_customers()

    assert linked == 1
    sess.refresh_from_db()
    assert sess.customer_id is not None
    cust = Customer.objects.get(pk=sess.customer_id)
    assert cust.name == "Erik"
    assert cust.phone_hash == phone_hash("070-1234567")
    # idempotent: a second run links nothing new
    assert backfill_customers() == 0


def test_backfill_skips_sessions_without_contact(media_tmp):
    from chat.models import Conversation
    from crm.backfill import backfill_customers
    from crm.models import Session
    conv = Conversation.objects.create(language="en", case_state={"contact": {}})
    Session.objects.create(conversation=conv, manufacturer="IVT")
    assert backfill_customers() == 0


# ── (2) storage folder creation ────────────────────────────────────────
def test_ensure_folders_materializes_subfolders(media_tmp):
    from crm import storage
    from crm.models import Customer
    c = Customer.objects.create(name="Folder Test", phone="070-0000001")
    root = storage.ensure_folders(c)
    for sub in ("uploads", "invoices", "docs"):
        assert (root / sub).is_dir()
    assert root == media_tmp / "customers" / str(c.pk)


# ── (3) file registration + dedup ──────────────────────────────────────
def test_register_file_places_in_folder_and_dedups(media_tmp):
    from crm import storage
    from crm.models import Customer, CustomerFile
    c = Customer.objects.create(name="Reg", phone="070-0000002")
    cf, created = storage.register_file(
        c, content=b"hello-bytes", filename="quote.pdf", folder="invoices", source="staff")
    assert created and cf.folder == "invoices" and cf.source == "staff" and cf.kind == "pdf"
    assert f"customers/{c.pk}/invoices/" in cf.file.name
    assert (media_tmp / cf.file.name).exists()
    # same content → dedup, no second row
    cf2, created2 = storage.register_file(c, content=b"hello-bytes", filename="dup.pdf", folder="invoices")
    assert not created2 and cf2.pk == cf.pk
    assert CustomerFile.objects.filter(customer=c).count() == 1


def test_staff_upload_view_registers_into_chosen_folder(staff, client, media_tmp):
    from crm.models import Customer, CustomerFile
    c = Customer.objects.create(name="Up", phone="070-0000003")
    upload = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4 body", content_type="application/pdf")
    r = client.post(f"/dashboard/customers/{c.pk}/files/upload",
                    data={"file": upload, "folder": "invoices"})
    assert r.status_code in (302, 200)
    cf = CustomerFile.objects.get(customer=c)
    assert cf.folder == "invoices" and cf.source == "staff"


def test_chat_attach_registers_upload_folder(seeded, media_tmp):
    """attach_customer_files routes transcript photos through the File Hub."""
    from chat.models import Conversation, Message
    from crm.leads import attach_customer_files
    from crm.models import Customer, CustomerFile, Session
    conv = Conversation.objects.create(language="en")
    m = Message.objects.create(conversation=conv, role="user")
    m.image.save("p.jpg", ContentFile(b"imgdata"), save=True)
    sess = Session.objects.create(conversation=conv)
    cust = Customer.objects.create(name="Photo", phone="070-0000004")
    sess.customer = cust
    sess.save()
    n = attach_customer_files(sess)
    assert n == 1
    cf = CustomerFile.objects.get(customer=cust)
    assert cf.folder == "uploads" and cf.source == "chat"


# ── (4) signed n8n mirror sink ─────────────────────────────────────────
def test_mirror_sink_fires_signed_and_stores_drive_link(media_tmp, monkeypatch):
    from crm import file_sink, storage
    from crm.models import Customer, IntegrationSettings
    cfg = IntegrationSettings.load()
    cfg.n8n_webhook_url = "https://n8n.example.com/webhook/nordland-drive"
    cfg.n8n_shared_secret = "s3cr3t"
    cfg.n8n_enabled = True
    cfg.save()

    c = Customer.objects.create(name="Mirror", phone="070-0000005")
    cf, _ = storage.register_file(c, content=b"file-bytes", filename="a.pdf",
                                  folder="invoices", mirror=False)

    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"drive_url": "https://drive.google.com/file/xyz"}).encode()

    def fake_urlopen(req, timeout=10):
        captured["body"] = req.data
        captured["sig"] = req.get_header("X-nordland-signature")
        return _Resp()

    monkeypatch.setattr(file_sink.urllib.request, "urlopen", fake_urlopen)

    link = file_sink.mirror_customer_file(cf)
    assert link == "https://drive.google.com/file/xyz"
    # payload shape
    payload = json.loads(captured["body"])
    assert payload["customer_id"] == c.pk and payload["folder"] == "invoices"
    assert payload["filename"] == "a.pdf"
    # signature = HMAC-SHA256 of the exact body
    assert captured["sig"] == "sha256=" + file_sink.sign(captured["body"], "s3cr3t")


def test_mirror_sink_noop_when_disabled(media_tmp, monkeypatch):
    from crm import file_sink, storage
    from crm.models import Customer
    called = {"n": 0}
    monkeypatch.setattr(file_sink.urllib.request, "urlopen",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    c = Customer.objects.create(name="Off", phone="070-0000006")
    cf, _ = storage.register_file(c, content=b"x", filename="a.pdf", mirror=False)
    assert file_sink.mirror_customer_file(cf) is None
    assert called["n"] == 0


# ── (5) machine documentation resolution ───────────────────────────────
def test_machine_docs_shows_not_loaded_without_manual(staff, client, seeded):
    m = _machine()
    r = client.get(f"/dashboard/kb/machine/{m.pk}/docs")
    assert r.status_code == 200
    assert b"docs-not-loaded" in r.content


def test_machine_docs_serves_pdf_when_loaded(staff, client, seeded, media_tmp):
    from kb.models import MachineDocument
    m = _machine()
    doc = MachineDocument(machine=m, lang="sv", kind="manual")
    doc.pdf.save("manual.pdf", ContentFile(b"%PDF-1.4 mini"), save=True)
    r = client.get(f"/dashboard/kb/machine/{m.pk}/docs")
    assert r.status_code == 200
    assert b"machine-docs" in r.content
    assert f"/dashboard/kb/document/{doc.pk}/pdf".encode() in r.content


def test_customer_detail_renders_manifest_tabs(staff, client, seeded, media_tmp):
    from crm.models import Customer
    from crm.profile import enrich_customer_from_session
    from crm.models import Session
    from chat.models import Conversation
    m = _machine()
    conv = Conversation.objects.create(language="en")
    sess = Session.objects.create(conversation=conv, machine=m, category=m.category, ai_summary="S")
    cust = Customer.objects.create(name="Manifest", phone="070-0000007")
    sess.customer = cust
    sess.save()
    enrich_customer_from_session(cust, sess)
    html = client.get(f"/dashboard/customers/{cust.pk}/").content.decode()
    assert 'data-testid="customer-manifest"' in html
    assert 'data-testid="tab-docs"' in html
    # machine-doc modal link resolves to the docs endpoint
    assert f"/dashboard/kb/machine/{m.pk}/docs" in html
