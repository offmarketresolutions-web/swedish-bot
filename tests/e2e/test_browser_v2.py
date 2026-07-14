"""Real-browser E2E suite v2 for the Nordland VVS support-bot platform.

Extends the v1 suite (tests/e2e/test_browser.py) with four scenarios that
exercise deeper conversation + dashboard surfaces:

  (a) early postnummer ask on a rich opener
  (b) model disambiguation chips (no premature machine binding)
  (c) form-button chip -> prefilled /demo/form
  (d) settings tabs (Service area / Website & forms) + FAQ approval

Every test is marked `e2e` + `live` (kept out of the default `-m 'not live'`
run). Run with:

    .venv\\Scripts\\python.exe -m pytest -m e2e -s -v tests/e2e/test_browser_v2.py

Screenshots land in docs/evals/2026-07-14-e2e-v2/. Chat scenarios (a,b,c) hit
real Gemini; (d) is mostly static Django.
"""
from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import (
    BASE_URL,
    E2E_ADMIN_PASS,
    E2E_ADMIN_USER,
    PROJECT_ROOT,
)
# Reuse the v1 widget helpers verbatim (import, don't fork).
from tests.e2e.test_browser import (
    _bot_count,
    _last_bot_text,
    _wait_bot_settled,
    chips,
    click_chip,
    is_swedish,
    open_widget,
    send_text,
)

pytestmark = [pytest.mark.e2e, pytest.mark.live]

TURN_TIMEOUT = 40_000  # ms — one live-Gemini turn
SHOT_DIR_V2 = PROJECT_ROOT / "docs" / "evals" / "2026-07-14-e2e-v2"


def shot_v2(page: Page, name: str):
    """Screenshot into the v2 eval dir (v1's conftest.shot points elsewhere)."""
    SHOT_DIR_V2.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR_V2 / name
    page.screenshot(path=str(path), full_page=False)
    return path


def _looks_like_postcode_ask(text: str) -> bool:
    low = text.lower()
    return "postnummer" in low or "postnr" in low


def _is_question(text: str) -> bool:
    return "?" in (text or "")


# ── (a) postcode asked early on a rich opener ──────────────────────────

def test_v2_a_postcode_early(page: Page):
    """A rich opener (brand+model+symptom) should let the bot reach the
    postnummer ask within its first two questions rather than re-interrogating
    the basics."""
    page.goto(f"{BASE_URL}/demo/homepage")
    open_widget(page)

    opener = ("Min IVT Geo 412C värmepump ger inte tillräckligt varmt vatten "
              "och huset är kallt")
    reply = send_text(page, opener)

    questions_seen = 0
    postcode_within_two = _looks_like_postcode_ask(reply) and _is_question(reply)
    if _is_question(reply):
        questions_seen += 1
        if _looks_like_postcode_ask(reply):
            postcode_within_two = True

    generic_answers = ["Det började igår", "Nej ingen felkod", "Jag vet inte modellen exakt"]
    for ans in generic_answers:
        if questions_seen >= 2:
            break
        reply = send_text(page, ans)
        if _looks_like_postcode_ask(reply):
            postcode_within_two = True
            break
        if _is_question(reply):
            questions_seen += 1

    shot_v2(page, "a_postcode_early.png")
    assert postcode_within_two, (
        f"bot did not ask for postnummer within its first 2 questions; "
        f"last reply: {reply!r}")


# ── (b) model disambiguation — chips, no premature machine bind ─────────

def test_v2_b_model_disambiguation(page: Page):
    """Brand=IVT + ambiguous free-text model 'Geo' should surface a
    which-model disambiguation (candidate chips and/or a 'vilken modell' ask),
    NOT silently bind a single machine."""
    page.goto(f"{BASE_URL}/demo/homepage")
    open_widget(page)

    send_text(page, "Min värmepump krånglar")
    # Brand first (chip if offered, else free text).
    ivt_chip = page.locator('[data-testid="chip"][data-value="IVT"]')
    if ivt_chip.count():
        click_chip(page, value="IVT")
    else:
        send_text(page, "IVT")

    chips_before = chips(page).count()
    reply = send_text(page, "Geo")

    low = reply.lower()
    asks_model = ("modell" in low or "vilken" in low or "typskylten" in low
                  or "menar du" in low)
    chips_grew = chips(page).count() > chips_before

    shot_v2(page, "b_model_disambiguation.png")
    assert asks_model or chips_grew, (
        f"expected a model disambiguation (candidate chips or a which-model "
        f"ask); chips_before={chips_before} chips_now={chips(page).count()} "
        f"reply={reply!r}")


# ── (c) form-button chip -> prefilled /demo/form ───────────────────────

def _drive_answer(bot_low: str) -> tuple[str, str]:
    """Map a Swedish bot prompt to (kind, payload). kind in {chip, chip:<val>, text}.
    Copied from v1 test_d_escalation_creates_lead's driver."""
    if "ska jag skicka" in bot_low:                       # approval
        return "chip", "yes_send"
    if "innan jag skickar" in bot_low:                    # pre-escalate diag
        return "text", "Den låter skrapande och surrande, ingen felkod visas."
    if "vad heter du" in bot_low or "får jag ta några uppgifter" in bot_low:
        return "text", "Erik Testsson"
    if "telefonnummer" in bot_low:
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


