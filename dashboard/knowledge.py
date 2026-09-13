"""General Knowledge curation pages (owner's workbench): one page per category
family — Heat pumps, Water pumps & wells, Water filtration, plus Site/General
(SiteFAQ). Search/filter, approve toggle, full-metadata create/edit, delete.

FAQEntry.category is NOT nullable in the schema, so the Site page lists SiteFAQ
rows only (there is no such thing as a category-less FAQEntry)."""
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q, TextField
from django.db.models.functions import Cast
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from dashboard.forms import KnowledgeEntryForm, SiteFAQForm
from dashboard.views import _toast
from kb.models import Category, FAQEntry, SiteFAQ

# family slug (URL) -> root Category slug + staff-facing label. Order = tab order.
FAMILIES = {
    "heat-pump": {"root": "heat_pump", "label": "Värmepumpar"},
    "water-pump-well": {"root": "water_pump_well", "label": "Vattenpumpar & brunnar"},
    "water-filtration": {"root": "water_filtration", "label": "Vattenfiltrering"},
    "site": {"root": None, "label": "Webbplats / Allmänt"},
}

ONSETS = ["any", "sudden", "long_term"]


def _family_or_404(family: str) -> dict:
    if family not in FAMILIES:
        raise Http404
    return FAMILIES[family]


def _family_categories(root_slug: str) -> list[Category]:
    """Root category + all descendants (BFS — the tree is shallow but this stays
    correct if a leaf ever grows children)."""
    root = Category.objects.filter(slug=root_slug).first()
    if root is None:
        return []
    cats, frontier = [root], [root]
    while frontier:
        children = list(Category.objects.filter(parent__in=frontier))
        cats += children
        frontier = children
    return cats


def _tabs(active: str) -> list[dict]:
    return [{"slug": s, "label": cfg["label"], "active": s == active}
            for s, cfg in FAMILIES.items()]


def _list_ctx(request, family: str) -> dict:
    cfg = _family_or_404(family)
    q = (request.GET.get("q") or "").strip()
    subtype = (request.GET.get("subtype") or "").strip()
    onset = (request.GET.get("onset") or "").strip()
    status = (request.GET.get("status") or "").strip()

    ctx = {"family": family, "label": cfg["label"], "tabs": _tabs(family),
           "q": q, "subtype": subtype, "onset": onset, "status": status,
           "onsets": ONSETS, "is_site": family == "site",
           "entries": [], "site_faqs": [], "subtype_chips": []}

    if family == "site":
        base = SiteFAQ.objects.all()
        qs = base
        if q:
            qs = qs.filter(Q(question__icontains=q) | Q(answer__icontains=q))
        if status == "approved":
            qs = qs.filter(is_approved=True)
        elif status == "pending":
            qs = qs.filter(is_approved=False)
        ctx["site_faqs"] = list(qs.order_by("topic", "question"))
        ctx.update(total=base.count(),
                   approved_count=base.filter(is_approved=True).count(),
                   pending_count=base.filter(is_approved=False).count())
        return ctx

    cats = _family_categories(cfg["root"])
    ctx["subtype_chips"] = [c.slug for c in cats if c.parent_id]
    base = FAQEntry.objects.filter(category__in=cats)
    qs = base.select_related("category", "manufacturer").prefetch_related("texts")
    if q:
        qs = qs.annotate(kw_text=Cast("keywords", TextField())).filter(
            Q(texts__question__icontains=q) | Q(texts__answer__icontains=q)
            | Q(kw_text__icontains=q)).distinct()
    if subtype:
        qs = qs.filter(applicable_subtypes__contains=[subtype])
    if onset:
        qs = qs.filter(onset_type=onset)
    if status == "approved":
        qs = qs.filter(is_approved=True)
    elif status == "pending":
        qs = qs.filter(is_approved=False)
    entries = list(qs.order_by("category__name", "order", "id"))
    for e in entries:
        e.preview_text = e.text("sv") or e.text("en")
    ctx["entries"] = entries
    ctx.update(total=base.count(),
               approved_count=base.filter(is_approved=True).count(),
               pending_count=base.filter(is_approved=False).count())
    return ctx


@staff_member_required
def knowledge_index(request):
    return redirect("dash-knowledge", family="heat-pump")


@staff_member_required
def knowledge_page(request, family: str):
    ctx = _list_ctx(request, family)
    if request.headers.get("HX-Request"):
        return render(request, "dashboard/_knowledge_list.html", ctx)
    return render(request, "dashboard/knowledge.html", ctx)


