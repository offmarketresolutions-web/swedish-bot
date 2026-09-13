"""Real customer journeys, driven through the widget the way a customer drives it.

Nothing here calls the orchestrator directly: every message is typed into the composer or
picked from a chip, exactly as on nordlandvvs.se. What is asserted afterwards is the half
the customer never sees — that the conversation was recorded, that a Customer row was
created with a usable profile, that the session carries a summary, and above all that a
person who comes back a second time lands on their EXISTING profile instead of a duplicate.

    .venv\\Scripts\\python.exe -m pytest -m e2e -s -v tests/e2e/test_customer_journey.py
"""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from .conftest import BASE_URL, shot

pytestmark = [pytest.mark.e2e, pytest.mark.live]

# A number that cannot collide with the dev DB's existing rows, so "did this link to the
# right person?" has an unambiguous answer. Digits only — a hex uuid slice put letters in
# the middle of the phone number, which the bot quite correctly refused to accept.
UNIQUE = f"{uuid.uuid4().int % 10**6:06d}"
ANNA = {
    "name": "Anna Lindqvist",
    "phone": f"070-555 {UNIQUE[:2]} {UNIQUE[2:4]}",
    "email": f"anna.{UNIQUE}@example.se",
}
ADDRESS = "Storgatan 5"

# The specialist turn does retrieval (embeddings + a context-cache round trip) before it
# answers. On the dev box that has been seen to take well over a minute, so a tight per-turn
# wait fails the test for slowness rather than for a defect.
TURN_TIMEOUT_MS = 180_000


def stored_phone(typed: str) -> str:
    """What the CRM actually holds for a number the customer typed.

    Contact numbers are normalised to E.164 on capture, so "070-555 00 67" is stored as
    "+46705550067" — looking the customer up by the typed form finds nothing and reads as
    "no row was created".
    """
    from chat import sanitize

    return sanitize.clean_phone(typed) or typed


# ── widget driving ───────────────────────────────────────────────────────────

def open_widget(page: Page, fresh: bool = True) -> None:
    """Open the widget as a first-time visitor.

    The widget persists the conversation in sessionStorage and restores it on reload, so a
    second journey in the same browser resumes the FINISHED one — no greeting, no category
    chips. That is correct for a customer who refreshes mid-chat; it is not a second visit,
    which is what these tests are staging.
    """
    page.goto(f"{BASE_URL}/demo/homepage", timeout=60_000)
    if fresh:
        page.evaluate("() => { try { sessionStorage.clear(); } catch (e) {} }")
        page.reload()
    page.wait_for_selector(".nl-launcher", timeout=20_000)
    if not page.locator(".nl-panel.nl-show").count():
        page.locator(".nl-launcher").click()
    page.wait_for_selector(".nl-panel.nl-show", timeout=10_000)
    page.wait_for_selector(".nl-row.nl-bot .nl-bubble", timeout=20_000)


def bot_turns(page: Page) -> list[str]:
    return [t.strip() for t in page.locator(".nl-row.nl-bot .nl-bubble").all_inner_texts()]


def last_bot(page: Page) -> str:
    turns = bot_turns(page)
    return turns[-1] if turns else ""


def _ready(page: Page) -> None:
    """The composer is disabled while a turn is in flight — wait it out rather than
    racing it, exactly as a customer waiting for the reply would."""
    page.wait_for_function(
        "() => { const t = document.querySelector('[data-testid=\"widget-input\"]');"
        " return t && !t.disabled; }", timeout=TURN_TIMEOUT_MS)


def _settle(page: Page, previous: int) -> str:
    """Wait for the turn to FINISH, then return the bot's reply.

    Counting bubbles is not enough: the widget inserts an empty "typing" bubble the moment
    you hit send, so a count-based wait returns that placeholder and the driver ends up
    answering "nej" to a question it never actually read. The composer being re-enabled is
    the widget's own "this turn is done" signal, so use that.
    """
    page.wait_for_function(
        "n => document.querySelectorAll('.nl-row.nl-bot .nl-bubble').length > n",
        arg=previous, timeout=TURN_TIMEOUT_MS)
    _ready(page)
    page.wait_for_timeout(250)
    text = last_bot(page)
    assert text.strip(), "the bot produced an empty bubble — nothing was said to the customer"
    return text


def say(page: Page, text: str) -> str:
    """Type into the composer and send — the customer's actual input path."""
    _ready(page)
    before = page.locator(".nl-row.nl-bot .nl-bubble").count()
    box = page.locator('[data-testid="widget-input"]').first
    box.click()
    box.fill(text)
    page.locator(".nl-send").click()
    return _settle(page, before)


def tap(page: Page, label_contains: str) -> str:
    """Click a suggestion chip by its visible label."""
    _ready(page)
    before = page.locator(".nl-row.nl-bot .nl-bubble").count()
    chip = page.locator(".nl-chip", has_text=re.compile(re.escape(label_contains), re.I)).first
    expect(chip).to_be_visible(timeout=10_000)
    chip.click()
    return _settle(page, before)