def test_v2_c_form_button_prefill(page: Page, orm):
    """Drive a full escalation lead; assert the post-lead thanks emits a
    target=_blank form-chip whose href carries ?nl_case=<token>, then open
    /demo/form?nl_case=<token> and assert the prefill populated the fields."""
    from crm.models import FormButton

    # Ensure an active quote_request FormButton exists (the fallback the chip
    # resolves to regardless of the case category). Construction mirrors
    # tests/test_scenarios/test_q_form_chip.py + dashboard's 4-fixed-rows seed.
    with orm.unblock():
        FormButton.objects.update_or_create(
            category_slug="quote_request",
            defaults={"label": "Begär offert", "is_active": True,
                      "url": "https://www.nordlandvvs.se/offert"},
        )

    page.goto(f"{BASE_URL}/demo/homepage")
    open_widget(page)

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
    assert dispatched, f"never reached approval; last reply: {reply!r}"
    shot_v2(page, "c1_lead_done.png")

    # The thanks turn renders the form chip as a target=_blank anchor.
    link = page.locator('[data-testid="chip-link"][data-value="open_form"]')
    expect(link.first).to_be_visible(timeout=10_000)
    href = link.first.get_attribute("href")
    assert href and "nl_case=" in href, f"form-chip href missing nl_case token: {href!r}"
    token = href.split("nl_case=", 1)[1]
    shot_v2(page, "c2_form_chip.png")

    # Open the prefill form directly with the extracted token.
    page.goto(f"{BASE_URL}/demo/form?nl_case={token}")
    # The banner flips visible only after prefill actually filled >=1 field.
    expect(page.locator('[data-testid="prefill-banner"]')).to_be_visible(timeout=10_000)

    # Technical postal_code is always in the prefill payload (session field).
    expect(page.locator('[data-field="postal_code"]')).to_have_value("11152")
    # Contact name/phone appear only when the customer consented; assert when present.
    name_val = page.locator('[data-field="name"]').input_value()
    phone_val = page.locator('[data-field="phone"]').input_value()
    if name_val:
        assert name_val == "Erik Testsson", name_val
    if phone_val:
        # The product normalizes Swedish mobiles to E.164: 070-1234567 → +46701234567.
        assert phone_val.replace(" ", "") in ("+46701234567", "070-1234567", "0701234567"), phone_val
    shot_v2(page, "c3_form_prefilled.png")


# ── (d) dashboard settings tabs + FAQ approval ─────────────────────────

def _login(page: Page):
    """Copied from v1 test_browser._login. First navigation gets a generous timeout:
    when the live-eval driver saturates the shared dev DB/CPU, the initial /dashboard/
    load can exceed the 15s context default (observed transient in the first S7 run)."""
    page.goto(f"{BASE_URL}/dashboard/", timeout=60_000)  # -> redirect to /admin/login/
    page.locator("#id_username").fill(E2E_ADMIN_USER)
    page.locator("#id_password").fill(E2E_ADMIN_PASS)
    page.locator('input[type="submit"]').click()
    page.wait_for_url(f"{BASE_URL}/dashboard/**", timeout=15_000)


def test_v2_d_dashboard_tabs(page: Page, orm):
    _login(page)

    # Settings landing -> tabs bar present.
    resp = page.goto(f"{BASE_URL}/dashboard/settings/")
    assert resp is not None and resp.status == 200
    expect(page.locator('[data-testid="settings-tabs"]')).to_be_visible()
    shot_v2(page, "d1_settings.png")

    # Service area tab -> its postcode test box renders.
    page.get_by_role("link", name="Service area").click()
    page.wait_for_url(f"{BASE_URL}/dashboard/settings/service-area/", timeout=15_000)
    expect(page.locator('[data-testid="geo-test-box"]')).to_be_visible()
    expect(page.locator('[data-testid="geo-test-postcode"]')).to_be_visible()
    shot_v2(page, "d2_service_area.png")

    # Website & forms tab -> fill a URL field, save, assert it persisted.
    page.get_by_role("link", name="Website & forms").click()
    page.wait_for_url(f"{BASE_URL}/dashboard/settings/forms/", timeout=15_000)
    expect(page.locator('[data-testid="settings-form-buttons"]')).to_be_visible()
    url_input = page.locator('input[name="url_quote_request"]')
    new_url = "https://www.nordlandvvs.se/offert-e2e-v2"
    url_input.fill(new_url)
    # The Save label is localized (sv), so target the form's submit button by CSS.
    page.locator('[data-testid="settings-form-buttons"] form button.btn-primary').click()
    # Plain form POST -> 302 redirect back to dash-forms; value must persist.
    page.wait_for_url(f"{BASE_URL}/dashboard/settings/forms/", timeout=15_000)
    expect(page.locator('input[name="url_quote_request"]')).to_have_value(new_url)
    shot_v2(page, "d3_forms_saved.png")

    # FAQ approval page -> pending section renders with the real pending count.
    with orm.unblock():
        from kb.models import FAQEntry, SiteFAQ
        pending = (FAQEntry.objects.filter(is_approved=False).count()
                   + SiteFAQ.objects.filter(is_approved=False).count())

    resp = page.goto(f"{BASE_URL}/dashboard/faq/")
    assert resp is not None and resp.status == 200
    heading = page.locator('[data-testid="faq-pending-heading"]')
    expect(heading).to_be_visible()
    if pending:
        expect(heading).to_contain_text(str(pending))
        expect(page.locator('[data-testid="faq-pending-list"]')).to_be_visible()
    shot_v2(page, "d4_faq_pending.png")
