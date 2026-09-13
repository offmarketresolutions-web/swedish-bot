"""The flow builder must keep describing the bot it configures — in a real browser.

The unit tests pin the reconciliation itself; this pins the part the owner touches: the
warning appears, one click puts every live agent on the canvas, and the page then says it
has unsaved work.

    .venv\\Scripts\\python.exe -m pytest -m e2e -s -v tests/e2e/test_flow_sync.py
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import BASE_URL, E2E_ADMIN_PASS, E2E_ADMIN_USER, shot

pytestmark = [pytest.mark.e2e, pytest.mark.live]


@pytest.fixture(autouse=True)
def a_canvas_missing_one_agent(orm):
    """Drop one agent's step from the saved graph so there is a real divergence to find."""
    with orm.unblock():
        from dashboard.views import _get_flow

        cfg = _get_flow()
        nodes = cfg.graph.get("nodes", [])
        victim = next(n for n in nodes if n.get("kind") == "agent" and n.get("role"))
        cfg.graph = {
            "nodes": [n for n in nodes if n is not victim],
            "edges": [e for e in cfg.graph.get("edges", [])
                      if victim["id"] not in (e.get("source"), e.get("target"))],
        }
        cfg.save(update_fields=["graph", "updated_at"])
        return victim["role"]


def _open_flow(page: Page) -> None:
    page.goto(f"{BASE_URL}/dashboard/", timeout=60_000)
    page.locator("#id_username").fill(E2E_ADMIN_USER)
    page.locator("#id_password").fill(E2E_ADMIN_PASS)
    page.locator('input[type="submit"]').click()
    page.wait_for_url(f"{BASE_URL}/dashboard/**", timeout=15_000)
    page.goto(f"{BASE_URL}/dashboard/flow/")
    page.wait_for_selector("[data-testid='flow-builder']", timeout=15_000)


def _agent_nodes(page: Page) -> int:
    return page.evaluate(
        "() => Alpine.$data(document.querySelector('[data-testid=\\'flow-builder\\']'))"
        ".nodes.filter(n => n.kind === 'agent').length")


def test_an_agent_missing_from_the_canvas_is_announced_and_fixable(page: Page):
    _open_flow(page)
    banner = page.locator("[data-testid='flow-sync-warning']")
    expect(banner).to_be_visible()
    expect(page.locator("[data-testid='flow-sync-missing']")).to_be_visible()

    before = _agent_nodes(page)
    shot(page, "flow_sync_warning.png")

    page.locator("[data-testid='flow-sync-add']").click()
    expect(banner).to_be_hidden()

    after = _agent_nodes(page)
    assert after > before, f"the missing step was not added ({before} -> {after})"

    # Every agent the bot actually has is now on the canvas.
    live = page.evaluate(
        "() => Object.keys(Alpine.$data(document.querySelector("
        "'[data-testid=\\'flow-builder\\']')).agents).length")
    assert after == live, f"{after} agent steps for {live} live agents"

    # Located by its binding, not its words: this dashboard renders in Swedish.
    expect(page.locator('[x-show="dirty"]').first).to_be_visible()


def test_the_added_steps_survive_a_save(page: Page):
    _open_flow(page)
    page.locator("[data-testid='flow-sync-add']").click()
    expected = _agent_nodes(page)

    page.locator("[data-testid='flow-save']").click()
    page.wait_for_timeout(1500)

    page.reload()
    page.wait_for_selector("[data-testid='flow-builder']", timeout=15_000)
    assert _agent_nodes(page) == expected, "the saved canvas lost the steps that were added"
    expect(page.locator("[data-testid='flow-sync-warning']")).to_be_hidden()
