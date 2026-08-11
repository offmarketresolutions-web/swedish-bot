"""RAG corpus-suitability registry (S10) — the single source of truth for which
model rows are embeddable knowledge for which agent role.

"Suitable for RAG" here means: a free-text customer problem description ranked
against a small, curated, APPROVED knowledge corpus (FAQEntry / GenericGuide /
SiteFAQ). Explicitly NOT suitable, and therefore never embedded:
  - manuals (MachineDocument) — served whole via a Gemini context cache
    (chat/context.py::machine_pdf_context); chunking/embedding them is the
    do-NOT-do #1 in docs/plans/2026-07-14-accuracy-research.md.
  - BrandNote / MachineNote — small, always injected in full for the bound
    machine's vendor (chat/context.py::collect_knowledge), never ranked, so
    there's nothing for an embedding to rank against.

Deterministic/contract roles (intake, router, summarizer, safety, qa) are
excluded outright: each is a fixed-shape decision the code already enforces,
and retrieval augmentation would only add hallucination surface for no
accuracy upside — this is the "only embed suitable information" half of the
owner's ask.

This is the ONE place role -> corpus scope is decided. build_embeddings reads
it to know what to embed; kb/semantic.py reads it to know what to rank
against; a later S9 agents-page tool registry should read get_corpus_for_role
too, rather than re-deriving this mapping a third time.
"""
from __future__ import annotations

from dataclasses import dataclass

# Top-level serviced-family category slugs (mirrors chat.orchestrator.SERVICED_FAMILIES).
SERVICED_FAMILIES = {"heat_pump", "water_pump_well", "water_filtration"}

_FAMILY_TO_GENERAL_ROLE = {
    "heat_pump": "heat_pump_specialist",
    "water_pump_well": "water_pump_specialist",
    "water_filtration": "water_filtration_specialist",
}


@dataclass(frozen=True)
class CorpusScope:
    role: str
    included: bool
    reason: str
    # Top-level family slug to scope FAQEntry/GenericGuide to, or None. For the two
    # roles where None occurs, the meaning differs by role (documented per-entry
    # below): intelligent_specialist's None means "no filter, rank all approved
    # rows"; specialist's None means "computed dynamically from the bound machine's
    # own category at call time" (chat/context.py handles that case specially).
    category_family: str | None = None


# One entry per AGENT_ROLE_CHOICES value (core/enums.py). Completeness (every role
# explicitly present) is asserted by tests/test_corpus_registry.py so a new role
# can't silently ship unscoped.
ROLE_CORPUS: dict[str, CorpusScope] = {
    "intake": CorpusScope(
        "intake", False,
        "deterministic slot-filling FSM step; no free-text answer to ground"),
    "router": CorpusScope(
        "router", False,
        "deterministic classification into a fixed enum; retrieval doesn't change the contract"),
    "specialist": CorpusScope(
        "specialist", True,
        "manual mode — approved FAQEntry/GenericGuide scoped to the bound machine's own "
        "category (resolved per-call from the machine, not a fixed family here); "
        "BrandNote/MachineNote for the vendor are injected directly and unranked, and the "
        "manual itself is never embedded — it's cached whole"),
    "intelligent_intake": CorpusScope(
        "intelligent_intake", False,
        "unsupported-equipment intake; no matched machine/category yet for anything to scope to"),
    "intelligent_specialist": CorpusScope(
        "intelligent_specialist", True,
        "no serviced-family match — ranks across ALL approved general knowledge (incl. SiteFAQ)",
        category_family=None),
    "heat_pump_specialist": CorpusScope(
        "heat_pump_specialist", True,
        "approved FAQEntry/GenericGuide scoped to the heat_pump family",
        category_family="heat_pump"),
    "water_pump_specialist": CorpusScope(
        "water_pump_specialist", True,
        "approved FAQEntry/GenericGuide scoped to the water_pump_well family",
        category_family="water_pump_well"),
    "water_filtration_specialist": CorpusScope(
        "water_filtration_specialist", True,
        "approved FAQEntry/GenericGuide scoped to the water_filtration family",
        category_family="water_filtration"),
    "summarizer": CorpusScope(
        "summarizer", False,
        "compresses this conversation's own transcript; no external knowledge lookup"),
    "safety": CorpusScope(
        "safety", False,
        "keyword/classifier guardrail backstop must stay deterministic, never augmented"),
    "qa": CorpusScope(
        "qa", False,
        "deterministic eval/assessment contract, not a customer-facing knowledge consumer"),
}


