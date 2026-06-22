"""End-to-end browser tests (Playwright, headless Chromium) against the running
Docker stack at http://127.0.0.1:8080. Exercises the real request → SSE → render
cycle, HTMX inline-save, the Alpine tree, and the Tailwind-CLI brand styling, and
saves screenshots to tools/e2e_artifacts/.

Run:  uv run python tools/e2e_playwright.py
Needs: the stack up (`make up`) + staff user admin/nordland123. Hits real Gemini,
so assertions are on deterministic chips/state + UI, never on LLM prose.
"""
from __future__ import annotations

import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
ART = pathlib.Path(__file__).resolve().parent / "e2e_artifacts"
ART.mkdir(exist_ok=True)
BRAND_BLUE = "rgb(26, 116, 191)"  # #1a74bf

results: list[tuple[str, bool, str]] = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def shot(page, name):
    page.screenshot(path=str(ART / f"{name}.png"), full_page=False)


def widget_flow(page):
    page.goto(f"{BASE}/widget-demo", wait_until="load")
    shot(page, "01_widget_demo")
    # bubble carries the brand colour (proves the rebranded widget)
    bg = page.eval_on_selector('[data-testid=widget-bubble]', "el => getComputedStyle(el).backgroundColor")
    check("widget bubble is brand blue", bg == BRAND_BLUE, bg)
    page.click('[data-testid=widget-bubble]')
    page.wait_for_selector('[data-testid=widget-panel]', state="visible", timeout=30000)
    page.wait_for_selector('[data-testid=msg-bot]', timeout=30000)
    page.wait_for_selector('[data-testid=chip]', timeout=30000)
    shot(page, "02_widget_open")
    logo = page.get_attribute('[data-testid=widget-panel] img', "src") or ""
    check("widget header shows Nordland logo", "nordland-logo.png" in logo, logo)
    values = [c.get_attribute("data-value") for c in page.query_selector_all('[data-testid=chip]')]
    check("greeting offers category chips", "heat_pump" in values, str(values))
    # click a category chip → deterministic problem chips (full SSE round-trip)
    page.click('[data-testid=chip][data-value="heat_pump"]')
    page.wait_for_selector('[data-testid=chip][data-value="no_heat"]', timeout=45000)
    shot(page, "03_widget_after_category")
    values2 = [c.get_attribute("data-value") for c in page.query_selector_all('[data-testid=chip]')]
    check("category selection advances to problem chips", "no_heat" in values2, str(values2))
    # language selector → switches the whole conversation (UI + greeting + chips) to Swedish
    check("widget has a language selector", page.locator('[data-testid=widget-lang]').count() == 1)
    opts = page.eval_on_selector_all('[data-testid=widget-lang] option', "os => os.map(o => o.value)")
    check("selector offers sv + en", "sv" in opts and "en" in opts, str(opts))
    page.select_option('[data-testid=widget-lang]', 'sv')
    page.wait_for_function(
        "() => { const b=document.querySelectorAll('[data-testid=msg-bot]'); if(!b.length) return false;"
        " const last=b[b.length-1]; if(last.querySelector('.nl-typing')) return false;"
        " return /[\\u00e5\\u00e4\\u00f6]|hej|v\\u00e4rme/.test((last.innerText||'').toLowerCase()); }",
        timeout=60000)
    check("language selector switches the bot to Swedish", True)
    shot(page, "03b_widget_swedish")


def login(page):
    page.goto(f"{BASE}/admin/login/", wait_until="load")
    if page.locator("#id_username").count():           # normal login form
        page.fill("#id_username", "admin")
        page.fill("#id_password", "nordland123")
        page.click("input[type=submit]")
        page.wait_for_load_state("load")
    # else: DEMO_OPEN_ADMIN auto-logs-in — no form to fill


def dashboard_overview(page):
    page.goto(f"{BASE}/dashboard/", wait_until="load")
    shot(page, "04_dashboard_overview")
    check("dashboard overview renders", "Overview" in page.content())
    # familiar SaaS shell: a persistent left sidebar in brand-dark
    check("sidebar present", page.locator(".nl-sidebar").count() == 1)
    sb = page.eval_on_selector(".nl-sidebar", "el => getComputedStyle(el).backgroundColor")
    check("sidebar uses brand dark", sb == "rgb(15, 69, 112)", sb)  # #0f4570
    # data table with search on the sessions list
    page.goto(f"{BASE}/dashboard/sessions/", wait_until="load")
    shot(page, "04b_sessions_table")
    check("sessions table has search", page.locator('input[name=q]').count() >= 1)