def _form_kwargs(family_cfg):
    cats = _family_categories(family_cfg["root"])
    return {
        "family_categories": Category.objects.filter(pk__in=[c.pk for c in cats]).order_by("name"),
        "leaf_slugs": [c.slug for c in cats if c.parent_id],
    }


@staff_member_required
def knowledge_entry_new(request, family: str):
    cfg = _family_or_404(family)
    if family == "site":  # site rows are SiteFAQ — reuse the existing create page
        return redirect("dash-site-faq-new")
    kwargs = _form_kwargs(cfg)
    if request.method == "POST":
        form = KnowledgeEntryForm(request.POST, **kwargs)
        if form.is_valid():
            form.save()
            resp = redirect("dash-knowledge", family=family)
            resp["HX-Trigger"] = _toast("success", "Knowledge entry added.")
            return resp
    else:
        root = Category.objects.filter(slug=cfg["root"]).first()
        form = KnowledgeEntryForm(initial={"category": root.pk if root else None}, **kwargs)
    return render(request, "dashboard/knowledge_form.html", {
        "form": form, "family": family, "label": cfg["label"],
        "title": f"Ny post — {cfg['label']}", "entry": None})


def _family_for_category(category: Category) -> str:
    root = category
    while root.parent_id:
        root = root.parent
    for slug, cfg in FAMILIES.items():
        if cfg["root"] == root.slug:
            return slug
    return "heat-pump"


@staff_member_required
def knowledge_entry_edit(request, pk: int):
    entry = get_object_or_404(FAQEntry.objects.select_related("category__parent"), pk=pk)
    family = _family_for_category(entry.category)
    cfg = FAMILIES[family]
    kwargs = _form_kwargs(cfg)
    if request.method == "POST":
        form = KnowledgeEntryForm(request.POST, instance=entry, **kwargs)
        if form.is_valid():
            form.save()  # never flips is_approved
            resp = redirect(_next_url(request) or reverse("dash-knowledge", args=[family]))
            resp["HX-Trigger"] = _toast("success", "Knowledge entry updated.")
            return resp
    else:
        form = KnowledgeEntryForm(instance=entry, **kwargs)
    return render(request, "dashboard/knowledge_form.html", {
        "form": form, "family": family, "label": cfg["label"],
        "title": "Redigera post", "entry": entry})


def _next_url(request) -> str:
    """The ?next= path to return to after Save, or "" when there isn't a safe one.

    The FAQ approval queue links here with ?next=, so an edit made while reviewing pending
    entries returns to that queue instead of dumping the reviewer back in the knowledge
    list. Only same-site paths are honoured — an absolute URL from a crafted link would
    otherwise turn Save into an open redirect.
    """
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next") or request.GET.get("next") or ""
    ok = nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return nxt if ok else ""


@staff_member_required
def knowledge_site_edit(request, pk: int):
    faq = get_object_or_404(SiteFAQ, pk=pk)
    if request.method == "POST":
        form = SiteFAQForm(request.POST, instance=faq)
        if form.is_valid():
            form.save()  # is_approved not in the form — preserved
            resp = redirect(_next_url(request) or reverse("dash-knowledge", args=["site"]))
            resp["HX-Trigger"] = _toast("success", "Site FAQ updated.")
            return resp
    else:
        form = SiteFAQForm(instance=faq)
    return render(request, "dashboard/knowledge_form.html", {
        "form": form, "family": "site", "label": FAMILIES["site"]["label"],
        "title": "Redigera site-FAQ", "entry": faq})


def _kind_model(kind: str):
    model = {"entry": FAQEntry, "site": SiteFAQ}.get(kind)
    if model is None:
        raise Http404
    return model


def _list_response(request, toast_kind: str, message: str):
    family = request.GET.get("family") or "heat-pump"
    resp = render(request, "dashboard/_knowledge_list.html", _list_ctx(request, family))
    resp["HX-Trigger"] = _toast(toast_kind, message)
    return resp


@staff_member_required
@require_POST
def knowledge_toggle(request, kind: str, pk: int):
    obj = get_object_or_404(_kind_model(kind), pk=pk)
    obj.is_approved = not obj.is_approved
    obj.save(update_fields=["is_approved"])
    msg = "Approved — live in retrieval now ✓" if obj.is_approved else "Unapproved — hidden from retrieval."
    return _list_response(request, "success" if obj.is_approved else "info", msg)


@staff_member_required
@require_POST
def knowledge_delete(request, kind: str, pk: int):
    get_object_or_404(_kind_model(kind), pk=pk).delete()
    return _list_response(request, "info", "Entry deleted.")
