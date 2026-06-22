"""V2 semantic search: embedding fallback for identification + FAQ/guide retrieval.

The mock embedder is hash-based (deterministic, identical text → cosine 1.0) so
these tests verify the PLUMBING + gating + fail-safe behavior; real semantic
QUALITY (e.g. sv↔en match) is verified live via `manage.py check_ai`.
"""
import pytest
from django.core.management import call_command

from kb import identification, semantic
from kb.models import Category, FAQEntry, GenericGuide, Machine

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


# ── gating / fail-safe ────────────────────────────────────────────────
def test_disabled_returns_empty(seeded, settings):
    settings.SEMANTIC_SEARCH_ENABLED = False
    assert semantic.semantic_identify("IVT 490") == (None, 0.0)
    assert semantic.rank_guides("anything") == []


def test_identify_no_semantic_when_disabled(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = False
    machine, _ = identification.identify_machine("zzqq nonexistent model")
    assert machine is None  # trigram misses, semantic off → no claim


# ── identification fallback ───────────────────────────────────────────
def test_semantic_identify_matches_self(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    m = Machine.objects.get(model_name="IVT 490")
    machine, cos = semantic.semantic_identify(m.search_text)
    assert machine == m and cos > 0.99  # identical text → cosine ~1.0


def test_identify_uses_semantic_fallback_when_trigram_misses(seeded, settings, monkeypatch):
    settings.SEMANTIC_SEARCH_ENABLED = True
    m = Machine.objects.get(model_name="IVT 490")
    monkeypatch.setattr(semantic, "semantic_identify", lambda q, vendor=None: (m, 0.91))
    machine, score = identification.identify_machine("xyzzy totally unmatchable text")
    assert machine == m
    # conservative confidence (not the raw 0.91 cosine) so safety gates still fire
    assert score == semantic.SEMANTIC_MATCH_CONFIDENCE and score < 0.7


def test_semantic_fallback_respects_threshold(seeded, settings, monkeypatch):
    settings.SEMANTIC_SEARCH_ENABLED = True
    m = Machine.objects.get(model_name="IVT 490")
    # below SEM_IDENTIFY_THRESHOLD → must NOT claim (a wrong manual is worse than none)
    monkeypatch.setattr(semantic, "semantic_identify", lambda q, vendor=None: (m, 0.50))
    machine, _ = identification.identify_machine("xyzzy totally unmatchable text")
    assert machine is None


# ── FAQ / guide retrieval ─────────────────────────────────────────────
def test_rank_guides_returns_scored_list(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    cat = Category.objects.first()
    GenericGuide.objects.create(category=cat, key="air", kind="guide", lang="en",
                                body="Bleed the radiator to release trapped air.")
    out = semantic.rank_guides("how do I get air out of the radiator", top_k=3)
    assert isinstance(out, list) and len(out) >= 1
    assert all(isinstance(t, str) and isinstance(s, float) for t, s in out)


def test_collect_knowledge_appends_semantic_guides(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    from chat.context import collect_knowledge
    # isolate the semantic corpus so the marked guide is deterministically top-ranked
    GenericGuide.objects.all().delete()
    FAQEntry.objects.all().delete()
    cat = Category.objects.first()
    GenericGuide.objects.create(category=cat, key="uniqueguide", kind="guide", lang="en",
                                body="UNIQ_MARKER bleed the system safely.")
    m = Machine.objects.get(model_name="IVT 490")
    _notes, faq = collect_knowledge(m, "en", query="air in the system")
    assert "UNIQ_MARKER" in faq  # semantic retrieval injected it


def test_collect_knowledge_no_query_is_unchanged(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    from chat.context import collect_knowledge
    m = Machine.objects.get(model_name="IVT 490")
    # no query → no semantic call, just the deterministic category FAQ/guide path
    notes, faq = collect_knowledge(m, "en")
    assert isinstance(notes, str) and isinstance(faq, str)