def agent_config(page):
    page.goto(f"{BASE}/dashboard/agents/", wait_until="load")
    shot(page, "05_agent_config")
    card = page.locator('[data-testid=agent-card-specialist]')
    check("agent config shows specialist card", card.count() == 1)
    card.locator('input[name=temperature]').fill("0.55")
    card.locator('[data-testid=agent-save-btn]').click()
    # HTMX swaps the card in-place and the Saved badge appears
    page.wait_for_selector('[data-testid=agent-card-specialist] [data-testid=agent-saved]', timeout=15000)
    shot(page, "06_agent_saved")
    check("agent inline save (HTMX) shows Saved", True)
    # persisted?
    page.goto(f"{BASE}/dashboard/agents/", wait_until="load")
    val = page.locator('[data-testid=agent-card-specialist] input[name=temperature]').input_value()
    check("agent temperature persisted", val == "0.55", val)
    # clickable flow map → per-agent detail page
    check("agent flow map renders", page.locator('[data-testid=agent-map] svg').count() == 1)
    page.locator('[data-testid=agent-map] a[href$="/agents/specialist/"]').first.click()
    page.wait_for_url("**/agents/specialist/", timeout=15000)
    shot(page, "05b_agent_detail")
    check("map node opens the agent detail page",
          page.locator('[data-testid=agent-detail]').count() == 1
          and page.locator('[data-testid=agent-card-specialist]').count() == 1)
    # save from the detail page → goes live immediately (toast confirms)
    page.locator('[data-testid=agent-card-specialist] input[name=temperature]').fill("0.6")
    page.locator('[data-testid=agent-card-specialist] [data-testid=agent-save-btn]').click()
    page.wait_for_selector('[data-testid=agent-card-specialist] [data-testid=agent-saved]', timeout=15000)
    check("agent detail page saves live", True)


def kb_manager(page):
    # KB landing → Brand page → Machine page (real pages, everything clickable)
    page.goto(f"{BASE}/dashboard/kb/", wait_until="load")
    shot(page, "07_kb_landing")
    brand = page.locator('a[href*="/kb/vendor/"]:not([href*="/new"])').first
    check("KB landing lists brand links", brand.count() >= 1)
    brand.click()
    page.wait_for_url("**/kb/vendor/**")
    shot(page, "07b_brand_page")
    machine = page.locator('a[href*="/kb/machine/"]:not([href*="/panel"]):not([href*="/new"])').first
    check("brand page lists machine links", machine.count() >= 1)
    machine.click()
    page.wait_for_selector('[data-testid=machine-panel]', timeout=15000)
    shot(page, "08_machine_page")
    check("machine opens its own page", "/kb/machine/" in page.url and page.locator('[data-testid=machine-panel]').count() == 1)
    # add a note (HTMX), verify, then DELETE it so the test never pollutes the KB
    page.on("dialog", lambda d: d.accept())  # auto-accept the hx-confirm on delete
    note = "E2E temp note " + page.evaluate("() => String(performance.now()|0)")
    page.fill('[data-testid=note-input]', note)
    page.click('[data-testid=note-form] button')
    page.wait_for_function(
        "txt => document.querySelector('[data-testid=note-list]')?.innerText.includes(txt)",
        arg=note, timeout=15000)
    shot(page, "09_machine_note_added")
    check("HTMX note add reflects on machine page", note in page.locator('[data-testid=note-list]').inner_text())
    page.locator('[data-testid=note-item]', has_text=note).locator('button').click()
    page.wait_for_function(
        "txt => !document.querySelector('[data-testid=note-list]')?.innerText.includes(txt)",
        arg=note, timeout=15000)
    check("note delete removes it (no test pollution)",
          note not in page.locator('[data-testid=note-list]').inner_text())


def kb_create_and_faq(page):
    # Create a brand (CRUD) → should redirect to its new brand page
    page.goto(f"{BASE}/dashboard/kb/vendor/new/", wait_until="load")
    shot(page, "10_brand_create_form")
    name = "E2E Test Brand " + page.evaluate("() => String(performance.now()|0)")
    page.fill('input[name=name]', name)
    page.locator('form button, button[type=submit], .btn-primary').last.click()  # the form's submit
    page.wait_for_url("**/kb/vendor/**", timeout=45000)  # POST creates a vendor then redirects (allow cold-start)
    check("create brand redirects to brand page", "/kb/vendor/" in page.url and "/new" not in page.url)
    check("new brand name shown", name.split()[0] in page.content())
    # FAQ page (imported from nordlandvvs.se)
    page.goto(f"{BASE}/dashboard/faq/", wait_until="load")
    shot(page, "11_faq_page")
    check("FAQ page has a search box", page.locator('input[name=q]').count() >= 1)
    check("FAQ page shows imported questions", "?" in page.locator('main').inner_text() and len(page.locator('main').inner_text()) > 500)


