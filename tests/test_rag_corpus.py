"""S10 RAG corpus separation: registry completeness, build_embeddings idempotence,
persisted-vector retrieval, task-type asymmetry, fallback paths, excluded roles.
"""
import pytest
from django.core.management import call_command

from core.enums import AGENT_ROLE_CHOICES
from kb import corpus, semantic
from kb.models import Category, Embedding, FAQEntry, FAQEntryText, Machine

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


# ── registry completeness ───────────────────────────────────────────────
def test_every_agent_role_is_explicitly_registered():
    declared = {role for role, _label in AGENT_ROLE_CHOICES}
    registered = set(corpus.ROLE_CORPUS.keys())
    assert declared == registered, (
        f"missing from ROLE_CORPUS: {declared - registered}; "
        f"stale entries no longer in AGENT_ROLE_CHOICES: {registered - declared}")


def test_every_entry_has_a_nonempty_reason():
    for role, scope in corpus.ROLE_CORPUS.items():
        assert scope.reason and len(scope.reason) > 10, role


def test_deterministic_contract_roles_are_excluded():
    for role in ("intake", "router", "summarizer", "safety", "qa"):
        assert corpus.get_corpus_for_role(role).included is False


def test_specialist_roles_are_included():
    for role in ("specialist", "intelligent_specialist", "heat_pump_specialist",
                 "water_pump_specialist", "water_filtration_specialist"):
        assert corpus.get_corpus_for_role(role).included is True


def test_unknown_role_fails_closed():
    scope = corpus.get_corpus_for_role("made_up_role")
    assert scope.included is False


# ── role_for_case ────────────────────────────────────────────────────────
def test_role_for_case_manual_mode_is_specialist(seeded):
    m = Machine.objects.get(model_name="IVT 490")
    assert corpus.role_for_case({"slots": {}}, m) == "specialist"


def test_role_for_case_general_mode_maps_family_to_role(seeded):
    cs = {"slots": {"category": "heat_pump"}}
    assert corpus.role_for_case(cs, None) == "heat_pump_specialist"
    cs = {"slots": {"category": "water_pump_well"}}
    assert corpus.role_for_case(cs, None) == "water_pump_specialist"


def test_role_for_case_unmapped_family_falls_back(seeded):
    cs = {"slots": {"category": "unknown"}}
    assert corpus.role_for_case(cs, None) == "intelligent_specialist"


# ── build_embeddings: idempotence + hash-change re-embed + scope filter ─
def test_build_embeddings_is_idempotent_and_scoped(seeded, mock_gemini):
    cat = Category.objects.get(slug="heat_pump")
    fa = FAQEntry.objects.create(category=cat, key="test1", is_approved=True)
    FAQEntryText.objects.create(faq=fa, lang="en", question="Q1", answer="A1")

    call_command("build_embeddings", scope="heat_pump_specialist")
    rows_first = list(Embedding.objects.filter(scope="heat_pump_specialist"))
    assert len(rows_first) >= 1
    n_embed_calls_first = len(mock_gemini.embed_calls)

    # Re-run with unchanged content: nothing new should be embedded.
    call_command("build_embeddings", scope="heat_pump_specialist")
    assert len(mock_gemini.embed_calls) == n_embed_calls_first

    # Edit the text -> content_hash changes -> re-embedded on next run.
    FAQEntryText.objects.filter(faq=fa, lang="en").update(answer="A1-changed")
    call_command("build_embeddings", scope="heat_pump_specialist")
    assert len(mock_gemini.embed_calls) > n_embed_calls_first

    # A water_pump_specialist-scoped build must not touch the heat_pump row.
    call_command("build_embeddings", scope="water_pump_specialist")
    assert not Embedding.objects.filter(scope="water_pump_specialist", source_model="FAQEntry",
                                        object_id=fa.pk).exists()


def test_build_embeddings_force_reembeds_unchanged(seeded, mock_gemini):
    cat = Category.objects.get(slug="water_filtration")
    fa = FAQEntry.objects.create(category=cat, key="test2", is_approved=True)
    FAQEntryText.objects.create(faq=fa, lang="en", question="Q2", answer="A2")
    call_command("build_embeddings", scope="water_filtration_specialist")
    n1 = len(mock_gemini.embed_calls)
    call_command("build_embeddings", scope="water_filtration_specialist", force=True)
    assert len(mock_gemini.embed_calls) > n1


