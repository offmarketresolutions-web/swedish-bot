"""A manual with no alarm-code table must never yield a code's meaning.

Caught on the live site: the IVT AirX 500 manuals document no codes at all, and the
specialist answered "E4 indikerar ett fel med flodesgivaren" on one production run and
"E4 betyder fel pa extern varmekalla" on another. Two different fabrications for the
same code, each stated to a homeowner as fact. The specialist prompt already said
"Never invent error-code meanings", so these tests pin the deterministic behaviour
rather than the wording of an instruction.
"""
import pytest

from chat import orchestrator as orch
from kb.alarms import machine_documents_codes
from kb.models import Category, Machine, MachineDocument, Vendor

pytestmark = pytest.mark.django_db


def _machine(**doc_kwargs):
    vendor = Vendor.objects.create(name="IVT", slug="ivt")
    cat, _ = Category.objects.get_or_create(slug="heat_pump", defaults={"name": "Heat pump"})
    machine = Machine.objects.create(vendor=vendor, category=cat, model_name="AirX 500",
                                     slug="airx-500")
    MachineDocument.objects.create(
        machine=machine, pdf="manuals/airx500.pdf", sha256="abc123", **doc_kwargs)
    return machine


# ── the verdict itself ────────────────────────────────────────────────
def test_scanned_manual_without_codes_reports_false():
    m = _machine(documents_alarm_codes=False, alarm_codes=[], alarm_scan_sha="abc123")
    assert machine_documents_codes(m) is False


def test_scanned_manual_with_codes_reports_true():
    m = _machine(documents_alarm_codes=True, alarm_codes=["E4"], alarm_scan_sha="abc123")
    assert machine_documents_codes(m) is True


def test_unscanned_manual_is_unknown_not_false():
    """An un-run scan must never make the bot refuse something it could answer."""
    m = _machine(alarm_scan_sha="")
    assert machine_documents_codes(m) is None


def test_replaced_manual_invalidates_the_old_verdict():
    """The scan is about specific bytes. New bytes, no verdict — not the old one."""
    m = _machine(documents_alarm_codes=False, alarm_scan_sha="abc123")
    doc = m.documents.get()
    doc.sha256 = "def456"  # manual replaced since the scan
    doc.save(update_fields=["sha256"])
    assert machine_documents_codes(m) is None


def test_one_manual_with_codes_is_enough():
    """Machines carry several manuals (AirBox + AirModule). Codes in either one count."""
    m = _machine(documents_alarm_codes=False, alarm_scan_sha="abc123")
    MachineDocument.objects.create(machine=m, pdf="manuals/b.pdf", sha256="zzz",
                                   alarm_scan_sha="zzz", documents_alarm_codes=True,
                                   alarm_codes=["E4"])
    assert machine_documents_codes(m) is True


# ── the gate the orchestrator applies ─────────────────────────────────
def test_gate_fires_only_with_a_code_and_a_codeless_manual():
    m = _machine(documents_alarm_codes=False, alarm_scan_sha="abc123")
    assert orch._code_ungrounded(m, {"slots": {"error_code": "E4"}}) is True
    # no code stated -> nothing to be wrong about
    assert orch._code_ungrounded(m, {"slots": {}}) is False


def test_gate_stays_shut_when_the_manual_documents_codes():
    m = _machine(documents_alarm_codes=True, alarm_codes=["E4"], alarm_scan_sha="abc123")
    assert orch._code_ungrounded(m, {"slots": {"error_code": "E4"}}) is False


def test_gate_stays_shut_when_the_manual_was_never_scanned():
    m = _machine(alarm_scan_sha="")
    assert orch._code_ungrounded(m, {"slots": {"error_code": "E4"}}) is False


def test_gate_survives_a_kb_error_without_changing_the_answer(monkeypatch):
    m = _machine(documents_alarm_codes=False, alarm_scan_sha="abc123")
    monkeypatch.setattr("kb.alarms.machine_documents_codes",
                        lambda _m: (_ for _ in ()).throw(RuntimeError("db down")))
    assert orch._code_ungrounded(m, {"slots": {"error_code": "E4"}}) is False


# ── what the customer actually reads ──────────────────────────────────
def test_the_invented_meaning_never_reaches_the_customer(monkeypatch):
    """The escalate path prints the draft answer ABOVE the handoff, so merely flipping
    the decision left the fabrication as the first thing the customer read."""
    m = _machine(documents_alarm_codes=False, alarm_scan_sha="abc123")
    conv, _ = orch.open_conversation("sv")
    cs = orch.new_case_state()
    cs["slots"] = {"category": "heat_pump", "brand": "IVT", "model": "AirX 500",
                   "problem": "Den visar E4 pa displayen", "error_code": "E4"}
    cs["machine_id"] = m.pk
    cs["match_confidence"] = 0.9
    cs["state"] = orch.STATE_SPECIALIST
    cs["contact"] = {"name": "Anna", "phone": "+46701234567"}

    invented = "Larmkod E4 indikerar ett fel med flodesgivaren i varmesystemet."
    monkeypatch.setattr(orch.gemini, "generate", lambda *a, **k: type("R", (), {"text": (
        '{"answer_to_customer": "' + invented + '", "decision": "solve", '
        '"confidence": 0.95, "in_docs": true, "severity": "normal", "report": {}}')})())
    monkeypatch.setattr(orch.context, "machine_pdf_context", lambda *a, **k: (None, []))

    out = orch._specialist_step(conv, cs, "Den visar E4 pa displayen", [], "sv")
    msg = out["message"]
    assert "flodesgivaren" not in msg, f"the fabricated meaning was shown: {msg}"
    assert "listar inga larmkoder" in msg, msg
    assert "E4" in msg  # it still names the code it cannot explain
    assert cs["decision"] == "escalate"
