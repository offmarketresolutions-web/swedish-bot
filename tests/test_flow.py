"""Flow builder (Vapi-style editable canvas): page renders + seeds, and the JSON
save endpoint validates fail-closed (no weakening of the code-level guardrails)."""
import json

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


def _post(client, graph):
    return client.post("/dashboard/flow/save", data=json.dumps(graph), content_type="application/json")


# ── auth + page ───────────────────────────────────────────────────────
def test_flow_requires_auth(client, seeded):
    assert client.get("/dashboard/flow/").status_code == 302


def test_flow_page_renders_and_seeds(staff, client, seeded):
    from kb.models import FlowConfig
    r = client.get("/dashboard/flow/")
    assert r.status_code == 200
    assert b'data-testid="flow-builder"' in r.content
    assert b'data-testid="flow-canvas"' in r.content
    # seeded the default flow on first visit
    cfg = FlowConfig.objects.first()
    assert cfg is not None
    roles = {n.get("role") for n in cfg.graph["nodes"] if n["kind"] == "agent"}
    assert {"intake", "router", "specialist"} <= roles
    # the "fields collected on a transition" concept is seeded on an edge
    assert any(e.get("collect") for e in cfg.graph["edges"])


# ── save round-trip ───────────────────────────────────────────────────
def test_flow_save_roundtrip(staff, client, seeded):
    from kb.models import FlowConfig
    graph = {
        "nodes": [
            {"id": "a", "kind": "agent", "role": "intake", "title": "A", "x": 10, "y": 20, "config": {}},
            {"id": "z", "kind": "end", "title": "Done", "x": 300, "y": 40, "config": {"outcome": "solve"}},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "z", "label": "go",
                   "collect": [{"name": "phone", "label": "Phone", "required": True}]}],
    }
    r = _post(client, graph)
    assert r.status_code == 200 and r.json()["ok"] is True
    saved = FlowConfig.objects.first().graph
    assert [n["id"] for n in saved["nodes"]] == ["a", "z"]
    assert saved["edges"][0]["collect"][0]["name"] == "phone"
    assert saved["edges"][0]["collect"][0]["required"] is True


def test_flow_save_whitelists_unknown_keys(staff, client, seeded):
    from kb.models import FlowConfig
    graph = {"nodes": [{"id": "a", "kind": "say", "title": "Hi", "x": 1, "y": 2,
                        "config": {"message": "hello"}, "evil": "DROP TABLE"}], "edges": []}
    assert _post(client, graph).status_code == 200
    node = FlowConfig.objects.first().graph["nodes"][0]
    assert "evil" not in node and node["config"]["message"] == "hello"


# ── fail-closed validation ────────────────────────────────────────────
def test_flow_save_rejects_bad_kind(staff, client, seeded):
    r = _post(client, {"nodes": [{"id": "a", "kind": "hacker", "title": "x", "x": 0, "y": 0}], "edges": []})
    assert r.status_code == 400


def test_flow_save_rejects_unknown_agent_role(staff, client, seeded):
    r = _post(client, {"nodes": [{"id": "a", "kind": "agent", "role": "wizard", "title": "x", "x": 0, "y": 0}], "edges": []})
    assert r.status_code == 400


def test_flow_save_rejects_dangling_edge(staff, client, seeded):
    graph = {"nodes": [{"id": "a", "kind": "end", "title": "x", "x": 0, "y": 0}],
             "edges": [{"id": "e", "source": "a", "target": "ghost", "label": ""}]}
    assert _post(client, graph).status_code == 400


def test_flow_save_rejects_oversized(staff, client, seeded):
    nodes = [{"id": f"n{i}", "kind": "say", "title": "x", "x": 0, "y": 0} for i in range(81)]
    assert _post(client, {"nodes": nodes, "edges": []}).status_code == 400


def test_flow_save_rejects_bad_json(staff, client, seeded):
    r = client.post("/dashboard/flow/save", data="not json", content_type="application/json")
    assert r.status_code == 400


def test_flow_save_requires_auth(client, seeded):
    # anonymous POST must not persist anything
    assert _post(client, {"nodes": [], "edges": []}).status_code in (302, 403)


def test_flow_page_escapes_script_in_titles(staff, client, seeded):
    # a staff-saved title containing </script> must not break out of the data block
    graph = {"nodes": [{"id": "a", "kind": "say", "title": "</script><b>x</b>", "x": 0, "y": 0, "config": {}}], "edges": []}
    assert _post(client, graph).status_code == 200
    html = client.get("/dashboard/flow/").content.decode()
    assert "</script><b>x</b>" not in html       # never present unescaped
    assert "\\u003C" in html                       # json_script escaped the "<"
