"""Real-browser E2E suite for the Nordland VVS support-bot platform.

Every test is marked `e2e` + `live` (the latter keeps it out of the default
`-m 'not live'` run). Run with:

    uv run pytest -m e2e tests/e2e -s -v

Screenshots + report land in docs/evals/2026-07-13-e2e/. The chat scenarios hit
real Gemini, so per-turn waits are generous (up to 40s).
"""
from __future__ import annotations

import io
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import (
    BASE_URL,
    E2E_ADMIN_PASS,
    E2E_ADMIN_USER,
    shot,
)

pytestmark = [pytest.mark.e2e, pytest.mark.live]

TURN_TIMEOUT = 40_000  # ms — one live-Gemini turn
SV = set("åäöÅÄÖ")


# ── widget helpers ─────────────────────────────────────────────────────

def _bot_count(page: Page) -> int:
    return page.locator('[data-testid="msg-bot"]').count()


def _last_bot_text(page: Page) -> str:
    loc = page.locator('[data-testid="msg-bot"]').last
    return (loc.inner_text() or "").strip()


def open_widget(page: Page):
    """Click the launcher, wait for the panel + a non-empty greeting bubble."""
    page.locator('[data-testid="widget-bubble"]').click()
    expect(page.locator('[data-testid="widget-panel"]')).to_be_visible()
    _wait_bot_settled(page, prev=0)


