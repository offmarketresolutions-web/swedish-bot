"""Approval-gated retrieval (V2 plan §D2 / Sprint S1): FAQEntry/SiteFAQ gained
`is_approved` (default True so existing hand-authored rows stay live). Imported
general-knowledge rows land unapproved and must be excluded from both retrieval
paths — rank_guides (semantic) and collect_knowledge (specialist injection) —
until staff approve them in the dashboard."""
import pytest
from django.core.management import call_command

from kb import semantic
from kb.models import Category, FAQEntry, FAQEntryText, Machine, SiteFAQ

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def test_faq_entry_defaults_approved():
    cat, _ = Category.objects.get_or_create(slug="heat_pump", defaults={"name": "Heat pump"})
    faq = FAQEntry.objects.create(category=cat, key="k1")
    assert faq.is_approved is True


def test_site_faq_defaults_approved():
    faq = SiteFAQ.objects.create(slug="s1", question="Q", answer="A")
    assert faq.is_approved is True


def test_rank_guides_excludes_unapproved_faq_entry(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    cat = Category.objects.first()
    faq = FAQEntry.objects.create(category=cat, key="unapproved_marker", is_approved=False)
    FAQEntryText.objects.create(faq=faq, lang="en",
                                question="UNIQ_MARKER_Q what is this",
                                answer="UNIQ_MARKER_A should never surface")
    out = semantic.rank_guides("UNIQ_MARKER_Q what is this", top_k=10)
    assert not any("UNIQ_MARKER_A" in text for text, _score in out)

    faq.is_approved = True
    faq.save(update_fields=["is_approved"])
    out2 = semantic.rank_guides("UNIQ_MARKER_Q what is this", top_k=10)
    assert any("UNIQ_MARKER_A" in text for text, _score in out2)


def test_rank_guides_excludes_unapproved_site_faq(seeded, settings, mock_gemini):
    settings.SEMANTIC_SEARCH_ENABLED = True
    faq = SiteFAQ.objects.create(
        slug="unapproved-site-faq", question="UNIQ_SITE_Q booking hours",
        answer="UNIQ_SITE_A never surface", is_active=True, is_approved=False)
    out = semantic.rank_guides("UNIQ_SITE_Q booking hours", top_k=10)
    assert not any("UNIQ_SITE_A" in text for text, _score in out)

    faq.is_approved = True
    faq.save(update_fields=["is_approved"])
    out2 = semantic.rank_guides("UNIQ_SITE_Q booking hours", top_k=10)
    assert any("UNIQ_SITE_A" in text for text, _score in out2)


def test_collect_knowledge_excludes_unapproved_faq_entry(seeded):
    from chat.context import collect_knowledge
    m = Machine.objects.get(model_name="IVT 490")
    faq = FAQEntry.objects.create(category=m.category, key="unapproved_ck", is_approved=False)
    FAQEntryText.objects.create(faq=faq, lang="en",
                                question="UNIQ_CK_Q", answer="UNIQ_CK_A")
    _notes, faq_text = collect_knowledge(m, "en")
    assert "UNIQ_CK_A" not in faq_text

    faq.is_approved = True
    faq.save(update_fields=["is_approved"])
    _notes, faq_text2 = collect_knowledge(m, "en")
    assert "UNIQ_CK_A" in faq_text2