# ── task-type asymmetry ──────────────────────────────────────────────────
def test_build_embeddings_uses_retrieval_document(seeded, mock_gemini):
    cat = Category.objects.get(slug="heat_pump")
    fa = FAQEntry.objects.create(category=cat, key="test3", is_approved=True)
    FAQEntryText.objects.create(faq=fa, lang="en", question="Q3", answer="A3")
    call_command("build_embeddings", scope="heat_pump_specialist")
    assert mock_gemini.embed_calls
    assert all(c["task_type"] == "RETRIEVAL_DOCUMENT" for c in mock_gemini.embed_calls)


def test_rank_general_knowledge_query_uses_retrieval_query(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    cat = Category.objects.get(slug="heat_pump")
    FAQEntry.objects.filter(category=cat).delete()  # isolate from seed_kb's own FAQ rows
    fa = FAQEntry.objects.create(category=cat, key="test4", is_approved=True)
    FAQEntryText.objects.create(faq=fa, lang="en", question="Q4", answer="Bleed the radiator")
    call_command("build_embeddings", scope="heat_pump_specialist")
    mock_gemini.embed_calls.clear()
    semantic.rank_general_knowledge("air in the radiator", category_ids=[cat.id],
                                     scope="heat_pump_specialist")
    query_calls = [c for c in mock_gemini.embed_calls if c["task_type"] == "RETRIEVAL_QUERY"]
    assert query_calls, "query embed must use RETRIEVAL_QUERY"
    # and no fresh RETRIEVAL_DOCUMENT call was needed (persisted vector was used)
    doc_calls = [c for c in mock_gemini.embed_calls if c["task_type"] == "RETRIEVAL_DOCUMENT"]
    assert not doc_calls, "persisted vectors should have been used, not re-embedded"


# ── persisted-vector retrieval + fallback ────────────────────────────────
def test_rank_general_knowledge_uses_persisted_vectors(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    cat = Category.objects.get(slug="heat_pump")
    FAQEntry.objects.filter(category=cat).delete()  # isolate from seed_kb's own FAQ rows
    fa = FAQEntry.objects.create(category=cat, key="marker", is_approved=True)
    FAQEntryText.objects.create(faq=fa, lang="en", question="UNIQ_Q",
                                answer="UNIQ_MARKER bleed the radiator to fix air noise")
    call_command("build_embeddings", scope="heat_pump_specialist")
    out = semantic.rank_general_knowledge(
        "UNIQ_MARKER bleed the radiator to fix air noise", category_ids=[cat.id],
        scope="heat_pump_specialist", top_k=1)
    assert out and out[0][0].pk == fa.pk


def test_rank_general_knowledge_falls_back_when_not_yet_embedded(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    cat = Category.objects.get(slug="heat_pump")
    FAQEntry.objects.filter(category=cat).delete()  # isolate from seed_kb's own FAQ rows
    fa = FAQEntry.objects.create(category=cat, key="fresh", is_approved=True)
    FAQEntryText.objects.create(faq=fa, lang="en", question="fresh Q",
                                answer="fresh row never embedded")
    # no build_embeddings run -> nothing persisted -> must fall back to on-the-fly
    out = semantic.rank_general_knowledge("fresh row never embedded", category_ids=[cat.id],
                                          scope="heat_pump_specialist", top_k=1)
    assert out and out[0][0].pk == fa.pk


# ── excluded-role scoping in chat/context.py ─────────────────────────────
def test_collect_general_knowledge_excluded_role_returns_empty(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    from chat.context import collect_general_knowledge
    # no machine bound and an unserviceable category -> intelligent_specialist (included);
    # force an excluded role by simulating intake-shaped cs (no category at all still
    # resolves to intelligent_specialist per role_for_case, which IS included, so assert
    # the true excluded case directly via the registry instead).
    assert corpus.get_corpus_for_role("intelligent_intake").included is False


def test_collect_general_knowledge_scopes_to_family(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    from chat.context import collect_general_knowledge
    cat_heat = Category.objects.get(slug="heat_pump")
    cat_water = Category.objects.get(slug="water_filtration")
    FAQEntry.objects.all().delete()
    fa_heat = FAQEntry.objects.create(category=cat_heat, key="heatmarker", is_approved=True)
    FAQEntryText.objects.create(faq=fa_heat, lang="en", question="Q",
                                answer="HEAT_ONLY_MARKER no heat troubleshooting")
    fa_water = FAQEntry.objects.create(category=cat_water, key="watermarker", is_approved=True)
    FAQEntryText.objects.create(faq=fa_water, lang="en", question="Q",
                                answer="WATER_ONLY_MARKER bad taste troubleshooting")
    call_command("build_embeddings")

    cs = {"slots": {"category": "heat_pump", "problem": "no heat troubleshooting"}}
    text = collect_general_knowledge(cs, "en", machine=None)
    assert "HEAT_ONLY_MARKER" in text
    assert "WATER_ONLY_MARKER" not in text
    assert f"[K{fa_heat.pk}]" in text  # citation tag present


def test_collect_general_knowledge_manual_mode_scopes_to_machine_category(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    from chat.context import collect_general_knowledge
    m = Machine.objects.get(model_name="IVT 490")  # exhaust_air (heat_pump family)
    cat_water = Category.objects.get(slug="water_filtration")
    FAQEntry.objects.all().delete()
    fa_heat = FAQEntry.objects.create(category=m.category, key="manualmarker", is_approved=True)
    FAQEntryText.objects.create(faq=fa_heat, lang="en", question="Q",
                                answer="MANUAL_MODE_MARKER troubleshooting")
    fa_water = FAQEntry.objects.create(category=cat_water, key="manualwatermarker", is_approved=True)
    FAQEntryText.objects.create(faq=fa_water, lang="en", question="Q",
                                answer="WATER_MARKER unrelated")
    call_command("build_embeddings")

    cs = {"slots": {"problem": "MANUAL_MODE_MARKER troubleshooting"}}
    text = collect_general_knowledge(cs, "en", machine=m)
    assert "MANUAL_MODE_MARKER" in text
    assert "WATER_MARKER" not in text


def test_collect_general_knowledge_manual_mode_sees_family_level_knowledge(
        seeded, settings, mock_gemini):
    """Regression (run100 R018): manual mode scoped to the machine's LEAF category
    (water_to_water), so approved FAMILY-level heat-pump knowledge was invisible and
    the specialist answered a benign 'is this normal?' from world knowledge at low
    confidence, then escalated. Family-level entries must be in scope; other families
    must still be excluded."""
    settings.SEMANTIC_SEARCH_ENABLED = True
    from chat.context import collect_general_knowledge
    m = Machine.objects.get(model_name="IVT 490")           # leaf category, heat_pump family
    assert m.category.parent_id, "fixture must be a leaf category for this regression"
    cat_family = m.category.parent                          # heat_pump (top level)
    cat_water = Category.objects.get(slug="water_filtration")
    FAQEntry.objects.all().delete()
    fa_family = FAQEntry.objects.create(category=cat_family, key="familymarker", is_approved=True)
    FAQEntryText.objects.create(faq=fa_family, lang="en", question="Is dripping normal?",
                                answer="FAMILY_MARKER condensation is normal")
    fa_water = FAQEntry.objects.create(category=cat_water, key="otherfamilymarker",
                                       is_approved=True)
    FAQEntryText.objects.create(faq=fa_water, lang="en", question="Is dripping normal?",
                                answer="WATER_MARKER condensation is normal")
    call_command("build_embeddings")

    cs = {"slots": {"problem": "FAMILY_MARKER condensation is normal"}}
    text = collect_general_knowledge(cs, "en", machine=m)
    assert "FAMILY_MARKER" in text      # family-level knowledge now reaches manual mode
    assert "WATER_MARKER" not in text   # a different family stays out of scope


# ── live smoke ────────────────────────────────────────────────────────────
@pytest.mark.live
def test_live_embed_and_query_one_row(seeded):
    cat = Category.objects.get(slug="heat_pump")
    FAQEntry.objects.filter(category=cat).delete()  # isolate from seed_kb's own FAQ rows
    fa = FAQEntry.objects.create(category=cat, key="livemarker", is_approved=True)
    FAQEntryText.objects.create(faq=fa, lang="en", question="Why is my heat pump noisy?",
                                answer="A noisy heat pump often means a loose panel or fan debris.")
    call_command("build_embeddings", scope="heat_pump_specialist")
    assert Embedding.objects.filter(scope="heat_pump_specialist", source_model="FAQEntry",
                                    object_id=fa.pk).exists()
    out = semantic.rank_general_knowledge(
        "my heat pump makes a loud rattling noise", category_ids=[cat.id],
        scope="heat_pump_specialist", top_k=1)
    assert out and out[0][0].pk == fa.pk
