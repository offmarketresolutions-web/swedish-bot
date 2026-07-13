"""V2 P-C — configurable agents, vendor-scoped identification, thinking-on-complex."""
import pytest
from django.core.management import call_command

from chat import orchestrator as orch
from chat import prompts
from kb.identification import identify_machine
from kb.models import AgentPrompt, Category, Machine, Vendor

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def _solve(mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Check the filter.", "confidence": 0.9, "decision": "solve",
        "in_docs": True, "report": {}}


def _drive(conv):
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")          # postcode asked early (declined)
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "IVT")
    return orch.process_turn(conv, "IVT 490")


def _specialist_call(mock_gemini):
    return next(c for c in mock_gemini.calls if c["role"] == "specialist")


def test_config_for_defaults(seeded):
    cfg = prompts.config_for("specialist")
    assert cfg["model"] and cfg["thinking_budget"] == 0 and cfg["temperature"] == 0.4


def test_specialist_uses_db_config(seeded, mock_gemini):
    AgentPrompt.objects.filter(role="specialist").update(
        thinking_enabled=True, thinking_budget=512, max_output_tokens=1500, temperature=0.2)
    _solve(mock_gemini)
    conv, _ = orch.open_conversation()
    _drive(conv)
    kw = _specialist_call(mock_gemini)["kw"]
    assert kw["thinking_budget"] == 512
    assert kw["max_output_tokens"] == 1500
    assert kw["temperature"] == 0.2


def test_easy_case_has_no_thinking(seeded, mock_gemini):
    _solve(mock_gemini)
    conv, _ = orch.open_conversation()
    _drive(conv)  # IVT 490 matches strongly, no error code → not complex
    assert _specialist_call(mock_gemini)["kw"]["thinking_budget"] == 0


def test_vendor_scoped_identification_never_crosses_vendor(seeded):
    ivt = Vendor.objects.get(slug="ivt")
    other = Vendor.objects.create(name="OtherCo", slug="otherco")
    cat = Category.objects.get(slug="exhaust_air")
    Machine.objects.create(vendor=other, category=cat, model_name="Clone 490",
                           slug="other-490", aliases=["490", "ivt 490"])
    m, _ = identify_machine("ivt 490", vendor=ivt)
    assert m is None or m.vendor_id == ivt.id  # scoped result never belongs to OtherCo