def chips(page: Page) -> list[str]:
    return [c.strip() for c in page.locator(".nl-chip").all_inner_texts()]


# ── the journeys ─────────────────────────────────────────────────────────────

# What a real customer would answer, keyed on what the bot actually asked. A fixed script
# desynchronises the moment the bot skips or reorders a question — which it legitimately
# does once it has mined a fact from an earlier message.
def _reply_for(question: str, who: dict, problem: str) -> str | None:
    q = question.lower()
    # FIRST, before anything else. The hand-off confirmation quotes the details back —
    # including the street address — so an "adress" rule further down matched it and
    # answered "Storgatan 5" to "shall I send this to Nordland VVS?". The bot read that as
    # a decline, no lead was created, and it looked like contact capture was broken.
    if "ska jag skicka" in q or "skicka detta" in q or "shall i send" in q:
        return "ja"
    if "vad heter du" in q or "your name" in q:
        return who["name"]
    if "telefonnummer" in q or "phone number" in q:
        return who["phone"]
    if "e-post" in q or "email" in q:
        return who["email"]
    if "postnummer" in q or "postal code" in q:
        return "85230"
    if "märke" in q or "brand" in q:
        return "IVT"
    if "modell" in q or "model" in q:
        return "AirX 500"
    if "larmkod" in q or "felkod" in q or "error" in q or "kod" in q:
        return "E4"
    if "när" in q or "började" in q or "hur länge" in q or "when" in q:
        return "Det började igår"
    if "adress" in q or "gata" in q or "address" in q:
        return ADDRESS
    if "beskriv" in q or "problem" in q or "describe" in q:
        return problem
    return None


def run_journey(page: Page, who: dict, problem: str, max_turns: int = 16) -> list[str]:
    """Drive a whole case through the widget. Returns every bot turn, for inspection.

    Runs PAST the contact questions on purpose: the CRM row is only written once the
    escalation completes, so stopping at the email left nothing in the database and made
    it look as though capture was broken.
    """
    open_widget(page)
    assert last_bot(page), "the bot must greet first"
    assert chips(page), "the opener should offer categories as chips"

    tap(page, "Värmepump")
    given, idle = set(), 0
    for _ in range(max_turns):
        q = last_bot(page)
        answer = _reply_for(q, who, problem)
        print(f"    Q: {q[:70]!r} -> A: {answer!r}", flush=True)
        if answer is None:
            # Nothing this customer can answer (a safety notice, a summary, a yes/no) —
            # a real person says no and lets it move on. Two of those in a row after the
            # details are in means the conversation has finished.
            idle += 1
            answer = "nej"
            if given >= {who["name"], who["phone"], who["email"]} and idle >= 2:
                break
        else:
            idle = 0
        if answer in (who["name"], who["phone"], who["email"]):
            given.add(answer)
        say(page, answer)
    return bot_turns(page)


def test_a_full_journey_is_recorded_with_a_usable_profile(page: Page, orm):
    turns = run_journey(page, ANNA, "Värmepumpen larmar och ger ingen värme")

    # Spec §11: it must ask for contact details before handing over.
    joined = " ".join(turns).lower()
    assert "vad heter du" in joined, f"the bot never asked for a name. Turns: {turns}"
    assert "telefonnummer" in joined, f"the bot never asked for a phone. Turns: {turns}"
    assert "e-post" in joined, f"the bot never asked for an email. Turns: {turns}"
    shot(page, "journey_contact_captured.png")

    with orm.unblock():
        from crm.models import Customer, Session

        cust = Customer.objects.filter(phone=stored_phone(ANNA["phone"])).first()
        assert cust is not None, (
            f"no Customer row for {ANNA['phone']} (stored as {stored_phone(ANNA['phone'])})")
        assert cust.name == ANNA["name"], f"name not captured: {cust.name!r}"
        assert cust.email == ANNA["email"], f"email not captured: {cust.email!r}"

        session = Session.objects.filter(customer=cust).order_by("-id").first()
        assert session is not None, "the case was not attached to the customer"
        assert session.conversation_id, "the transcript was not linked to the session"
        assert session.manufacturer or session.model, (
            "the machine facts never reached the session")
        assert session.postal_code == "85230", f"postcode: {session.postal_code!r}"
        assert cust.address == ADDRESS, f"address not captured: {cust.address!r}"

        msgs = session.conversation.messages.count()
        assert msgs >= 6, f"only {msgs} messages recorded for a full conversation"

        # The recap is what the technician actually reads. It must be written, substantial,
        # and in the language they read — the summariser used to flip to English on a
        # Swedish case because the shared directive told it to "reason internally in
        # English" and the recap is internal.
        recap = session.ai_summary or ""
        assert len(recap) > 60, f"the interaction summary is too thin: {recap!r}"
        assert re.search(r"[åäöÅÄÖ]|kunden|värmepump|felkod|postnummer", recap, re.I), (
            f"the technician's recap came back in English on a Swedish case: {recap!r}")


