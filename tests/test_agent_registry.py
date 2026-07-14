"""Agent flow registry + redesigned agents page (V2 S9)."""
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from core.agent_registry import LAYERS, ROLE_INFO, layers_ctx, ordered_roles
from core.enums import AGENT_ROLE_CHOICES
from kb.models import AgentPrompt, Category, Tool

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops2", password="x", is_staff=True)
    client.force_login(user)
    return user


# ── Registry completeness / ordering ───────────────────────────────────────

def test_every_agent_role_appears_exactly_once():
    all_roles = [r for r, _ in AGENT_ROLE_CHOICES]
    roles_seen = ordered_roles()
    assert sorted(roles_seen) == sorted(all_roles)
    assert len(roles_seen) == len(set(roles_seen))


def test_role_info_matches_layers():
    assert set(ROLE_INFO) == set(ordered_roles())
    for layer in LAYERS:
        for role in layer.roles:
            assert ROLE_INFO[role].layer == layer.key


def test_general_layer_has_multiple_roles():
    general = next(l for l in LAYERS if l.key == "general")
    assert len(general.roles) > 1
    assert "heat_pump_specialist" in general.roles
    assert "water_pump_specialist" in general.roles
    assert "water_filtration_specialist" in general.roles


def test_single_agent_layers_have_exactly_one_role():
    for layer in LAYERS:
        if layer.key != "general" and layer.key != "fallback":
            assert len(layer.roles) == 1


# ── Page rendering ──────────────────────────────────────────────────────────

def test_agents_page_renders_all_roles(staff, client):
    for role, label in AGENT_ROLE_CHOICES:
        AgentPrompt.objects.get_or_create(role=role, defaults={"body": "x", "model_id": "gemini-2.0"})
    resp = client.get(reverse("dash-agents"))
    assert resp.status_code == 200


def test_agents_page_has_tab_for_each_layer(staff, client):
    resp = client.get(reverse("dash-agents"))
    html = resp.content.decode()
    for layer in layers_ctx():
        assert f'data-testid="agent-tab-{layer["key"]}"' in html


def test_general_tab_has_dropdown_markup(staff, client):
    html = client.get(reverse("dash-agents")).content.decode()
    assert 'data-testid="agent-tab-dropdown-general"' in html
    assert "heat_pump_specialist" in html or "Heat-pump" in html


def test_agent_detail_renders_for_every_role(staff, client):
    for role, label in AGENT_ROLE_CHOICES:
        AgentPrompt.objects.get_or_create(role=role, defaults={"body": "x", "model_id": "gemini-2.0"})
        resp = client.get(reverse("dash-agent-detail", args=[role]))
        assert resp.status_code == 200, role


# ── FAQ section scoping ─────────────────────────────────────────────────────

def test_faq_section_shows_family_link_for_general_roles(staff, client):
    Category.objects.get_or_create(slug="heat_pump", defaults={"name": "Heat pump", "group": "heat"})
    AgentPrompt.objects.get_or_create(
        role="heat_pump_specialist", defaults={"body": "x", "model_id": "gemini-2.0"})
    html = client.get(reverse("dash-agent-detail", args=["heat_pump_specialist"])).content.decode()
    assert reverse("dash-knowledge", args=["heat-pump"]) in html


def test_faq_section_shows_by_design_none_for_intake(staff, client):
    AgentPrompt.objects.get_or_create(role="intake", defaults={"body": "x", "model_id": "gemini-2.0"})
    resp = client.get(reverse("dash-agent-detail", args=["intake"]))
    html = resp.content.decode()
    assert 'data-testid="faq-none"' in html


# ── Common issues + tools round-trip via agent_save ────────────────────────

def test_agent_save_round_trips_common_issues(staff, client):
    p = AgentPrompt.objects.create(role="intake", body="x", model_id="gemini-2.0")
    resp = client.post(reverse("dash-agent-save", args=[p.pk]), {
        "model_id": "gemini-2.0", "body": "hi", "language_directive": "",
        "common_issues": "Customers often confuse E5 with E9.",
        "is_active": "on",
    })
    assert resp.status_code == 200
    p.refresh_from_db()
    assert p.common_issues == "Customers often confuse E5 with E9."


def test_agent_save_round_trips_tool_toggles(staff, client):
    p = AgentPrompt.objects.create(role="intake", body="x", model_id="gemini-2.0")
    t1 = Tool.objects.create(slug="t1", name="Tool one")
    t2 = Tool.objects.create(slug="t2", name="Tool two")
    resp = client.post(reverse("dash-agent-save", args=[p.pk]), {
        "model_id": "gemini-2.0", "body": "hi", "language_directive": "",
        "is_active": "on", "tools_submitted": "1", "tools": [str(t1.pk)],
    })
    assert resp.status_code == 200
    p.refresh_from_db()
    assert list(p.tools.values_list("pk", flat=True)) == [t1.pk]

    # Unchecking (submitting with tools_submitted but no tools) clears them.
    client.post(reverse("dash-agent-save", args=[p.pk]), {
        "model_id": "gemini-2.0", "body": "hi", "language_directive": "",
        "is_active": "on", "tools_submitted": "1",
    })
    p.refresh_from_db()
    assert p.tools.count() == 0


def test_agent_save_without_tools_submitted_leaves_tools_untouched(staff, client):
    p = AgentPrompt.objects.create(role="intake", body="x", model_id="gemini-2.0")
    t1 = Tool.objects.create(slug="t1", name="Tool one")
    p.tools.set([t1])
    client.post(reverse("dash-agent-save", args=[p.pk]), {
        "model_id": "gemini-2.0", "body": "hi", "language_directive": "", "is_active": "on",
    })
    p.refresh_from_db()
    assert list(p.tools.values_list("pk", flat=True)) == [t1.pk]


# ── Tool registry / enabled_tools_for_role ─────────────────────────────────

def test_enabled_tools_for_role():
    from kb.tooling import enabled_tools_for_role
    p = AgentPrompt.objects.create(role="specialist", body="x", model_id="gemini-2.0")
    active = Tool.objects.create(slug="active-tool", name="Active", is_active=True)
    inactive = Tool.objects.create(slug="inactive-tool", name="Inactive", is_active=False)
    p.tools.set([active, inactive])
    assert enabled_tools_for_role("specialist") == [active]


def test_enabled_tools_for_role_no_prompt():
    from kb.tooling import enabled_tools_for_role
    assert enabled_tools_for_role("nonexistent") == []


def test_seeded_tools_exist():
    slugs = set(Tool.objects.values_list("slug", flat=True))
    for expected in ("identify_machine", "suggest_models", "check_service_area",
                     "form_chip", "request_photo", "consult_brand"):
        assert expected in slugs, expected
    consult = Tool.objects.get(slug="consult_brand")
    # Live since migration 0018 — the handler (chat.consult.consult_brand) now exists
    # and the orchestrator wires it for general-mode specialists.
    assert consult.is_active is True
    assert consult.handler_ref == "chat.consult.consult_brand"
