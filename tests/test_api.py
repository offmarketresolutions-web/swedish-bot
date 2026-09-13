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
    assert _strip_kb_tags("Inga taggar här.") == "Inga taggar här."
    assert _strip_kb_tags("") == ""
    assert _strip_kb_tags(None) == ""
    # a bracketed non-citation must survive
    assert _strip_kb_tags("Se [Kapitel 4] i manualen.") == "Se [Kapitel 4] i manualen."
