"""V2 P-D — admin-configurable routing rules + best-practice injection."""
import pytest
from django.core.management import call_command

from chat import context
from chat import orchestrator as orch
from crm.models import Session
from kb.models import GenericGuide, Machine, RoutingRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def test_routing_rule_routes_to_maintenance(seeded, mock_gemini):
    RoutingRule.objects.create(name="leaks", match_keyword="leak", action="route_maintenance")
    mock_gemini.responses["specialist"] = {  # would "solve" — but the rule must pre-empt it
        "answer_to_customer": "Try X.", "confidence": 0.99, "decision": "solve",
        "in_docs": True, "report": {}}
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "it is leaking water badly")  # free-text problem w/ keyword
    orch.process_turn(conv, "IVT")
    res = orch.process_turn(conv, "IVT 490")
    assert res["decision"] == "escalate"
    assert not any(c["role"] == "specialist" for c in mock_gemini.calls)  # troubleshooting skipped
    assert Session.objects.get(conversation=conv).service_recommended is True


def test_urgent_rule_sets_urgent_severity(seeded, mock_gemini):
    RoutingRule.objects.create(name="flood", match_keyword="flood", action="urgent_contact")
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "water_pump_well")
    orch.process_turn(conv, "basement is flooding")
    orch.process_turn(conv, "Grundfos")
    orch.process_turn(conv, "Grundfos SQ")
    assert Session.objects.get(conversation=conv).severity == "urgent"


def test_best_practice_injected_into_specialist_context(seeded):
    machine = Machine.objects.get(model_name="IVT 490")
    GenericGuide.objects.create(category=machine.category, key="bp1", kind="best_practice",
                               lang="en", body="Always check the extract-air filter first.")
    _notes, faq = context.collect_knowledge(machine, "en")
    assert "best_practice" in faq and "check the extract-air filter first" in faq