def test_the_same_person_coming_back_lands_on_one_profile(page: Page, orm):
    """The failure this guards: a second visit creating a second customer row, which
    splits their history and breaks the File Hub (it keys folders by customer pk)."""
    with orm.unblock():
        from crm.models import Customer

        before = Customer.objects.filter(phone=stored_phone(ANNA["phone"])).count()
        assert before == 1, f"expected exactly one Anna before the second visit, got {before}"

    run_journey(page, ANNA, "Den låter konstigt när den startar")

    with orm.unblock():
        from crm.models import Customer

        rows = Customer.objects.filter(phone=stored_phone(ANNA["phone"]))
        assert rows.count() == 1, (
            f"the same person produced {rows.count()} customer rows — history is split")
        cust = rows.first()
        assert cust.sessions.count() >= 2, (
            f"the second visit did not attach to the profile "
            f"({cust.sessions.count()} session(s))")


def test_a_different_person_on_the_same_number_does_not_hijack_the_profile(page: Page, orm):
    """A reassigned or mistyped number must not overwrite somebody else's record."""
    run_journey(page, {"name": "Bengt Karlsson",
                       "phone": ANNA["phone"],            # same number, different person
                       "email": f"bengt.{UNIQUE}@example.se"},
                "Ingen varmvatten alls")

    with orm.unblock():
        from crm.models import Customer

        anna = Customer.objects.filter(phone=stored_phone(ANNA["phone"]), name="Anna Lindqvist").first()
        assert anna is not None, "Anna's row disappeared"
        assert anna.email == ANNA["email"], (
            f"Anna's email was overwritten by the other caller: {anna.email!r}")


# ── the owner's side of the same story ───────────────────────────────────────

def _login(page: Page) -> None:
    from .conftest import E2E_ADMIN_PASS, E2E_ADMIN_USER

    page.goto(f"{BASE_URL}/dashboard/", timeout=60_000)
    page.locator("#id_username").fill(E2E_ADMIN_USER)
    page.locator("#id_password").fill(E2E_ADMIN_PASS)
    page.locator('input[type="submit"]').click()
    page.wait_for_url(f"{BASE_URL}/dashboard/**", timeout=15_000)


def test_the_owner_finds_one_profile_carrying_both_conversations(page: Page, orm):
    """Everything above is only useful if the owner can SEE it. Walk the dashboard the way
    they would: search the customer list, open the profile, read the history."""
    run_journey(page, ANNA, "Värmepumpen larmar och ger ingen värme")
    run_journey(page, ANNA, "Det droppar vatten under inomhusdelen")

    _login(page)
    # Search by THIS run's unique email, not the name: the dev DB accumulates an
    # "Anna Lindqvist" per test run, each with her own number, and they are different people
    # as far as the CRM is concerned.
    page.goto(f"{BASE_URL}/dashboard/customers/?q={ANNA['email']}")
    rows = page.locator("table tbody tr", has_text=ANNA["email"])
    assert rows.count() == 1, (
        f"the customer list shows {rows.count()} rows for one person — history is split")

    rows.first.locator("a").first.click()
    page.wait_for_selector('[data-testid="customer-conversations"]', timeout=15_000)

    convos = page.locator('[data-testid="customer-conversations"] a')
    assert convos.count() >= 2, (
        f"only {convos.count()} conversation(s) on the profile; both visits must be here")

    # The profile has to be worth opening: equipment and a written summary, not just a name.
    equipment = page.locator('[data-testid="customer-equipment"]').inner_text()
    assert "IVT" in equipment, f"equipment panel does not name the machine: {equipment!r}"

    summaries = page.locator('[data-testid="session-ai-summary"]')
    assert summaries.count() >= 1, "no interaction summary is shown on the profile"
    assert len(summaries.first.inner_text().strip()) > 40, "the summary is too thin to be useful"

    shot(page, "owner_customer_profile.png")


def test_the_owner_can_read_back_the_whole_transcript(page: Page, orm):
    """Recording a conversation is only worth it if it can be read back. Open the case from
    the profile and check the replica carries both sides of what was actually typed."""
    run_journey(page, ANNA, "Värmepumpen larmar och ger ingen värme")

    _login(page)
    page.goto(f"{BASE_URL}/dashboard/customers/?q={ANNA['email']}")
    page.locator("table tbody tr", has_text=ANNA["email"]).first.locator("a").first.click()
    page.wait_for_selector('[data-testid="customer-conversations"]', timeout=15_000)

    page.locator('[data-testid="open-replica"]').first.click()
    page.wait_for_selector('[data-testid="chat-replica"]', timeout=15_000)

    transcript = page.locator('[data-testid="chat-replica"]').inner_text()
    # The customer's own words and the bot's questions must both be there.
    assert ANNA["name"] in transcript, "the customer's name is missing from the transcript"
    assert "85230" in transcript, "the postcode the customer typed is missing"
    assert "AirX 500" in transcript, "the model the customer typed is missing"
    assert len(transcript) > 400, f"the transcript looks truncated ({len(transcript)} chars)"

    shot(page, "owner_transcript_replica.png")
