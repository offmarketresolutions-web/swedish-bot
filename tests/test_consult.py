"""Brand-consult tool + question budget + small wires (conversation-core final build).

Covers:
- chat.consult.consult_brand unit: digest from notes, NOT-IN-NOTES fallback (no LLM),
  untrusted wrapping, candidate machines + machine notes in the material.
- Orchestrator consult flow: general specialist returns consult_brand → digest injected
  → same-turn re-render; reply budget not consumed; 1/turn + 3/conversation caps;
  disabled Tool row / role without the tool → ignored.
- Question budget ≤5: keyed counter increments on the right question types only;
  exhaustion forces routing with unknowns; disambiguation/brand-reconfirm +1 exception;
  reasks/repeat renders are free.
- Prompt wires: common_issues injection, citation-echo contract text, exploratory
  INTAKE section, {tools} block.
"""
import pytest
from django.core.management import call_command

from chat import consult, orchestrator as orch
from chat.casestate import new_case_state
from chat.prompts import render
from kb import tooling
from kb.models import AgentPrompt, BrandNote, Machine, MachineNote, Tool, Vendor

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


GENERAL_OK = {
    "answer_to_customer": "Check the breaker panel — look only.",
    "confidence": 0.9, "in_docs": True, "decision": "solve", "severity": "normal",
    "safe_steps_given": ["Look at the breaker"], "consult_brand": None,
    "extracted_facts": {"onset": None, "alarm_text": None, "model_text": None,
                        "error_code": None, "readings": [], "installer": None,
                        "operating_context": None, "check_results": []},
    "report": {}}


def _general_asks_consult(question="Known quirks for this brand?", **extra):
    d = dict(GENERAL_OK)
    d.update(extra)
    d["consult_brand"] = {"question": question}
    return d


def _drive_to_general(conv, *, brand="NIBE", problem="the heat pump is noisy"):
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")            # postcode declined
    orch.process_turn(conv, problem)
    orch.process_turn(conv, brand)
    orch.process_turn(conv, "unknown")       # no model -> general specialist runs


# ── consult_brand unit ─────────────────────────────────────────────────

def test_consult_no_vendor_deterministic_fallback(seeded, mock_gemini):
    out = consult.consult_brand("NoSuchBrand", None, "anything?")
    assert out == "NOT-IN-NOTES: no brand notes available"
    assert not [c for c in mock_gemini.calls if c["role"] == "consult_brand"]  # no LLM call


def test_consult_no_notes_deterministic_fallback(seeded, mock_gemini):
    Vendor.objects.get_or_create(name="Thermia", defaults={"slug": "thermia"})  # exists, zero notes
    out = consult.consult_brand("Thermia", None, "anything?")
    assert out == "NOT-IN-NOTES: no brand notes available"
    assert not [c for c in mock_gemini.calls if c["role"] == "consult_brand"]


def test_consult_digest_from_notes_wrapped_untrusted(seeded, mock_gemini):
    v = Vendor.objects.get(name="IVT")
    bn = BrandNote.objects.create(vendor=v, body="E21 usually means low brine flow.")
    m = Machine.objects.filter(vendor=v).first()
    MachineNote.objects.create(machine=m, body="Geo units: check the particle filter first.")
    captured = {}
    from core.services import gemini as gm
    real = gm.generate

    def capture(contents, **kw):
        captured["system"] = kw.get("system_instruction") or ""
        return real(contents, **kw)
    gm.generate = capture
    try:
        out = consult.consult_brand("IVT", m.model_name, "What does E21 mean?")
    finally:
        gm.generate = real
    assert out == "- mock brand digest [B1]"  # conftest consult_brand default
    sysline = captured["system"]
    assert "<<UNTRUSTED" in sysline and "END_UNTRUSTED" in sysline  # spotlighting
    assert f"[B{bn.pk}]" in sysline                                  # citation tags present
    assert "low brine flow" in sysline
    assert "particle filter" in sysline                              # machine note gathered
    assert f"[M{m.pk}]" in sysline                                   # candidate machine row


def test_consult_llm_failure_falls_back(seeded, mock_gemini, monkeypatch):
    v = Vendor.objects.get(name="IVT")
    BrandNote.objects.create(vendor=v, body="something")
    from core.services import gemini as gm

    def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(gm, "generate", boom)
    assert consult.consult_brand("IVT", None, "q?") == "NOT-IN-NOTES: no brand notes available"


# ── orchestrator consult flow ──────────────────────────────────────────