def pdf_preview(page):
    # IVT brand → a machine with a manual → Preview → inline PDF in the iframe
    page.goto(f"{BASE}/dashboard/kb/", wait_until="load")
    page.locator('a[href*="/kb/vendor/"]', has_text="IVT").first.click()
    page.wait_for_url("**/kb/vendor/**")
    page.locator('a[href*="/kb/machine/"]:not([href*="/new"])').first.click()
    page.wait_for_selector('[data-testid=machine-panel]', timeout=15000)
    btn = page.locator('[data-testid=doc-preview-btn]').first
    check("machine has a previewable manual", btn.count() >= 1)
    if btn.count() == 0:
        return
    btn.click()
    iframe = page.locator('[data-testid=doc-preview]').first
    iframe.wait_for(state="visible", timeout=10000)
    src = iframe.get_attribute("src") or ""
    check("preview iframe targets the PDF route", "/kb/document/" in src)
    resp = page.request.get(BASE + src if src.startswith("/") else src)
    check("inline PDF serves 200 application/pdf",
          resp.status == 200 and "application/pdf" in (resp.headers.get("content-type") or ""))
    shot(page, "13_pdf_preview")


def analytics_page(page):
    page.goto(f"{BASE}/dashboard/analytics/", wait_until="load")
    shot(page, "12_analytics")
    check("analytics page renders", page.locator('[data-testid=analytics-page]').count() == 1)
    body = page.locator('main').inner_text()
    check("analytics shows KPIs", "Conversations" in body or "Resolution" in body)
    check("analytics shows success scoreboard", "target" in body.lower())
    # day-range switch works
    page.goto(f"{BASE}/dashboard/analytics/?days=7", wait_until="load")
    check("analytics day-range switch", page.locator('[data-testid=analytics-page]').count() == 1)


def flow_builder(page):
    # Vapi-style editable canvas: seeded, can add a step, configure it, save, persist
    page.goto(f"{BASE}/dashboard/flow/", wait_until="load")
    shot(page, "14_flow_builder")
    check("flow builder canvas renders",
          page.locator('[data-testid=flow-builder]').count() == 1
          and page.locator('[data-testid=flow-canvas] svg').count() >= 1)
    check("flow seeded with agent nodes", page.locator('[data-testid=node-specialist]').count() == 1)
    # add a "wait" step → a node appears and is selected for editing
    page.locator('[data-testid=add-wait]').click()
    page.wait_for_function("() => document.querySelectorAll('[data-testid^=\"node-wait_\"]').length >= 1", timeout=8000)
    check("can add a step (wait)", page.locator('[data-testid^="node-wait_"]').count() >= 1)
    page.fill('[data-testid=node-title]', "Hold for parts")
    # save → toast confirms + it persists across reload (real SQL write)
    page.locator('[data-testid=flow-save]').click()
    page.wait_for_selector('[data-testid=flow-toast]', timeout=10000)
    check("flow saves with confirmation", "saved" in page.locator('[data-testid=flow-toast]').inner_text().lower())
    shot(page, "14b_flow_saved")
    page.goto(f"{BASE}/dashboard/flow/", wait_until="load")
    check("added step persisted after reload", page.locator('[data-testid^="node-wait_"]').count() >= 1)
    # cleanup: remove the test step(s) and save, so the flow is left as we found it
    while page.locator('[data-testid^="node-wait_"]').count():
        page.locator('[data-testid^="node-wait_"]').first.click()
        page.locator('[data-testid=node-delete]').click()
    page.locator('[data-testid=flow-save]').click()
    page.wait_for_selector('[data-testid=flow-toast]', timeout=10000)
    check("flow delete-step works (no test pollution)", page.locator('[data-testid^="node-wait_"]').count() == 0)


def mobile_sidebar(page):
    # sidebar: collapsible drawer on mobile + its own scrollbar when it grows
    page.set_viewport_size({"width": 375, "height": 740})
    page.goto(f"{BASE}/dashboard/", wait_until="load")
    left = lambda: page.evaluate("() => document.querySelector('.nl-sidebar').getBoundingClientRect().left")
    check("mobile: sidebar collapsed by default", left() < -10)
    page.click('header button[aria-label]')          # hamburger
    page.wait_for_timeout(350)
    check("mobile: hamburger opens the sidebar", left() > -10)
    shot(page, "18_mobile_drawer")
    page.mouse.click(330, 400)                        # tap outside → overlay closes it
    page.wait_for_timeout(350)
    check("mobile: tapping outside collapses it", left() < -10)
    nav_overflow = page.evaluate("() => getComputedStyle(document.querySelector('.nl-sidebar nav')).overflowY")
    check("sidebar nav has its own scrollbar (overflow auto/scroll)", nav_overflow in ("auto", "scroll"))
    page.set_viewport_size({"width": 1280, "height": 900})  # restore


def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        for fn in (widget_flow, login, dashboard_overview, agent_config, kb_manager,
                   kb_create_and_faq, pdf_preview, analytics_page, flow_builder, mobile_sidebar):
            try:
                fn(page)
            except Exception as exc:  # noqa: BLE001
                check(f"{fn.__name__} (crashed)", False, repr(exc)[:200])
        browser.close()
    check("no uncaught JS page errors", not errors, "; ".join(errors)[:200])
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== {passed}/{len(results)} E2E checks passed — screenshots in {ART} ===")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
