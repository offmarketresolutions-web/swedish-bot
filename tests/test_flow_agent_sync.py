"""The flow builder must keep describing the bot it configures.

The canvas graph is saved once and then hand-arranged; AgentPrompt rows are added,
switched off and deleted independently. Nothing connected the two, so adding an agent left
it invisible on the canvas and deleting one left a step pointing at nothing — and neither
said so anywhere.

The contract here is deliberately NOT "rewrite the graph": a GET must not write, and the
owner's arrangement is their work. It is "never let the two drift silently".
"""
from __future__ import annotations

import json
import re

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from dashboard.views import _flow_agent_sync

pytestmark = pytest.mark.django_db


def _agents(**overrides):
    base = {
        "intake": {"display": "Intake", "is_active": True},
        "triage": {"display": "Triage", "is_active": True},
    }
    base.update(overrides)
    return base


def _graph(*roles):
    return {"nodes": [{"id": r, "kind": "agent", "role": r} for r in roles]
                     + [{"id": "bye", "kind": "end"}],
            "edges": []}


def test_an_agent_with_no_step_is_reported_missing():
    sync = _flow_agent_sync(_graph("intake"), _agents())
    assert [m["role"] for m in sync["missing"]] == ["triage"]
    assert sync["missing"][0]["display"] == "Triage"
    assert sync["orphans"] == [] and sync["inactive"] == []


def test_a_step_naming_a_deleted_agent_is_reported_orphaned():
    sync = _flow_agent_sync(_graph("intake", "triage", "ghost"), _agents())
    assert sync["orphans"] == ["ghost"]
    assert sync["missing"] == []


def test_a_switched_off_agent_is_called_out():
    agents = _agents(triage={"display": "Triage", "is_active": False})
    sync = _flow_agent_sync(_graph("intake", "triage"), agents)
    assert sync["inactive"] == ["triage"]
    assert sync["missing"] == [] and sync["orphans"] == []


def test_a_matching_canvas_reports_nothing():
    sync = _flow_agent_sync(_graph("intake", "triage"), _agents())
    assert sync == {"missing": [], "orphans": [], "inactive": []}


def test_non_agent_steps_are_ignored():
    """An 'ask' or 'end' step has no role and must never count as an orphan."""
    graph = {"nodes": [{"id": "a", "kind": "ask", "title": "Postcode"},
                       {"id": "b", "kind": "end", "config": {"outcome": "escalate"}},
                       {"id": "intake", "kind": "agent", "role": "intake"},
                       {"id": "triage", "kind": "agent", "role": "triage"}],
             "edges": []}
    assert _flow_agent_sync(graph, _agents()) == {"missing": [], "orphans": [], "inactive": []}


def test_an_empty_graph_reports_every_agent_missing():
    assert len(_flow_agent_sync({}, _agents())["missing"]) == 2
    assert len(_flow_agent_sync({"nodes": []}, _agents())["missing"]) == 2


# ── through the real page ────────────────────────────────────────────────────

@pytest.fixture
def staff_client(client):
    user = get_user_model().objects.create_user(
        username="flowadmin", password="x", is_staff=True, is_superuser=True)
    client.force_login(user)
    return client


def test_the_page_ships_the_reconciliation_to_the_canvas(staff_client):
    call_command("seed_kb")
    html = staff_client.get(reverse("dash-flow")).content.decode()
    assert 'id="flow-sync"' in html, "the canvas needs the sync data island"
    assert 'data-testid="flow-sync-warning"' in html


def _sync_of(html: str) -> dict:
    m = re.search(r'<script id="flow-sync" type="application/json">(.*?)</script>', html, re.S)
    assert m, "flow-sync island missing from the page"
    return json.loads(m.group(1))


def _a_role_on_the_canvas() -> str:
    from dashboard.views import _get_flow
    roles = [n.get("role") for n in (_get_flow().graph or {}).get("nodes", [])
             if n.get("kind") == "agent" and n.get("role")]
    assert roles, "the seeded canvas should have agent steps"
    return roles[0]


def test_switching_an_agent_off_is_visible_on_the_canvas(staff_client):
    call_command("seed_kb")
    from kb.models import AgentPrompt

    role = _a_role_on_the_canvas()
    assert role not in _sync_of(staff_client.get(reverse("dash-flow")).content.decode())["inactive"]

    AgentPrompt.objects.filter(role=role).update(is_active=False)
    after = _sync_of(staff_client.get(reverse("dash-flow")).content.decode())
    assert role in after["inactive"], f"{role} was switched off but the builder stayed quiet: {after}"


def test_deleting_an_agent_leaves_a_flagged_orphan_step(staff_client):
    """The step survives (we never rewrite the owner's layout) but it must be flagged."""
    call_command("seed_kb")
    from kb.models import AgentPrompt

    role = _a_role_on_the_canvas()
    AgentPrompt.objects.filter(role=role).delete()
    after = _sync_of(staff_client.get(reverse("dash-flow")).content.decode())
    assert role in after["orphans"], f"{role} no longer exists but the step was not flagged: {after}"


def test_an_agent_with_no_step_is_offered_for_adding(staff_client):
    """Delete the STEP rather than the agent: the agent is now invisible on the canvas."""
    call_command("seed_kb")
    from dashboard.views import _get_flow

    cfg = _get_flow()
    role = _a_role_on_the_canvas()
    cfg.graph = {"nodes": [n for n in cfg.graph["nodes"]
                           if not (n.get("kind") == "agent" and n.get("role") == role)],
                 "edges": []}
    cfg.save(update_fields=["graph", "updated_at"])

    after = _sync_of(staff_client.get(reverse("dash-flow")).content.decode())
    assert role in [m["role"] for m in after["missing"]], (
        f"{role} has no step on the canvas but was not offered: {after}")