def get_corpus_for_role(role: str) -> CorpusScope:
    """The single source of truth for role -> corpus scope. Unknown roles fail
    closed (excluded) rather than silently ranking against an unscoped corpus."""
    return ROLE_CORPUS.get(
        role, CorpusScope(role, False, "role not declared in ROLE_CORPUS (fail-closed)"))


def family_ids(family_slug: str | None) -> list[int] | None:
    """A top-level category slug -> [category.id, *leaf-children ids]. None (or an
    unknown slug) = no filter. Mirrors chat.orchestrator._family_ids, kept
    independent since chat/orchestrator.py is out of scope for this change."""
    if not family_slug:
        return None
    from kb.models import Category
    cat = Category.objects.filter(slug=family_slug).first()
    if not cat:
        return None
    return [cat.id] + list(cat.children.values_list("id", flat=True))


def family_ids_for_category(cat) -> list[int] | None:
    """Family ids for a bound machine's category, which is usually a LEAF
    (water_to_water, air_to_water, ...), not a top-level family slug.

    family_ids() expands a family DOWNWARD; handed a leaf it returns just that leaf,
    which silently hid all category-level family knowledge from manual mode — e.g. a
    Geo 412C (water_to_water) could not see the approved heat-pump entry "Det droppar
    vatten vid värmepumpen. Är det normalt?" (ranked 0.844 unscoped, absent when
    scoped to the leaf), so the specialist answered from world knowledge at low
    confidence and escalated a benign case. Walk UP to the top-level family first,
    then expand, so system-level knowledge is visible while the machine's own manual
    still owns anything model-specific (spec §6 source order).
    """
    if cat is None:
        return None
    top = cat.parent if cat.parent_id else cat
    return [top.id] + list(top.children.values_list("id", flat=True))


def role_for_case(cs: dict, machine) -> str:
    """Independently derive the agent role for a case, for retrieval SCOPING only
    (chat/context.py). Mirrors chat.orchestrator._general_role/_category_family's
    logic exactly but is duplicated rather than imported, per the S10 file-ownership
    split that keeps chat/orchestrator.py untouched."""
    if machine is not None:
        return "specialist"
    from kb.models import Category
    family = None
    for slug in (cs.get("slots", {}).get("category"), cs.get("slots", {}).get("subtype")):
        if not slug:
            continue
        if slug in SERVICED_FAMILIES:
            family = slug
            break
        c = Category.objects.filter(slug=slug).select_related("parent").first()
        if c:
            if c.slug in SERVICED_FAMILIES:
                family = c.slug
                break
            if c.parent_id and c.parent.slug in SERVICED_FAMILIES:
                family = c.parent.slug
                break
    return _FAMILY_TO_GENERAL_ROLE.get(family, "intelligent_specialist")


def embeddable_rows(role: str):
    """Yield (source_model, pk, lang, text) for every row this role's corpus
    includes — the input to `build_embeddings`. Only FAQEntry/GenericGuide/SiteFAQ
    are ranked corpora; see the module docstring for what's deliberately excluded."""
    scope = get_corpus_for_role(role)
    if not scope.included:
        return
    from kb.models import FAQEntry, GenericGuide, SiteFAQ

    if role == "specialist":
        # Dynamic per-machine scoping is the caller's job (chat/context.py); the
        # management command embeds specialist rows per-machine-category via the
        # heat/water-pump/water-filtration family entries above, which already cover
        # every serviced category a machine can belong to. Nothing additional here.
        return

    cat_ids = family_ids(scope.category_family)  # None -> no filter (all approved)

    faq_qs = FAQEntry.objects.filter(is_approved=True)
    if cat_ids is not None:
        faq_qs = faq_qs.filter(category_id__in=cat_ids)
    for fa in faq_qs.prefetch_related("texts"):
        for t in fa.texts.all():
            blob = f"{t.question} {t.answer} {' '.join(str(k) for k in (fa.keywords or []))}".strip()
            if blob:
                yield ("FAQEntry", fa.pk, t.lang, blob)

    guide_qs = GenericGuide.objects.all()
    if cat_ids is not None:
        guide_qs = guide_qs.filter(category_id__in=cat_ids)
    for g in guide_qs:
        yield ("GenericGuide", g.pk, g.lang, f"[{g.kind}] {g.body}")

    # SiteFAQ is company-wide, not category-scoped — only relevant to the
    # family-agnostic intelligent_specialist (all-approved) scope.
    if cat_ids is None:
        for s in SiteFAQ.objects.filter(is_active=True, is_approved=True):
            yield ("SiteFAQ", s.pk, s.lang, f"Q: {s.question}\nA: {s.answer}")
