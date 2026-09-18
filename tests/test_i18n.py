"""i18n: message catalog parity, Swedish chips, and a full Swedish bot flow (plan §11)."""
import pytest
from django.core.management import call_command

from chat import intake
from chat import orchestrator as orch
from chat.casestate import new_case_state
from chat.i18n import T, t
from crm.models import ServiceRequest


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
    orch.process_turn(conv, "no")                       # postcode asked early (declined)
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "IVT")
    res = orch.process_turn(conv, "IVT 490")            # → Swedish diagnostics ask
    assert "tekniker" in res["message"]
    orch.process_turn(conv, "skramlar, kod E9")         # diagnostics reply → asks name
    orch.process_turn(conv, "Jan Svensson")
    orch.process_turn(conv, "070-1112233")
    orch.process_turn(conv, "skip")
    orch.process_turn(conv, "98101")                   # postal → address
    approval = orch.process_turn(conv, "Storgatan 5")  # address → approval
    assert any(c["label"] == "Ja, skicka till Nordland" for c in approval["chips"])
    done = orch.process_turn(conv, "ja")               # Swedish "yes"
    assert "Tack" in done["message"]
    conv.refresh_from_db()
    # GAP #9 (audit): a real lead was dispatched -> "terminal" (Nordland hör av sig) is now
    # a true claim, not an over-promise.
    assert conv.case_state.get("lead_dispatched") is True
    followup = orch.process_turn(conv, "tack")         # chit-chat close -> _terminal_step
    assert followup["message"] == t("sv", "terminal")
    assert "hör av sig" in followup["message"]


@pytest.mark.django_db
def test_terminal_no_lead_after_self_fix(mock_gemini):
    """GAP #9 (audit): a case solved without ever escalating must NOT claim Nordland VVS
    will follow up -- nobody is calling. lead_dispatched is only set at the single
    leads.create_and_dispatch() call site, which this flow never reaches."""
    call_command("seed_kb")
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Try resetting the breaker.", "confidence": 0.9,
        "decision": "solve", "in_docs": True, "report": {"resolved": True},
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")
    orch.process_turn(conv, "no heat")
    orch.process_turn(conv, "IVT")
    orch.process_turn(conv, "IVT 490")
    orch.process_turn(conv, "yes, that worked, thanks")   # confirm fix -> RESOLVED, save-offer
    orch.process_turn(conv, "no")                          # decline the save-details offer
    conv.refresh_from_db()
    assert conv.case_state["state"] == "RESOLVED"
    assert not conv.case_state.get("lead_dispatched")
    followup = orch.process_turn(conv, "thanks")           # chit-chat close -> _terminal_step
    assert followup["message"] == t("en", "terminal_no_lead")
    assert "Nordland" not in followup["message"]


def test_outside_area_decline_does_not_imply_bot_books_elsewhere():
    """GAP #9 (audit): the bot never books a visit anywhere -- "I can't book a technician
    visit there" implied it books visits elsewhere. Neither locale's decline string may
    frame the limitation as the bot's own booking capability."""
    en = t("en", "outside_area_decline", area_sfx="")
    sv = t("sv", "outside_area_decline", area_sfx="")
    assert "book" not in en.lower() and "i can't" not in en.lower()
    assert "boka" not in sv.lower() and "jag kan inte" not in sv.lower()
