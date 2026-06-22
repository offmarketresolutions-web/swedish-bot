"""V2 P-D UI — staff KB Manager + Agent Config screens (HTMX views).
Covers auth gating, inline agent save + validation, machine panel, PDF
upload/replace (with re-ingest), notes, and per-vendor notes."""
import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from kb.models import AgentPrompt, Machine, Vendor

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _pdf_bytes(text="IVT 490 error E1 means low pressure. Read the display code."):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.multi_cell(0, 10, text)
    return bytes(pdf.output())


# ── auth gate ─────────────────────────────────────────────────────────
def test_kb_requires_auth(client):
    assert client.get("/dashboard/kb/").status_code == 302


def test_agents_requires_auth(client):
    assert client.get("/dashboard/agents/").status_code == 302


# ── Agent Config ──────────────────────────────────────────────────────
def test_agent_config_lists_prompts(staff, client, seeded):
    r = client.get("/dashboard/agents/")
    assert r.status_code == 200
    assert b"Agent Configuration" in r.content
    assert b"specialist" in r.content


def test_agents_page_has_clickable_flow_map(staff, client, seeded):
    r = client.get("/dashboard/agents/")
    assert b'data-testid="agent-map"' in r.content
    # every agent node links to its own detail page
    for role in ("intake", "router", "specialist", "intelligent_intake", "safety", "summarizer"):
        assert f"/dashboard/agents/{role}/".encode() in r.content


def test_agent_detail_page_renders_config(staff, client, seeded):
    r = client.get("/dashboard/agents/specialist/")
    assert r.status_code == 200
    assert b'data-testid="agent-detail"' in r.content
    assert b'data-testid="agent-card-specialist"' in r.content   # the editable form
    assert b'data-testid="agent-map"' in r.content               # flow context
    assert b"Live in production" in r.content or b"live" in r.content.lower()


def test_agent_detail_requires_auth(client, seeded):
    assert client.get("/dashboard/agents/specialist/").status_code == 302


def test_agent_detail_unknown_role_404(staff, client, seeded):
    assert client.get("/dashboard/agents/not-a-real-agent/").status_code == 404


