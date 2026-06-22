"""Analytics aggregations (crm/analytics.py) over a known fixture dataset."""
import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def data():
    from chat.models import Conversation
    from crm.models import Customer, LeadDelivery, ServiceRequest, Session
    from kb.models import Category, Machine, Vendor

    v = Vendor.objects.create(name="IVT", slug="ivt")
    cat = Category.objects.create(name="Ground source", slug="water_to_water", group="heat")
    m = Machine.objects.create(vendor=v, category=cat, model_name="Geo 600C", slug="geo-600c")
    cust = Customer.objects.create(name="Sven", phone="0701234567", consent_to_contact=True)

    def sess(**kw):
        return Session.objects.create(conversation=Conversation.objects.create(), **kw)

    sess(customer=cust, machine=m, category=cat, severity="normal", resolved=True,
         status="resolved", decision="solve", reply_turns=3, confidence_score=0.9,
         manufacturer="IVT", model="Geo 600C")
    s2 = sess(customer=cust, machine=m, category=cat, severity="urgent", status="escalated",
              decision="escalate", reply_turns=4, service_recommended=True,
              manufacturer="IVT", model="Geo 600C")
    sess(machine=m, category=cat, severity="service", status="active", reply_turns=2)
    sr = ServiceRequest.objects.create(session=s2, idempotency_key="k1")
    LeadDelivery.objects.create(service_request=sr, sink="db", status="success")
    LeadDelivery.objects.create(service_request=sr, sink="email", status="failed")
    return {"v": v, "m": m, "cust": cust}


def test_kpis(data):
    from crm import analytics as A
    k = A.kpis()
    assert k["total"] == 3 and k["resolved"] == 1 and k["escalated"] == 1
    assert k["resolution_rate"] == round(1 / 3, 4)
    assert k["escalation_rate"] == round(1 / 3, 4)
    assert k["leads_captured"] == 1 and k["sessions_with_lead"] == 1
    assert k["lead_capture_rate"] == round(1 / 3, 4)
    assert k["avg_turns"] == round((3 + 4 + 2) / 3, 1)


def test_contacts(data):
    from crm import analytics as A
    c = A.contact_stats()
    assert c["total_customers"] == 1
    assert c["returning_customers"] == 1            # 2 sessions → returning
    assert c["customers_contacted"] == 1
    assert c["consented"] == 1


def test_lead_health(data):
    from crm import analytics as A
    lh = A.lead_health()
    assert lh["requests"] == 1 and lh["deliveries"] == 2
    assert lh["by_status"].get("success") == 1 and lh["failed"] == 1
    assert lh["delivery_success_rate"] == round(1 / 2, 4)


def test_breakdowns(data):
    from crm import analytics as A
    b = A.breakdowns()
    assert {"category__group": "heat", "n": 3} in b["by_group"]
    sev = {r["severity"]: r["n"] for r in b["by_severity"]}
    assert sev == {"normal": 1, "urgent": 1, "service": 1}
    top = b["top_machines"][0]
    assert top["machine__model_name"] == "Geo 600C" and top["n"] == 3 and top["resolved"] == 1


def test_trend(data):
    from crm import analytics as A
    t = A.trend(7)
    assert len(t) == 7
    assert sum(d["sessions"] for d in t) == 3      # all created today
    assert sum(d["resolved"] for d in t) == 1


def test_success_metrics(data):
    from crm import analytics as A
    s = A.success_metrics()
    assert {m["key"] for m in s} == {"resolution_rate", "deflection_rate",
                                     "lead_capture_rate", "returning_rate", "delivery_success_rate"}
    by = {m["key"]: m for m in s}
    assert by["returning_rate"]["value"] == 1.0 and by["returning_rate"]["met"] is True


def test_deflection_excludes_escalated(data):
    # A session resolved=True BUT escalated must NOT count as deflection (solved w/o human).
    from chat.models import Conversation
    from crm.models import Session
    from crm import analytics as A
    Session.objects.create(conversation=Conversation.objects.create(),
                           resolved=True, status="escalated")
    k = A.kpis()
    assert k["resolved"] == 2            # both resolved sessions
    assert k["deflected"] == 1           # only the non-escalated one is deflection
    assert k["deflection_rate"] < k["resolution_rate"]


def test_trend_no_double_count_multi_servicerequest(data):
    # A session with 2 ServiceRequests must count once in the daily trend (JOIN fan-out).
    from chat.models import Conversation
    from crm.models import Session, ServiceRequest
    from crm import analytics as A
    s = Session.objects.create(conversation=Conversation.objects.create(),
                               resolved=True, status="resolved")
    ServiceRequest.objects.create(session=s, idempotency_key="m1")
    ServiceRequest.objects.create(session=s, idempotency_key="m2")
    t = A.trend(2)
    # base fixture: 3 sessions (1 resolved, s2 has 1 SR) + this 1 resolved 2-SR session.
    # Without distinct the 2-SR session would inflate to 2 → sessions=5; the fix keeps it 1.
    assert sum(d["sessions"] for d in t) == 4    # 4 not 5 → no JOIN double-count
    assert sum(d["resolved"] for d in t) == 2
    assert sum(d["leads"] for d in t) == 2       # s2 + this session, each counted once


def test_entity_stats(data):
    from crm import analytics as A
    vs = A.vendor_stats(data["v"])
    assert vs["total"] == 3 and "by_severity" in vs and "top_machines" in vs
    ms = A.machine_stats(data["m"])
    assert ms["total"] == 3 and "by_problem" in ms
    cs = A.customer_stats(data["cust"])
    assert cs["total"] == 2 and cs["is_returning"] is True and cs["last_contact"] is not None