def _wait_bot_settled(page: Page, prev: int, timeout: int = TURN_TIMEOUT) -> str:
    """Wait until a NEW bot bubble exists AND its text is non-empty (the streamed
    reply has replaced the typing dots)."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if _bot_count(page) >= prev + 1 and _last_bot_text(page):
            return _last_bot_text(page)
        page.wait_for_timeout(300)
    raise AssertionError(
        f"no settled bot reply within {timeout}ms (bot bubbles={_bot_count(page)}, "
        f"last={_last_bot_text(page)!r})")


def send_text(page: Page, text: str) -> str:
    prev = _bot_count(page)
    inp = page.locator('[data-testid="widget-input"]')
    inp.click()
    inp.fill(text)
    page.locator('[data-testid="widget-send"]').click()
    return _wait_bot_settled(page, prev)


def chips(page: Page):
    return page.locator('[data-testid="chip"]')


def click_chip(page: Page, *, value: str | None = None, index: int = 0) -> str:
    prev = _bot_count(page)
    if value is not None:
        page.locator(f'[data-testid="chip"][data-value="{value}"]').click()
    else:
        chips(page).nth(index).click()
    return _wait_bot_settled(page, prev)


def is_swedish(text: str) -> bool:
    if any(ch in SV for ch in text):
        return True
    low = text.lower()
    return any(w in low for w in ("nordland", "värmepump", "tekniker", "hej", "larm",
                                  "kod", "vatten", "problem", "märke", "modell"))


# ── (a) homepage clone renders ─────────────────────────────────────────

def test_a_homepage_renders(page: Page):
    resp = page.goto(f"{BASE_URL}/demo/homepage")
    assert resp is not None and resp.status == 200
    expect(page.get_by_role("heading",
           name="Din auktoriserade värmepumpsinstallatör")).to_be_visible()
    for card in ("Värmepumpar", "Vattenpumpar", "Vattenbrunnar"):
        expect(page.get_by_role("heading", name=card, exact=True)).to_be_visible()
    expect(page.locator('[data-testid="widget-bubble"]')).to_be_visible()
    shot(page, "a_homepage.png")


# ── (b) full widget conversation (live) + chips ────────────────────────

def test_b_widget_conversation(page: Page):
    page.goto(f"{BASE_URL}/demo/homepage")
    open_widget(page)
    greeting = _last_bot_text(page)
    assert greeting and is_swedish(greeting)

    # Greeting renders category quick-replies.
    expect(chips(page).first).to_be_visible()
    assert chips(page).count() >= 2

    # Click a quick-reply (heat pump) -> next bot reply.
    reply_after_chip = click_chip(page, value="heat_pump")
    assert reply_after_chip and is_swedish(reply_after_chip)
    shot(page, "b1_after_chip.png")

    # Send a real free-text message -> live Gemini Swedish reply.
    reply = send_text(page, "Min IVT värmepump visar larm H01 5252")
    assert reply, "empty live reply"
    assert is_swedish(reply), f"reply not Swedish: {reply!r}"
    shot(page, "b2_live_reply.png")


# ── (c) photo upload (vision runs live) ────────────────────────────────

def _png_bytes() -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 140), (245, 245, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, 232, 132], outline=(20, 20, 20), width=2)
    d.text((20, 30), "IVT 490", fill=(0, 0, 0))
    d.text((20, 60), "S/N 12345", fill=(0, 0, 0))
    d.text((20, 90), "FEL H01", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_c_photo_upload(page: Page, tmp_path):
    page.goto(f"{BASE_URL}/demo/homepage")
    open_widget(page)

    png = tmp_path / "nameplate.png"
    png.write_bytes(_png_bytes())

    prev = _bot_count(page)
    page.locator('[data-testid="widget-panel"] input[type="file"]').set_input_files(str(png))
    # The file chip acknowledges the attachment before send.
    send_btn = page.locator('[data-testid="widget-send"]')
    expect(send_btn).to_be_enabled()
    send_btn.click()

    # User bubble shows the photo attachment...
    user_bubble = page.locator('[data-testid="msg-user"]').last
    expect(user_bubble).to_contain_text("nameplate.png")
    assert "📷" in user_bubble.inner_text()
    # ...and a live bot reply follows (vision + intake ran).
    reply = _wait_bot_settled(page, prev)
    assert reply and is_swedish(reply)
    shot(page, "c_photo_upload.png")


# ── (d) escalation -> lead row created in DB ───────────────────────────

def _drive_answer(bot_low: str) -> tuple[str, str]:
    """Map a Swedish bot prompt to (kind, payload). kind in {chip, text}."""
    if "ska jag skicka" in bot_low:                       # approval
        return "chip", "yes_send"
    if "innan jag skickar" in bot_low:                    # pre-escalate diag
        return "text", "Den låter skrapande och surrande, ingen felkod visas."
    if "vad heter du" in bot_low or "får jag ta några uppgifter" in bot_low:
        return "text", "Erik Testsson"
    if "telefonnummer" in bot_low:                        # phone / need_contact / reask
        return "text", "070-1234567"
    if "e-post" in bot_low:
        return "text", "skip"
    if "postnummer" in bot_low or "adress" in bot_low:
        return "text", "11152 Stockholm"
    if "vilket märke" in bot_low:
        return "text", "NIBE"
    if "vilken modell" in bot_low or "typskylten" in bot_low:
        return "text", "vet inte"
    if "vilken typ av utrustning" in bot_low:
        return "chip:heat_pump", "värmepump"
    if "beskriv kort" in bot_low:
        return "text", "Den låter konstigt och stör på nätterna."
    return "text", "vet inte"


def test_d_escalation_creates_lead(page: Page, orm):
    from crm.models import ServiceRequest

    with orm.unblock():
        before = ServiceRequest.objects.count()

    page.goto(f"{BASE_URL}/demo/homepage")
    open_widget(page)

    # Unsupported brand -> guaranteed escalation path.
    reply = send_text(page, "Jag har en NIBE pump som låter konstigt")

    dispatched = False
    for _ in range(16):
        low = reply.lower()
        kind, payload = _drive_answer(low)
        if kind == "chip" and payload == "yes_send":
            prev = _bot_count(page)
            page.locator('[data-testid="chip"][data-value="yes_send"]').click()
            reply = _wait_bot_settled(page, prev)
            dispatched = True
            break
        if kind.startswith("chip:"):
            val = kind.split(":", 1)[1]
            loc = page.locator(f'[data-testid="chip"][data-value="{val}"]')
            reply = click_chip(page, value=val) if loc.count() else send_text(page, payload)
        else:
            reply = send_text(page, payload)

    shot(page, "d_escalation.png")
    assert dispatched, f"never reached approval; last reply: {reply!r}"

    # Give the sink dispatch a moment, then assert the lead landed in the DB.
    deadline = time.time() + 10
    after = before
    while time.time() < deadline:
        with orm.unblock():
            after = ServiceRequest.objects.count()
        if after > before:
            break
        time.sleep(0.5)
    assert after == before + 1, f"ServiceRequest not created (before={before}, after={after})"

    with orm.unblock():
        sr = ServiceRequest.objects.order_by("-id").first()
        # v2 three-way router (S3): an unlisted-but-serviced brand goes to the GENERAL
        # specialist and escalates low_confidence/decision/budget, not v1's hard
        # "unsupported" refusal (reserved for truly out-of-scope categories). Same
        # adjudication as tools/eval/judge.py's soft-ok set.
        assert sr.escalation_reason in ("unsupported", "low_confidence", "decision", "budget"), \
            sr.escalation_reason
        cust = sr.session.customer
        assert cust is not None and cust.phone  # contact captured


# ── (e) dashboard: login + full sidebar walk + doc modal ───────────────

def _login(page: Page):
    page.goto(f"{BASE_URL}/dashboard/")            # -> redirect to /admin/login/
    page.locator("#id_username").fill(E2E_ADMIN_USER)
    page.locator("#id_password").fill(E2E_ADMIN_PASS)
    page.locator('input[type="submit"]').click()
    page.wait_for_url(f"{BASE_URL}/dashboard/**", timeout=15_000)


def test_e_dashboard(page: Page, e2e_seed):
    _login(page)
    expect(page.locator("aside, nav").first).to_be_visible()
    shot(page, "e01_overview.png")

    routes = [
        ("e02_analytics.png", "/dashboard/analytics/", None),
        ("e03_sessions.png", "/dashboard/sessions/", None),
        ("e04_customers.png", "/dashboard/customers/", None),
        ("e05_voice_phone.png", "/dashboard/voice/", None),
        ("e06_voice_credentials.png", "/dashboard/voice/credentials/",
         '[data-testid="settings-tabs"]'),
        ("e07_settings.png", "/dashboard/settings/", '[data-testid="settings-tabs"]'),
        ("e08_kb.png", "/dashboard/kb/", None),
        ("e09_faq.png", "/dashboard/faq/", None),
        ("e10_guardrails.png", "/dashboard/guardrails/", None),
        ("e11_flow.png", "/dashboard/flow/", None),
    ]
    for fname, path, sel in routes:
        resp = page.goto(f"{BASE_URL}{path}")
        assert resp is not None and resp.status == 200, f"{path} -> {resp.status if resp else None}"
        if sel:
            expect(page.locator(sel).first).to_be_visible()
        shot(page, fname)

    # Homepage-demo link (opens in a new tab from the sidebar; verify it loads directly).
    resp = page.goto(f"{BASE_URL}/demo/homepage")
    assert resp.status == 200

    # Customer detail + machine-documentation modal (seeded customer/session).
    cust_id = e2e_seed["customer_id"]
    resp = page.goto(f"{BASE_URL}/dashboard/customers/{cust_id}/")
    assert resp.status == 200
    expect(page.locator('[data-testid="customer-manifest"]')).to_be_visible()
    shot(page, "e12_customer_detail.png")

    page.locator('[data-testid="tab-docs"]').click()
    doc_link = page.locator('[data-testid="machine-doc-link"]').first
    expect(doc_link).to_be_visible()
    doc_link.click()
    # The doc modal's content container (#mdoc-<machine_id>) is unique to this modal
    # (the page also has hidden per-session chat dialogs), and htmx swaps the PDF into it.
    mdoc = page.locator(f'#mdoc-{e2e_seed["machine_id"]}')
    expect(mdoc).to_be_visible()
    expect(mdoc.locator("iframe")).to_be_visible(timeout=10_000)  # PDF viewer loaded
    shot(page, "e13_doc_modal.png")


# ── (f) mobile viewport sanity ─────────────────────────────────────────

def test_f_mobile(browser):
    ctx = browser.new_context(locale="sv-SE", viewport={"width": 375, "height": 812},
                              is_mobile=True, has_touch=True)
    page = ctx.new_page()
    try:
        resp = page.goto(f"{BASE_URL}/demo/homepage")
        assert resp.status == 200
        expect(page.get_by_role("heading",
               name="Din auktoriserade värmepumpsinstallatör")).to_be_visible()
        shot(page, "f1_mobile_home.png")

        launcher = page.locator('[data-testid="widget-bubble"]')
        expect(launcher).to_be_visible()
        # Fire the launcher's own click handler. Under mobile emulation Playwright's
        # hit-test intermittently reports the (aria-hidden, z-index-0) hero SVG as
        # intercepting the tap on the fixed launcher; dispatch_event exercises the same
        # openPanel() handler without the flaky coordinate hit-test.
        launcher.dispatch_event("click")
        expect(page.locator('[data-testid="widget-panel"]')).to_be_visible()
        shot(page, "f2_mobile_widget_open.png")

        # Close: on mobile the panel is full-screen and covers the launcher, so use the
        # in-panel Escape handler rather than toggling the (now-obscured) launcher.
        page.keyboard.press("Escape")
        expect(page.locator('[data-testid="widget-panel"]')).to_be_hidden()
        shot(page, "f3_mobile_widget_closed.png")
    finally:
        ctx.close()