def test_consult_flow_same_turn_rerender_no_budget_consumed(seeded, mock_gemini):
    nibe, _ = Vendor.objects.get_or_create(name="NIBE", defaults={"slug": "nibe"})
    BrandNote.objects.create(vendor=nibe, body="NIBE quirk.")
    # 1st render asks a consult; the re-render (2nd specialist call, SAME turn) solves.
    seq = [_general_asks_consult(), dict(GENERAL_OK)]
    mock_gemini.responses["heat_pump_specialist"] = seq[0]
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")
    orch.process_turn(conv, "the heat pump is noisy")
    orch.process_turn(conv, "NIBE")
    # swap the canned response after the FIRST specialist call by hooking generate
    real = mock_gemini.generate
    state = {"specialist_calls": 0}

    def hooked(contents, **kw):
        sys = (kw.get("system_instruction") or "") + str(contents)[:2000]
        if "heat-pump troubleshooting specialist" in sys:
            state["specialist_calls"] += 1
            if state["specialist_calls"] >= 2:
                mock_gemini.responses["heat_pump_specialist"] = seq[1]
        return real(contents, **kw)
    import core.services.gemini as gm
    gm.generate = hooked
    try:
        res = orch.process_turn(conv, "unknown")
    finally:
        gm.generate = real
    conv.refresh_from_db()
    cs = conv.case_state
    # two specialist renders in ONE turn, one consult call in between
    assert state["specialist_calls"] == 2
    assert [c["role"] for c in mock_gemini.calls].count("consult_brand") == 1
    assert cs["consult_notes"] == ["- mock brand digest [B1]"]
    assert cs["consult_total"] == 1
    # the consult did NOT consume the customer-visible reply budget
    assert cs["specialist_turns"] == 1
    assert res["decision"] == "solve"


def test_consult_cap_three_per_conversation(seeded, mock_gemini):
    Vendor.objects.get_or_create(name="NIBE", defaults={"slug": "nibe"})
    BrandNote.objects.create(vendor=Vendor.objects.get(name="NIBE"), body="NIBE quirk.")
    # specialist ALWAYS asks a consult and never solves -> would loop forever without caps
    mock_gemini.responses["heat_pump_specialist"] = _general_asks_consult(
        confidence=0.9, in_docs=True, decision="solve")
    conv, _ = orch.open_conversation()
    _drive_to_general(conv)                      # turn 1: consult 1 + re-render (asks again -> capped at 1/turn)
    orch.process_turn(conv, "no still noisy")    # turn 2: consult 2
    orch.process_turn(conv, "no still noisy")    # turn 3: consult 3
    orch.process_turn(conv, "no still noisy")    # turn 4+: capped, no more consults
    conv.refresh_from_db()
    assert conv.case_state["consult_total"] == 3
    assert [c["role"] for c in mock_gemini.calls].count("consult_brand") == 3
    # only latest 2 digests are kept
    assert len(conv.case_state["consult_notes"]) == 2


def test_consult_ignored_when_tool_row_inactive(seeded, mock_gemini):
    Tool.objects.filter(slug="consult_brand").update(is_active=False)
    Vendor.objects.get_or_create(name="NIBE", defaults={"slug": "nibe"})
    mock_gemini.responses["heat_pump_specialist"] = _general_asks_consult()
    conv, _ = orch.open_conversation()
    _drive_to_general(conv)
    assert not [c for c in mock_gemini.calls if c["role"] == "consult_brand"]
    conv.refresh_from_db()
    assert conv.case_state.get("consult_total", 0) == 0


def test_consult_ignored_when_role_lacks_tool(seeded, mock_gemini):
    ap = AgentPrompt.objects.get(role="heat_pump_specialist")
    ap.tools.clear()
    Vendor.objects.get_or_create(name="NIBE", defaults={"slug": "nibe"})
    mock_gemini.responses["heat_pump_specialist"] = _general_asks_consult()
    conv, _ = orch.open_conversation()
    _drive_to_general(conv)
    assert not [c for c in mock_gemini.calls if c["role"] == "consult_brand"]


def test_seed_enables_consult_on_general_roles(seeded):
    for role in ("intelligent_specialist", "heat_pump_specialist",
                 "water_pump_specialist", "water_filtration_specialist"):
        assert tooling.tool_enabled(role, "consult_brand"), role
    assert not tooling.tool_enabled("specialist", "consult_brand")  # manual mode: no consult


# ── question budget ────────────────────────────────────────────────────