# ── AI prompt assistant (append-only, proposes — never auto-saves) ─────
def test_agent_prompt_assist_proposes_without_saving(staff, client, seeded, mock_gemini):
    p = AgentPrompt.objects.get(role="specialist")
    # the assist sends the agent's body in `contents`, so the mock classifies as "specialist"
    mock_gemini.responses["specialist"] = "FULL PROMPT ... plus EXTRA-GUARDRAIL line"
    r = client.post(f"/dashboard/agents/{p.pk}/assist", data={"instruction": "add a guardrail about draining tanks"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "EXTRA-GUARDRAIL" in r.json()["body"]
    p.refresh_from_db()
    assert "EXTRA-GUARDRAIL" not in p.body   # proposed only — not persisted until admin Saves


def test_agent_prompt_assist_requires_instruction(staff, client, seeded, mock_gemini):
    p = AgentPrompt.objects.get(role="specialist")
    assert client.post(f"/dashboard/agents/{p.pk}/assist", data={"instruction": "   "}).status_code == 400


def test_agent_prompt_assist_requires_auth(client, seeded):
    p = AgentPrompt.objects.get(role="specialist")
    assert client.post(f"/dashboard/agents/{p.pk}/assist", data={"instruction": "x"}).status_code == 302


def test_agent_save_updates_fields(staff, client, seeded):
    p = AgentPrompt.objects.get(role="specialist")
    r = client.post(f"/dashboard/agents/{p.pk}/save", data={
        "model_id": "gemini-2.5-flash", "temperature": "0.7",
        "thinking_budget": "256", "max_output_tokens": "2048",
        "thinking_enabled": "on", "is_active": "on",
        "language_directive": p.language_directive, "body": "NEW SPECIALIST BODY",
    })
    assert r.status_code == 200
    assert b"Saved" in r.content
    p.refresh_from_db()
    assert p.body == "NEW SPECIALIST BODY"
    assert p.temperature == 0.7 and p.thinking_enabled is True
    assert p.thinking_budget == 256 and p.max_output_tokens == 2048


def test_agent_save_rejects_out_of_range(staff, client, seeded):
    p = AgentPrompt.objects.get(role="specialist")
    old_body = p.body
    r = client.post(f"/dashboard/agents/{p.pk}/save", data={
        "model_id": "gemini-2.5-flash", "temperature": "9.5",
        "thinking_budget": "0", "body": "SHOULD NOT PERSIST",
    })
    assert r.status_code == 200
    assert b"out of range" in r.content
    p.refresh_from_db()
    assert p.body == old_body  # fail-closed: nothing saved


def test_agent_save_requires_model_id(staff, client, seeded):
    p = AgentPrompt.objects.get(role="router")
    r = client.post(f"/dashboard/agents/{p.pk}/save", data={"model_id": "  ", "body": "x", "thinking_budget": "0"})
    assert b"model_id required" in r.content


# ── KB Manager ────────────────────────────────────────────────────────
def test_kb_manager_renders_tree(staff, client, seeded):
    r = client.get("/dashboard/kb/")
    assert r.status_code == 200
    assert b"Knowledge Base Manager" in r.content
    assert b"IVT" in r.content


def test_machine_panel_loads(staff, client, seeded):
    m = Machine.objects.get(model_name="IVT 490")
    r = client.get(f"/dashboard/kb/machine/{m.pk}/")
    assert r.status_code == 200
    assert b"machine-panel" in r.content and b"IVT 490" in r.content


def test_pdf_upload_ingests(staff, client, seeded, media):
    m = Machine.objects.get(model_name="IVT 490")
    f = SimpleUploadedFile("manual.pdf", _pdf_bytes(), content_type="application/pdf")
    r = client.post(f"/dashboard/kb/machine/{m.pk}/upload", data={"pdf": f, "lang": "sv", "kind": "manual"})
    assert r.status_code == 200
    doc = m.documents.get()
    assert doc.token_estimate > 0 and doc.sha256
    assert "low pressure" in doc.parsed_text.lower()  # actually parsed, not just stored


def test_non_pdf_upload_rejected(staff, client, seeded, media):
    m = Machine.objects.get(model_name="IVT 490")
    f = SimpleUploadedFile("evil.pdf", b"<html>not a pdf</html>", content_type="application/pdf")
    r = client.post(f"/dashboard/kb/machine/{m.pk}/upload", data={"pdf": f})
    assert r.status_code == 200
    assert b"Not a PDF" in r.content
    assert m.documents.count() == 0  # fail-closed


def test_pdf_replace_overwrites_in_place(staff, client, seeded, media):
    import os
    m = Machine.objects.get(model_name="IVT 490")
    client.post(f"/dashboard/kb/machine/{m.pk}/upload",
                data={"pdf": SimpleUploadedFile("a.pdf", _pdf_bytes("alpha first text"), content_type="application/pdf"),
                      "lang": "sv", "kind": "manual"})
    doc = m.documents.get()
    old_sha, old_path = doc.sha256, doc.pdf.path
    client.post(f"/dashboard/kb/machine/{m.pk}/upload",
                data={"pdf": SimpleUploadedFile("b.pdf", _pdf_bytes("beta second text"), content_type="application/pdf"),
                      "lang": "sv", "kind": "manual", "replace_id": str(doc.pk)})
    assert m.documents.count() == 1  # replaced, not appended
    doc.refresh_from_db()
    assert doc.sha256 != old_sha and "beta" in doc.parsed_text.lower()
    assert not os.path.exists(old_path)  # superseded file cleaned up (no orphan leak)


def test_pdf_served_inline_for_preview(staff, client, seeded, media):
    m = Machine.objects.get(model_name="IVT 490")
    client.post(f"/dashboard/kb/machine/{m.pk}/upload",
                data={"pdf": SimpleUploadedFile("a.pdf", _pdf_bytes(), content_type="application/pdf"),
                      "lang": "sv", "kind": "manual"})
    doc = m.documents.get()
    r = client.get(f"/dashboard/kb/document/{doc.pk}/pdf")
    assert r.status_code == 200
    assert r["Content-Type"] == "application/pdf"
    assert "inline" in r["Content-Disposition"]                 # renders in the viewer, not a download
    assert r["X-Content-Type-Options"] == "nosniff"
    assert r.get("X-Frame-Options") == "SAMEORIGIN"             # embeddable in the same-origin preview iframe
    assert b"".join(r.streaming_content)[:5] == b"%PDF-"
    rd = client.get(f"/dashboard/kb/document/{doc.pk}/pdf?download=1")
    assert "attachment" in rd["Content-Disposition"]


def test_pdf_preview_requires_login(client):
    assert client.get("/dashboard/kb/document/1/pdf").status_code == 302


def test_oversized_upload_rejected_before_read(staff, client, seeded, media, monkeypatch):
    from kb import ingest
    monkeypatch.setattr(ingest, "MAX_PDF_BYTES", 100)  # force the size gate
    m = Machine.objects.get(model_name="IVT 490")
    f = SimpleUploadedFile("big.pdf", _pdf_bytes("x" * 800), content_type="application/pdf")
    r = client.post(f"/dashboard/kb/machine/{m.pk}/upload", data={"pdf": f})
    assert r.status_code == 200
    assert b"too large" in r.content.lower()
    assert m.documents.count() == 0  # rejected, nothing ingested


def test_note_add(staff, client, seeded):
    m = Machine.objects.get(model_name="IVT 490")
    r = client.post(f"/dashboard/kb/machine/{m.pk}/note", data={"body": "Filter is behind the front grille."})
    assert r.status_code == 200
    assert m.notes.filter(body__icontains="front grille").exists()
    assert b"front grille" in r.content


def test_notes_paginated_load_more(staff, client, seeded):
    from kb.models import MachineNote
    m = Machine.objects.get(model_name="IVT 490")
    for i in range(7):
        MachineNote.objects.create(machine=m, body=f"NOTE{i:02d}")
    page = client.get(f"/dashboard/kb/machine/{m.pk}/").content.decode()
    assert page.count("NOTE0") == 5            # first page = 5
    assert "notes-load-more" in page           # has a load-more control
    more = client.get(f"/dashboard/kb/machine/{m.pk}/notes?offset=5").content.decode()
    assert more.count("NOTE0") == 2            # next page = remaining 2 (SQL LIMIT/OFFSET)
    assert "notes-load-more" not in more       # no more pages


def test_note_delete(staff, client, seeded):
    from kb.models import MachineNote
    m = Machine.objects.get(model_name="IVT 490")
    n = MachineNote.objects.create(machine=m, body="DELETE_ME")
    r = client.post(f"/dashboard/kb/note/{n.pk}/delete")
    assert r.status_code == 200
    assert not MachineNote.objects.filter(pk=n.pk).exists()
    assert b"DELETE_ME" not in r.content


def test_vendor_notes_save(staff, client, seeded):
    v = Vendor.objects.get(slug="ivt")
    r = client.post(f"/dashboard/kb/vendor/{v.pk}/notes", data={"agent_notes": "Prefer the Swedish error tables."})
    assert r.status_code == 200
    v.refresh_from_db()
    assert "Swedish error tables" in v.agent_notes
    assert b"Saved" in r.content
