"""S3 Routing v2 — no-auto-bind, candidate chips, Annan modell search, suggest_models,
subtype narrowing, brand preservation, three-way route (general specialist),
general-mode budget, approved-only general-knowledge retrieval, manual text fallback,
and the brand-vendor seed.
"""
import pytest
from django.core.management import call_command

from chat import context, intake
from chat import orchestrator as orch
from kb import identification as ident
from kb import semantic

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")
    from kb.models import Category, Machine, Vendor

    ivt = Vendor.objects.get(name="IVT")
    w2w = Category.objects.get(slug="water_to_water")
    # An ambiguity family: "Geo 600" must not silently bind either of these.
    for mn, slug in (("Geo 600C", "geo-600c"), ("Geo 600E", "geo-600e")):
        Machine.objects.get_or_create(
            vendor=ivt, model_name=mn,
            defaults=dict(category=w2w, slug=slug, is_supported=True,
                          aliases=[mn.lower().replace(" ", "")]))
    return {"ivt": ivt, "w2w": w2w}


def _drive_to_model(conv, *, brand="IVT", problem="it is leaking a bit of water"):
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")          # postcode declined
    orch.process_turn(conv, problem)
    orch.process_turn(conv, brand)


# ── no-auto-bind: exact match binds, partial does not ─────────────────────
def test_exact_model_binds_fast_path(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_model(conv)
    orch.process_turn(conv, "Geo 600C")     # exact -> bind + confirmed
    conv.refresh_from_db()
    cs = conv.case_state
    m = seeded["ivt"].machines.get(model_name="Geo 600C")
    assert cs["machine_id"] == m.id
    assert cs["model_confirmed"] is True
    assert cs["specialist_mode"] == "manual"


def test_partial_model_offers_candidates_no_silent_bind(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_model(conv)
    res = orch.process_turn(conv, "Geo 600")   # ambiguous -> chips, NO bind
    conv.refresh_from_db()
    cs = conv.case_state
    assert cs["await_model_confirm"] is True
    assert cs["machine_id"] is None
    assert cs["model_confirmed"] is False
    labels = {c["value"] for c in res["chips"]}
    assert {"Geo 600C", "Geo 600E", "other_model", "unknown"} <= labels
    # tapping a candidate binds it
    orch.process_turn(conv, "Geo 600E")
    conv.refresh_from_db()
    cs = conv.case_state
    assert cs["machine_id"] == seeded["ivt"].machines.get(model_name="Geo 600E").id
    assert cs["model_confirmed"] is True


def test_other_model_search_then_exact_binds(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_model(conv)
    orch.process_turn(conv, "Geo 600")         # -> disambig chips
    res = orch.process_turn(conv, "other_model")   # -> free-text search prompt
    conv.refresh_from_db()
    assert conv.case_state["model_search_mode"] is True
    assert conv.case_state["machine_id"] is None
    assert res["chips"] == []
    orch.process_turn(conv, "Geo 600C")        # exact typed -> bind
    conv.refresh_from_db()
    assert conv.case_state["machine_id"] == seeded["ivt"].machines.get(model_name="Geo 600C").id


def test_unknown_at_disambig_does_not_bind_goes_general(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_model(conv)
    orch.process_turn(conv, "Geo 600")
    orch.process_turn(conv, "unknown")         # gives up -> no bind, serviced -> general
    conv.refresh_from_db()
    cs = conv.case_state
    assert cs["machine_id"] is None
    assert cs["model_confirmed"] is False
    assert cs["specialist_mode"] == "general"


# ── identification helpers (retrieval only) ──────────────────────────────
def test_candidate_matches_and_exact(seeded):
    ivt = seeded["ivt"]
    cands = ident.candidate_matches("IVT Geo 600", vendor=ivt, limit=4)
    names = {m.model_name for m, _ in cands}
    assert {"Geo 600C", "Geo 600E"} <= names
    assert ident.exact_machine("Geo 600", "Geo 600", vendor=ivt) is None
    assert ident.exact_machine("Geo 600C", "Geo 600C", vendor=ivt).model_name == "Geo 600C"


def test_suggest_models_full_catalog_incl_manual_less(seeded):
    # suggest_models spans the full supported catalog (no documents__isnull filter).
    sugg = ident.suggest_models("Geo 600", vendor=seeded["ivt"], limit=5)
    assert any(m.model_name == "Geo 600C" for m, _ in sugg)


def test_suggest_models_category_narrowing(seeded):
    from kb.models import Category
    w2w = [Category.objects.get(slug="water_to_water").id]
    # Grundfos SQ is water_pump_well -> excluded when narrowing to water_to_water
    sugg = ident.suggest_models("Grundfos SQ", category_ids=w2w, floor=0.05)
    assert all(m.category.slug != "water_pump_well" for m, _ in sugg)


# ── model chips: Annan modell + subtype narrowing ────────────────────────
def test_model_chips_include_other_model(seeded):
    cs = orch.new_state = {"slots": {"category": "heat_pump", "brand": None, "subtype": None}}
    chips = intake.chips_for("model", cs, "en")
    vals = {c["value"] for c in chips}
    assert "other_model" in vals and "unknown" in vals


def test_model_chips_subtype_narrows(seeded):
    from kb.models import Category, Machine, MachineDocument, Vendor
    ivt = seeded["ivt"]
    bosch = Vendor.objects.get(name="Bosch")
    # give one exhaust_air + one air_to_water machine a document so they'd chip
    ex = Machine.objects.get(model_name="IVT 490")  # exhaust_air
    aw = Machine.objects.get(model_name="Bosch Compress 7000i")  # air_to_water
    MachineDocument.objects.create(machine=ex, parsed_text="x")
    MachineDocument.objects.create(machine=aw, parsed_text="y")
    cs = {"slots": {"category": "heat_pump", "brand": None, "subtype": "exhaust_air"}}
    vals = {c["value"] for c in intake.chips_for("model", cs, "en")}
    assert "IVT 490" in vals
    assert "Bosch Compress 7000i" not in vals   # narrowed away by subtype


# ── brand preservation ───────────────────────────────────────────────────
def test_brand_vendor_seed_present_and_no_machines(seeded):
    from kb.models import Vendor
    for name in ("NIBE", "CTC", "Thermia", "Daikin", "Mitsubishi Electric",
                 "Panasonic", "Toshiba", "DAB", "Callidus"):
        v = Vendor.objects.get(name=name)
        assert v.is_active is True
        assert v.machines.count() == 0


def test_brand_vendor_seed_idempotent(seeded):
    from kb.models import Vendor
    before = Vendor.objects.count()
    # update_or_create on the same slug must not duplicate
    Vendor.objects.update_or_create(slug="nibe", defaults={"name": "NIBE", "is_active": True})
    assert Vendor.objects.count() == before


def test_unlisted_brand_kept_verbatim_in_bulk(seeded, mock_gemini):
    cs = {"slots": {k: None for k in ("category", "brand", "model")}}
    mock_gemini.responses["bulk"] = {
        "category": "heat_pump", "brand": "Grönland VP", "model": None,
        "error_code": None, "alarm_text": None, "onset": None, "postal_code": None,
        "installer": None, "operating_context": None, "readings": [],
        "subtype": None, "problem": "no heat"}
    out = intake.bulk_extract("my Grönland VP heat pump has no heat", cs, "en")
    assert out["brand"] == "Grönland VP"   # not squashed to "other"


# ── three-way route: general specialist ──────────────────────────────────
def test_general_mode_budget_is_three(seeded, mock_gemini):
    # a serviced-category, no-machine case that keeps "solving" burns the 3-turn general
    # budget then force-escalates (reason "budget") — proving GENERAL_REPLY_BUDGET=3 < 5.
    # NIBE heat pump → the heat_pump_specialist general role (feature 1 split).
    mock_gemini.responses["heat_pump_specialist"] = {
        "answer_to_customer": "Check that the display reads a normal temperature.",
        "confidence": 0.9, "in_docs": True, "decision": "solve", "severity": "normal",
        "safe_steps_given": ["Read the display"], "report": {},
        "extracted_facts": {"onset": None, "alarm_text": None, "model_text": None,
                            "error_code": None, "readings": [], "installer": None,
                            "operating_context": None, "check_results": []}}
    conv, _ = orch.open_conversation()
    _drive_to_model(conv, brand="NIBE", problem="the heat pump is a bit noisy")
    orch.process_turn(conv, "unknown")     # no model -> general specialist (turn 1, solve)
    conv.refresh_from_db()
    assert conv.case_state["specialist_mode"] == "general"
    orch.process_turn(conv, "no still noisy")   # turn 2, solve
    res = orch.process_turn(conv, "no still noisy")   # turn 3 -> forced budget escalate
    conv.refresh_from_db()
    assert conv.case_state["state"] == "ESCALATE"
    assert conv.case_state["escalation_reason"] == "budget"


def test_general_mode_default_escalates_without_fabrication(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_model(conv, brand="NIBE", problem="error 163 shows on the display")
    res = orch.process_turn(conv, "unknown")   # general specialist, default = escalate
    conv.refresh_from_db()
    assert conv.case_state["specialist_mode"] == "general"
    assert conv.case_state["state"] == "ESCALATE"
    low = res["message"].lower()
    assert "163 means" not in low and "163 is caused by" not in low


# ── general-knowledge retrieval: approved-only + keyword fallback ─────────
def _mk_faq(category, key, q, a, *, approved, keywords):
    from kb.models import FAQEntry, FAQEntryText
    fa = FAQEntry.objects.create(category=category, key=key, is_approved=approved,
                                 keywords=keywords)
    FAQEntryText.objects.create(faq=fa, lang="en", question=q, answer=a)
    return fa


def test_rank_general_knowledge_approved_only_keyword_fallback(seeded, settings):
    settings.SEMANTIC_SEARCH_ENABLED = False   # force deterministic keyword fallback
    from kb.models import Category
    hp = Category.objects.get(slug="heat_pump")
    ok = _mk_faq(hp, "gk_ok", "Why is my heat pump noisy?",
                 "Noise can come from ice buildup.", approved=True, keywords=["noise", "noisy"])
    _mk_faq(hp, "gk_pending", "Noisy pump pending",
            "Unapproved noise entry.", approved=False, keywords=["noise", "noisy"])
    hits = semantic.rank_general_knowledge("my heat pump is noisy", category_ids=[hp.id])
    ids = {fa.pk for fa, _ in hits}
    assert ok.pk in ids
    assert all(fa.is_approved for fa, _ in hits)   # never surfaces the unapproved row


def test_collect_general_knowledge_includes_safe_checks(seeded, settings):
    settings.SEMANTIC_SEARCH_ENABLED = False
    from kb.models import Category, FAQEntry, FAQEntryText
    hp = Category.objects.get(slug="heat_pump")
    fa = FAQEntry.objects.create(category=hp, key="gk_checks", is_approved=True,
                                 keywords=["pressure"], safe_customer_checks="Read the gauge.",
                                 service_trigger="If below 0.5 bar, book a visit.")
    FAQEntryText.objects.create(faq=fa, lang="en", question="Low pressure?",
                                answer="Pressure may be low.")
    cs = {"slots": {"category": "heat_pump", "subtype": None, "onset": None,
                    "problem": "the pressure is low"}}
    block = context.collect_general_knowledge(cs, "en")
    assert "Read the gauge." in block and "book a visit" in block


# ── manual text fallback (S1 text-only manuals) ──────────────────────────
def test_machine_pdf_context_text_fallback(seeded):
    from kb.models import Machine, MachineDocument
    m = Machine.objects.get(model_name="IVT 490")
    MachineDocument.objects.create(machine=m, parsed_text="SECRET MANUAL BODY", pdf="")
    cached, inline = context.machine_pdf_context(m, "en")
    assert cached is None
    assert inline and "SECRET MANUAL BODY" in inline[0]
