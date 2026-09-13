"""HTTP layer: session + SSE message endpoints (plan §10)."""
import json
import re

import pytest
from django.core.management import call_command

from chat.models import Conversation

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def _sse_events(response) -> list[dict]:
    raw = b"".join(response.streaming_content).decode()
    out = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def _say(client, public_id, text):
    resp = client.post(f"/api/chat/{public_id}/message",
                       data=json.dumps({"message": text}), content_type="application/json")
    events = _sse_events(resp)
    return next(e for e in events if e["type"] == "message")


def test_create_session_returns_public_id_and_chips(client, seeded, mock_gemini):
    resp = client.post("/api/chat/session", data="{}", content_type="application/json")
    assert resp.status_code == 200
    j = resp.json()
    assert j["public_id"]
    assert {c["value"] for c in j["chips"]} >= {"heat_pump", "water_pump_well"}


def test_full_solve_over_http(client, seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Check the extract-air filter is clean and note the alarm code.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
    }
    pid = client.post("/api/chat/session", data="{}", content_type="application/json").json()["public_id"]
    _say(client, pid, "heat_pump")
    _say(client, pid, "no")          # postcode asked early (declined)
    _say(client, pid, "no_heat")
    _say(client, pid, "IVT")
    final = _say(client, pid, "IVT 490")
    assert final["decision"] == "solve"
    assert "filter" in final["message"]


def test_unknown_session_404(client, mock_gemini):
    resp = client.post("/api/chat/00000000-0000-0000-0000-000000000000/message",
                       data="{}", content_type="application/json")
    assert resp.status_code == 404


def test_session_without_a_language_defaults_to_swedish(client, seeded, mock_gemini):
    """Nordland VVS serves Swedish customers. The documented embed pins data-lang="sv",
    but an embed pasted without it (or any direct API caller) used to get an English
    bot — a silent, customer-facing failure nobody would notice in the logs. The
    fallback must be the business's own language, not English."""
    j = client.post("/api/chat/session", data="{}", content_type="application/json").json()
    assert j["message"].startswith("Hej!"), j["message"]
    assert Conversation.objects.get(public_id=j["public_id"]).language == "sv"


def test_session_still_honours_an_explicit_language(client, seeded, mock_gemini):
    j = client.post("/api/chat/session", data=json.dumps({"language": "en"}),
                    content_type="application/json").json()
    assert j["message"].startswith("Hi!"), j["message"]
    assert Conversation.objects.get(public_id=j["public_id"]).language == "en"


def test_internal_kb_citation_tags_never_reach_the_customer(client, seeded, mock_gemini):
    """The seeded specialist prompt tells the model to put the [K<pk>] traceability tag in
    answer_to_customer "so staff can trace the source" — but that field IS the customer's
    message. In the 100-conversation live eval, 35 conversations showed a real customer a
    raw "[K72]". The prompt is a DB row and seed_kb is no-clobber, so fixing the wording
    cannot reach an already-seeded install: the strip has to be code-owned."""
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Check the extract-air filter is clean. [K72] Then note the code. [K1]",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
    }
    pid = client.post("/api/chat/session", data="{}", content_type="application/json").json()["public_id"]
    _say(client, pid, "heat_pump")
    _say(client, pid, "no")
    _say(client, pid, "no_heat")
    _say(client, pid, "IVT")
    final = _say(client, pid, "IVT 490")

    # Guard against a vacuous pass: if the specialist answer never surfaced, the assertion
    # below would hold for the wrong reason.
    assert final["decision"] == "solve" and "filter" in final["message"], final["message"]
    assert not re.search(r"\[K\d+\]", final["message"]),         f"internal citation tag shown to the customer: {final['message']}"


def test_strip_kb_tags_removes_tags_without_damaging_the_answer():
    from chat.orchestrator import _strip_kb_tags
    assert _strip_kb_tags("Rengör filtret. [K72] Kontrollera trycket. [K1]") ==         "Rengör filtret. Kontrollera trycket."
    # The model emits several ids in one tag — "[K51, K53]" reached customers on 2 of the
    # 37 leaking turns in the live run because the first pattern demanded whitespace after
    # the number. Real leaked text, replayed.
    assert _strip_kb_tags("...behöver vi boka in en servicetekniker. [K51, K53]") ==         "...behöver vi boka in en servicetekniker."
    assert _strip_kb_tags("Se manualen. [W1 nibe.eu]") == "Se manualen."
    assert _strip_kb_tags("Enligt [K2,K7] gäller detta.") == "Enligt gäller detta."
    assert _strip_kb_tags("Inga taggar här.") == "Inga taggar här."
    assert _strip_kb_tags("") == ""
    assert _strip_kb_tags(None) == ""
    # a bracketed non-citation must survive
    assert _strip_kb_tags("Se [Kapitel 4] i manualen.") == "Se [Kapitel 4] i manualen."


