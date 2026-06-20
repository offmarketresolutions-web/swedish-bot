"""Golden set (plan §14): the 5 canonical scenarios + PDF-cache wiring + robustness.
Behavioural assertions (decision / routing / guardrail / fields), Gemini mocked."""
import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from chat import orchestrator as orch
from crm.models import Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


# 1 — IVT 490 exhaust-air alarm → grounded safe solve
def test_g1_ivt490_alarm_solves(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Note the alarm code, then check the extract-air filter is clean.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {}}
    conv, _ = orch.open_conversation()
    for m in ("heat_pump", "no_heat", "IVT"):
        orch.process_turn(conv, m)
    res = orch.process_turn(conv, "IVT 490")
    assert res["decision"] == "solve"
    assert Session.objects.get(conversation=conv).machine.model_name == "IVT 490"


# 2 — low pressure on a well → routes to the well pump, safe handling
def test_g2_well_low_pressure(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Check the pressure gauge reading and tell me the number.",
        "confidence": 0.85, "decision": "solve", "in_docs": True, "report": {}}
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "water_pump_well")
    orch.process_turn(conv, "low_pressure")
    orch.process_turn(conv, "Grundfos")
    res = orch.process_turn(conv, "Grundfos SQ")
    sess = Session.objects.get(conversation=conv)
    assert sess.machine.model_name == "Grundfos SQ"
    assert res["decision"] in ("solve", "escalate")


# 3 — unsupported brand → qualified lead, no fabricated steps
def test_g3_unsupported_brand_leads(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "other")
    res = orch.process_turn(conv, "Mitsubishi MSZ-LN35")
    assert res["decision"] == "escalate"
    assert Session.objects.get(conversation=conv).machine is None


# 4 — nameplate photo → vision fills model → routes
def test_g4_nameplate_photo_identifies(seeded, mock_gemini):
    mock_gemini.responses["vision"] = {"manufacturer": "IVT", "model": "IVT 490",
                                       "serial": "SN123", "error_code": "E11"}
    mock_gemini.responses["specialist"] = {"answer_to_customer": "Check the filter.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {}}
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no_heat")
    photo = SimpleUploadedFile("plate.jpg", b"\xff\xd8\xff\xe0fakejpeg", content_type="image/jpeg")
    res = orch.process_turn(conv, "", image=photo)
    sess = Session.objects.get(conversation=conv)
    assert sess.model == "IVT 490"
    assert res["decision"] in ("solve", "escalate")


# 5 — dangerous request → never delivers forbidden steps, escalates
def test_g5_dangerous_request_refused(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "You should rewire the compressor and top up the refrigerant.",
        "confidence": 0.95, "decision": "solve", "in_docs": True, "report": {}}
    conv, _ = orch.open_conversation()
    for m in ("heat_pump", "no_heat", "IVT"):
        orch.process_turn(conv, m)
    res = orch.process_turn(conv, "IVT 490")
    assert res["decision"] == "escalate"
    assert "rewire" not in res["message"].lower()
    assert "refrigerant" not in res["message"].lower()


# PDF-cache wiring: a machine with a sizeable manual → specialist gets cached_content
def test_specialist_uses_context_cache(seeded, mock_gemini, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    from kb.models import Machine, MachineDocument
    machine = Machine.objects.get(model_name="IVT 490")
    doc = MachineDocument(machine=machine, lang="en", kind="manual", token_estimate=120000)
    doc.pdf.save("ivt490.pdf", ContentFile(b"%PDF-1.4 fake manual"), save=True)
    mock_gemini.responses["specialist"] = {"answer_to_customer": "Check filter.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {}}
    conv, _ = orch.open_conversation()
    for m in ("heat_pump", "no_heat", "IVT"):
        orch.process_turn(conv, m)
    orch.process_turn(conv, "IVT 490")
    specialist_calls = [c for c in mock_gemini.calls if c["role"] == "specialist"]
    assert specialist_calls
    assert specialist_calls[0]["kw"].get("cached_content") == "mock/cache/abc123"


# Robustness: malformed specialist output never crashes — it escalates safely
def test_malformed_specialist_output_escalates(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = "not json at all"
    conv, _ = orch.open_conversation()
    for m in ("heat_pump", "no_heat", "IVT"):
        orch.process_turn(conv, m)
    res = orch.process_turn(conv, "IVT 490")
    assert res["decision"] == "escalate"
    assert res["message"]


def test_empty_message_does_not_crash(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    res = orch.process_turn(conv, "")
    assert res["message"]  # still returns a coherent turn
