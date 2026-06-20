"""Staff dashboard (plan §9): monitor every session, drill into transcripts +
AI summary + editable reporting fields, and see lead delivery status."""
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from core.enums import SEVERITY_CHOICES
from crm.models import Session

_EDITABLE = ["severity", "ai_summary"]
_BOOL_EDITABLE = ["resolved", "service_recommended", "booking_requested"]


@staff_member_required
def overview(request):
    qs = Session.objects.all()
    ctx = {
        "total": qs.count(),
        "escalated": qs.filter(status="escalated").count(),
        "resolved": qs.filter(resolved=True).count(),
        "leads": qs.filter(service_recommended=True).count(),
        "by_severity": list(qs.exclude(severity="").values("severity").annotate(n=Count("id")).order_by("-n")),
        "by_category": list(qs.exclude(category__isnull=True).values("category__name").annotate(n=Count("id")).order_by("-n")),
        "by_brand": list(qs.exclude(manufacturer="").values("manufacturer").annotate(n=Count("id")).order_by("-n")[:10]),
    }
    return render(request, "dashboard/overview.html", ctx)


@staff_member_required
def session_list(request):
    qs = Session.objects.select_related("customer", "machine", "category").order_by("-created_at")
    severity = request.GET.get("severity", "")
    status = request.GET.get("status", "")
    if severity:
        qs = qs.filter(severity=severity)
    if status:
        qs = qs.filter(status=status)
    return render(request, "dashboard/session_list.html", {
        "sessions": qs[:200], "severity": severity, "status": status,
        "severities": [s[0] for s in SEVERITY_CHOICES],
    })


@staff_member_required
def session_detail(request, pk: int):
    session = get_object_or_404(Session.objects.select_related("customer", "machine", "conversation"), pk=pk)
    if request.method == "POST":
        for f in _EDITABLE:
            if f in request.POST:
                setattr(session, f, request.POST[f])
        for f in _BOOL_EDITABLE:
            setattr(session, f, request.POST.get(f) == "on")
        session.save()
        return redirect("dash-session", pk=pk)
    messages = session.conversation.messages.all() if session.conversation_id else []
    deliveries = []
    for sr in session.service_requests.all():
        deliveries += list(sr.deliveries.all())
    return render(request, "dashboard/session_detail.html", {
        "session": session, "messages": messages, "deliveries": deliveries,
        "severities": [s[0] for s in SEVERITY_CHOICES],
    })