def _solve_to_confirm(client, mock_gemini):
    """Drive a conversation to a solved fix, sitting on "Did that fix it?"."""
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Check the extract-air filter is clean.",
        "confidence": 0.9, "decision": "solve", "in_docs": True, "report": {},
    }
    pid = client.post("/api/chat/session", data=json.dumps({"language": "en"}),
                      content_type="application/json").json()["public_id"]
    for text in ("heat_pump", "no", "no_heat", "IVT", "IVT 490"):
        last = _say(client, pid, text)
    assert last["decision"] == "solve", last
    return pid


def test_after_a_fix_the_bot_offers_to_save_details_it_never_demands_them_first(client, seeded, mock_gemini):
    """The solution is given FIRST and never held back pending contact details — the
    offer comes after the customer confirms it worked, so it reads as service rather than
    a toll gate on help."""
    pid = _solve_to_confirm(client, mock_gemini)
    msg = _say(client, pid, "yes, that worked")["message"]
    assert "phone number and email" in msg.lower(), msg
    assert "specialist" in msg.lower(), msg


def test_declining_to_save_details_closes_politely_and_writes_no_customer(client, seeded, mock_gemini):
    from crm.models import Customer

    pid = _solve_to_confirm(client, mock_gemini)
    _say(client, pid, "yes, that worked")
    before = Customer.objects.count()
    msg = _say(client, pid, "no thanks")["message"]
    assert "no problem" in msg.lower(), msg
    assert Customer.objects.count() == before, "declining must not create a customer"


def test_accepting_the_offer_collects_details_and_creates_the_customer(client, seeded, mock_gemini):
    from crm.models import Customer

    pid = _solve_to_confirm(client, mock_gemini)
    _say(client, pid, "yes, that worked")
    assert "name" in _say(client, pid, "yes please")["message"].lower()
    _say(client, pid, "Anna Berg")
    _say(client, pid, "070-555 01 99")
    final = _say(client, pid, "anna@example.se")["message"]

    c = Customer.objects.filter(name="Anna Berg").first()
    assert c is not None, "an accepted offer must create the customer"
    assert c.phone and c.phone.endswith("5550199"), c.phone
    assert c.email == "anna@example.se", c.email
    assert "specialist" in final.lower(), final


def test_abandoning_at_the_offer_still_records_a_resolved_case(client, seeded, mock_gemini):
    """If the customer closes the tab right after "yes, that worked", the case must
    already be RESOLVED. Holding resolution until the contact offer is answered would
    strand every such conversation as unresolved in the dashboard and skew the analytics."""
    from crm.models import Session

    pid = _solve_to_confirm(client, mock_gemini)
    out = _say(client, pid, "yes, that worked")          # offer shown; customer leaves here
    assert out["state"] == "RESOLVED", out["state"]

    session = Session.objects.filter(conversation__public_id=pid).first()
    assert session is not None and session.resolved, "an abandoned offer must still be resolved"


def test_the_stream_acks_before_the_slow_turn(client, seeded, mock_gemini, monkeypatch):
    """The widget aborts a request that has produced nothing after 20s.

    Django starts the response only when the generator is first iterated, so until this
    frame existed nothing reached the browser until the WHOLE turn had been computed. A
    turn that legitimately takes several seconds against Vertex then surfaced to the
    customer as "That took too long. Please try again." (seen in production 2026-09-13).
    """
    public_id = client.post("/api/chat/session", data="{}",
                            content_type="application/json").json()["public_id"]

    import chat.views as chat_views
    turns = []
    real = chat_views.process_turn

    def spy(*args, **kwargs):
        turns.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(chat_views, "process_turn", spy)

    resp = client.post(f"/api/chat/{public_id}/message",
                       data=json.dumps({"message": "Min värmepump larmar"}),
                       content_type="application/json")
    first = next(iter(resp.streaming_content)).decode()
    assert json.loads(first[len("data: "):])["type"] == "ack"
    assert not turns, "the ack must be flushed BEFORE the model call, not after it"

    # And the real reply still follows on the same stream.
    rest = _sse_events(resp)
    assert any(e["type"] == "message" for e in rest)
    assert turns, "the turn must still run"


def test_a_crash_mid_turn_still_answers_the_customer(client, seeded, mock_gemini, monkeypatch):
    """The ack is already on the wire, so an exception would otherwise truncate a stream
    the browser has accepted: the reader reaches done() and the customer is left staring at
    an empty bubble with nothing to retry."""
    public_id = client.post("/api/chat/session", data=json.dumps({"language": "sv"}),
                            content_type="application/json").json()["public_id"]

    import chat.views as chat_views

    def boom(*args, **kwargs):
        raise RuntimeError("simulated orchestrator failure")

    monkeypatch.setattr(chat_views, "process_turn", boom)

    events = _sse_events(client.post(
        f"/api/chat/{public_id}/message", data=json.dumps({"message": "Min pump larmar"}),
        content_type="application/json"))

    kinds = [e["type"] for e in events]
    assert "ack" in kinds and "final" in kinds, kinds
    msg = next(e for e in events if e["type"] == "message")
    assert msg["message"].strip(), "the customer must get words, not an empty bubble"
    assert msg["decision"] == "error"
    # Swedish conversation -> Swedish apology, and it must not blame the customer.
    assert "inte du" in msg["message"], msg["message"]