def test_budget_counts_intake_questions_only(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")   # -> postcode ask (1)
    orch.process_turn(conv, "12345")       # -> problem ask (2)
    orch.process_turn(conv, "no heat")     # -> brand ask (3)
    orch.process_turn(conv, "IVT")         # -> model ask (4)
    conv.refresh_from_db()
    assert conv.case_state["questions_asked"] == 4
    assert set(conv.case_state["question_keys"]) == {
        "slot:postal_code", "slot:problem", "slot:brand", "slot:model"}


def test_budget_reask_is_free(seeded, mock_gemini):
    # a reask of the SAME slot must not consume a second question
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")           # postcode ask (1)
    mock_gemini.responses["extractor"] = {"on_target": False, "value": None}
    orch.process_turn(conv, "gibberish")           # reask postcode — free
    conv.refresh_from_db()
    assert conv.case_state["questions_asked"] == 1


def test_budget_disambig_charges_and_gets_plus_one(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "12345")
    orch.process_turn(conv, "leaking a bit")
    orch.process_turn(conv, "IVT")
    res = orch.process_turn(conv, "Geo 600")   # ambiguous -> disambig chips (question 5)
    conv.refresh_from_db()
    cs = conv.case_state
    assert cs["await_model_confirm"] is True
    assert cs["questions_asked"] == 5
    # 'Annan modell' -> model_search still allowed at 5 via the documented +1 exception
    res2 = orch.process_turn(conv, "other_model")
    conv.refresh_from_db()
    assert conv.case_state["model_search_mode"] is True
    assert conv.case_state["questions_asked"] == 6  # documented overrun, max +1


def test_budget_exhaustion_forces_route_with_unknowns(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    cs = conv.case_state
    cs["question_keys"] = ["a", "b", "c", "d", "e"]   # budget spent
    cs["questions_asked"] = 5
    cs["slots"]["category"] = "heat_pump"
    cs["slots"]["problem"] = "no heat at all"
    cs["current_slot"] = None
    conv.case_state = cs
    conv.save(update_fields=["case_state"])
    res = orch.process_turn(conv, "hello")
    conv.refresh_from_db()
    cs = conv.case_state
    # brand/model filled unknown, routed to the general specialist — no more questions
    assert cs["slots"]["brand"] == "unknown" and cs["slots"]["model"] == "unknown"
    assert cs["state"] in ("SPECIALIST", "ESCALATE")  # routed with what we have
    assert cs["questions_asked"] == 5


def test_budget_specialist_and_contact_turns_do_not_count(seeded, mock_gemini):
    mock_gemini.responses["heat_pump_specialist"] = dict(GENERAL_OK)
    conv, _ = orch.open_conversation()
    _drive_to_general(conv)                     # intake spent 4 questions
    conv.refresh_from_db()
    before = conv.case_state["questions_asked"]
    orch.process_turn(conv, "no, still noisy")  # troubleshooting turn: confirm-fix Q not charged
    conv.refresh_from_db()
    assert conv.case_state["questions_asked"] == before


# ── prompt wires ───────────────────────────────────────────────────────

def _render_general(role="heat_pump_specialist", **kw):
    base = dict(locale="en", brand="NIBE", model="", category="heat_pump",
                general_knowledge="", problem="noisy", error_code="",
                forced_wrapup="false", previous_checks="", onset="",
                common_issues="", tools="", consult_notes="")
    base.update(kw)
    return render(role, **base)


def test_common_issues_injected_general_and_manual(seeded):
    out = _render_general(common_issues="NIBE units often trip on dirty filters.")
    assert "NIBE units often trip on dirty filters." in out
    man = render("specialist", locale="en", brand="IVT", model="Geo 600C",
                 category="water_to_water", brand_notes="", faq="", general_knowledge="",
                 problem="p", symptoms="", error_code="", serial="", forced_wrapup="false",
                 previous_checks="", onset="", common_issues="STAFF-NOTE-XYZ")
    assert "STAFF-NOTE-XYZ" in man
    assert "COMMON ISSUES" in man


def test_common_issues_empty_safe(seeded):
    out = _render_general(common_issues="")
    assert "{common_issues}" not in out


def test_citation_echo_in_contracts(seeded):
    from kb.seed_prompts import SPECIALIST, _GENERAL_TAIL, INTELLIGENT_SPECIALIST
    for body in (SPECIALIST, _GENERAL_TAIL, INTELLIGENT_SPECIALIST):
        assert "[K<number>]" in body  # citation-echo hook per kb/corpus.py


def test_consult_contract_key_in_general_prompts(seeded):
    from kb.seed_prompts import _GENERAL_TAIL, INTELLIGENT_SPECIALIST, SPECIALIST
    assert '"consult_brand"' in _GENERAL_TAIL
    assert '"consult_brand"' in INTELLIGENT_SPECIALIST
    assert '"consult_brand"' not in SPECIALIST  # manual mode has the manual — no consult


def test_exploratory_intake_section(seeded):
    from kb.seed_prompts import INTAKE
    assert "EXPLORATORY STYLE" in INTAKE
    assert "Berätta gärna" in INTAKE


def test_tools_block_renders_enabled_tools(seeded):
    block = tooling.render_tools_block("heat_pump_specialist")
    assert "TOOLS AVAILABLE" in block and "Consult brand notes" in block
    assert tooling.render_tools_block("router") == ""  # no tools -> empty
    out = _render_general(tools=block)
    assert "Consult brand notes" in out


def test_consult_notes_placeholder_injected(seeded):
    out = _render_general(consult_notes="- digest fact [B7]")
    assert "- digest fact [B7]" in out
    assert "{consult_notes}" not in out
