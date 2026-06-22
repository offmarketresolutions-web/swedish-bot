"""Read-only analytics over crm.Session + leads + customers (plan §9 — "which
products & problems cost the most support").

METRIC TAXONOMY (standard support-bot KPIs; each rate is a fraction in [0,1]):

  Volume        conversations (sessions), unique customers, leads captured.
  SUCCESS TRIGGERS (a session counts toward a success metric when it hits one):
    solution        resolved is True                          → the bot solved it
    deflection      resolved is True (no human needed)         → containment
    lead_captured   a ServiceRequest exists for the session    → qualified hand-off
    booking         booking_requested is True
  Rates         resolution_rate, deflection_rate, escalation_rate,
                lead_capture_rate, booking_rate, lead_delivery_success_rate.
  Returning     customers with >= 2 sessions (repeat contact).
  Efficiency    avg reply turns, avg identification confidence.
  Breakdowns    by category-group / severity / decision / status / vendor /
                top machines / problem.
  Trend         sessions + resolved + leads per day over a window.

Everything here is pure aggregation — no writes, safe to call from any view.
"""
from __future__ import annotations

import datetime

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from crm.models import Customer, LeadDelivery, ServiceRequest, Session


def _pct(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def kpis(qs=None) -> dict:
    """Headline KPIs over a Session queryset (default: all sessions)."""
    qs = Session.objects.all() if qs is None else qs
    total = qs.count()
    resolved = qs.filter(resolved=True).count()
    escalated = qs.filter(status="escalated").count()
    service = qs.filter(service_recommended=True).count()
    booking = qs.filter(booking_requested=True).count()
    deflected = qs.filter(resolved=True).exclude(status="escalated").count()  # solved, no human
    leads = ServiceRequest.objects.filter(session__in=qs).count()
    sessions_with_lead = qs.filter(service_requests__isnull=False).distinct().count()
    agg = qs.aggregate(turns=Avg("reply_turns"),
                       conf=Avg("confidence_score"))
    return {
        "total": total,
        "resolved": resolved,
        "escalated": escalated,
        "service_recommended": service,
        "bookings": booking,
        "leads_captured": leads,
        "sessions_with_lead": sessions_with_lead,
        "deflected": deflected,
        "resolution_rate": _pct(resolved, total),       # solved
        "deflection_rate": _pct(deflected, total),      # solved WITHOUT escalating to a human
        "escalation_rate": _pct(escalated, total),
        "lead_capture_rate": _pct(sessions_with_lead, total),
        "booking_rate": _pct(booking, total),
        "avg_turns": round(agg["turns"] or 0, 1),
        "avg_confidence": round(agg["conf"] or 0, 2),
    }


def contact_stats() -> dict:
    """Contacts made + returning customers (company-wide)."""
    total_customers = Customer.objects.count()
    returning = (Customer.objects.annotate(n=Count("sessions"))
                 .filter(n__gte=2).count())
    contacted = (Customer.objects
                 .filter(Q(sessions__service_recommended=True)
                         | Q(sessions__service_requests__isnull=False))
                 .distinct().count())
    consented = Customer.objects.filter(consent_to_contact=True).count()
    return {
        "total_customers": total_customers,
        "returning_customers": returning,
        "returning_rate": _pct(returning, total_customers),
        "customers_contacted": contacted,
        "consented": consented,
    }


def lead_health() -> dict:
    """Lead-delivery pipeline health (how reliably leads reach Nordland)."""
    deliveries = LeadDelivery.objects.all()
    total = deliveries.count()
    by_status = {row["status"]: row["n"] for row in
                 deliveries.values("status").annotate(n=Count("id"))}
    by_sink = list(deliveries.values("sink", "status").annotate(n=Count("id")).order_by("sink"))
    success = by_status.get("success", 0)
    return {
        "requests": ServiceRequest.objects.count(),
        "deliveries": total,
        "by_status": by_status,
        "by_sink": by_sink,
        "delivery_success_rate": _pct(success, total),
        "failed": by_status.get("failed", 0),
        "pending": by_status.get("pending", 0),
    }


def breakdowns(qs=None) -> dict:
    qs = Session.objects.all() if qs is None else qs

    def grp(field, label_field=None, limit=None):
        rows = (qs.exclude(**{f"{field}__isnull": True}) if "__" in field or field.endswith("_id")
                else qs.exclude(**{field: ""}))
        rows = rows.values(label_field or field).annotate(n=Count("id")).order_by("-n")
        return list(rows[:limit] if limit else rows)

    return {
        "by_group": list(qs.exclude(category__isnull=True)
                         .values("category__group").annotate(n=Count("id")).order_by("-n")),
        "by_severity": grp("severity"),
        "by_decision": grp("decision"),
        "by_status": list(qs.values("status").annotate(n=Count("id")).order_by("-n")),
        "by_vendor": list(qs.exclude(machine__isnull=True)
                          .values("machine__vendor__name").annotate(n=Count("id")).order_by("-n")[:10]),
        "top_machines": list(qs.exclude(machine__isnull=True)
                             .values("machine__id", "machine__model_name", "machine__vendor__name")
                             .annotate(n=Count("id"),
                                       resolved=Count("id", filter=Q(resolved=True)))
                             .order_by("-n")[:10]),
        "by_problem": list(qs.exclude(problem_category__isnull=True)
                           .values("problem_category__label").annotate(n=Count("id")).order_by("-n")[:10]),
    }


def trend(days: int = 30) -> list[dict]:
    """Daily sessions / resolved / leads over the last `days` (gap-filled)."""
    # Use the active-tz local date so the window matches TruncDate's local-tz
    # bucketing (mixing UTC .date() with local TruncDate drops day-boundary rows).
    start = timezone.localdate() - datetime.timedelta(days=days - 1)
    rows = (Session.objects.filter(created_at__date__gte=start)
            .annotate(d=TruncDate("created_at")).values("d")
            .annotate(sessions=Count("id", distinct=True),  # distinct: the SR join fans out rows
                      resolved=Count("id", filter=Q(resolved=True), distinct=True),
                      leads=Count("id", filter=Q(service_requests__isnull=False), distinct=True))
            .order_by("d"))
    by_day = {r["d"]: r for r in rows}
    out = []
    for i in range(days):
        day = start + datetime.timedelta(days=i)
        r = by_day.get(day)
        out.append({"date": day.isoformat(),
                    "sessions": r["sessions"] if r else 0,
                    "resolved": r["resolved"] if r else 0,
                    "leads": r["leads"] if r else 0})
    return out


# ── Success scoreboard (metrics + targets) ─────────────────────────────────────
# Targets are sensible defaults for a triage support bot; tune as the data matures.
TARGETS = {
    "resolution_rate": 0.55,
    "deflection_rate": 0.50,
    "lead_capture_rate": 0.25,
    "returning_rate": 0.20,
    "delivery_success_rate": 0.95,
}


def success_metrics(k=None, c=None, lh=None) -> list[dict]:
    """Scoreboard: each success metric with its value, target, and met/below flag.
    Pass already-computed dicts (dashboard_context does) to avoid recomputing them."""
    k = k if k is not None else kpis()
    c = c if c is not None else contact_stats()
    lh = lh if lh is not None else lead_health()
    src = {**k, **c, **lh}
    labels = {
        "resolution_rate": "Resolution rate",
        "deflection_rate": "Deflection (solved without a human)",
        "lead_capture_rate": "Lead capture rate",
        "returning_rate": "Returning customers",
        "delivery_success_rate": "Lead delivery success",
    }
    out = []
    for key, target in TARGETS.items():
        val = src.get(key, 0.0)
        out.append({"key": key, "label": labels[key], "value": val,
                    "target": target, "met": val >= target})
    return out


# ── Per-entity stats (for the brand / machine / customer pages) ────────────────

def vendor_stats(vendor) -> dict:
    qs = Session.objects.filter(Q(machine__vendor=vendor) | Q(manufacturer__iexact=vendor.name))
    out = kpis(qs)
    b = breakdowns(qs)  # compute once
    out["by_severity"] = b["by_severity"]
    out["top_machines"] = b["top_machines"]
    return out


def machine_stats(machine) -> dict:
    qs = Session.objects.filter(machine=machine)
    out = kpis(qs)
    out["by_problem"] = breakdowns(qs)["by_problem"]
    return out


def customer_stats(customer) -> dict:
    qs = Session.objects.filter(customer=customer)
    out = kpis(qs)
    last = qs.order_by("-created_at").values_list("created_at", flat=True).first()
    out["is_returning"] = qs.count() >= 2
    out["last_contact"] = last
    out["files"] = customer.files.count()
    return out


def dashboard_context(trend_days: int = 30) -> dict:
    """One call for the analytics page (each aggregate computed once)."""
    k, c, lh = kpis(), contact_stats(), lead_health()
    return {
        "kpis": k,
        "contacts": c,
        "lead_health": lh,
        "breakdowns": breakdowns(),
        "trend": trend(trend_days),
        "success": success_metrics(k, c, lh),
        "trend_days": trend_days,
    }
