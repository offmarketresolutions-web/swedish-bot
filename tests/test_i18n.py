"""i18n: message catalog parity, Swedish chips, and a full Swedish bot flow (plan §11)."""
import pytest
from django.core.management import call_command

from chat import intake
from chat import orchestrator as orch
from chat.casestate import new_case_state
from chat.i18n import T, t


def test_catalog_has_parity_across_languages():
    assert set(T["en"]) == set(T["sv"])  # every key translated


def test_t_returns_swedish_and_falls_back():
    assert t("sv", "greeting").startswith("Hej")
    assert "tekniker" in t("sv", "escalate_leadin")
    assert t("xx", "greeting") == t("en", "greeting")  # unknown locale → English
    assert "070" in t("sv", "thanks", name_sfx=" Jane", phone_sfx=" på 070")


@pytest.mark.django_db
def test_chips_localize_after_seed():
    call_command("seed_kb")
    cs = new_case_state()
    sv = {c["label"] for c in intake.chips_for("category", cs, "sv")}
    en = {c["label"] for c in intake.chips_for("category", cs, "en")}
    assert "Värmepump" in sv
    assert "Heat pump" in en


@pytest.mark.django_db
def test_open_conversation_in_swedish(mock_gemini):
    call_command("seed_kb")
    conv, greet = orch.open_conversation("sv")
    assert greet["message"].startswith("Hej")
    assert any(c["label"] == "Värmepump" for c in greet["chips"])


@pytest.mark.django_db
def test_full_swedish_escalation_flow(mock_gemini):
    call_command("seed_kb")
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Jag är inte tillräckligt säker.", "confidence": 0.4,
        "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation("sv")
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "IVT")
    res = orch.process_turn(conv, "IVT 490")            # → Swedish escalation lead-in
    assert "tekniker" in res["message"]
    orch.process_turn(conv, "Jan Svensson")
    orch.process_turn(conv, "070-1112233")
    orch.process_turn(conv, "skip")
    approval = orch.process_turn(conv, "98101")
    assert any(c["label"] == "Ja, skicka till Nordland" for c in approval["chips"])
    done = orch.process_turn(conv, "ja")               # Swedish "yes"
    assert "Tack" in done["message"]
