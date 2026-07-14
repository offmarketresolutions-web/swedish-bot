"""/api/prefill/<token> + chat.prefill helpers (plan S6/D2)."""
import pytest
from django.core import signing
from django.core.cache import cache

from chat.models import Conversation
from chat.prefill import build_form_url, make_prefill_token, read_prefill_token
from crm.models import Customer, Session

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_session(**kwargs):
    conv = Conversation.objects.create(language="sv")
    return Session.objects.create(conversation=conv, **kwargs)


def test_make_and_read_prefill_token_round_trip():
    session = _make_session(manufacturer="IVT", model="490")
    token = make_prefill_token(session)
    assert read_prefill_token(token) == session.pk


def test_read_prefill_token_rejects_bad_signature():
    assert read_prefill_token("not-a-real-token") is None


def test_read_prefill_token_rejects_expired():
    session = _make_session()
    token = make_prefill_token(session)
    # sign.dumps embeds a timestamp; a negative max_age is always in the past.
    assert read_prefill_token(token, max_age=-1) is None


def test_build_form_url_appends_token_param():
    session = _make_session()
    url = build_form_url("https://www.nordlandvvs.se/kontakt", session)
    assert url.startswith("https://www.nordlandvvs.se/kontakt?nl_case=")
    token = url.split("nl_case=", 1)[1]
    assert read_prefill_token(token) == session.pk


def test_build_form_url_preserves_existing_query_string():
    session = _make_session()
    url = build_form_url("https://x.test/f?utm=1", session)
    assert "?utm=1&nl_case=" in url


def test_prefill_endpoint_returns_technical_fields():
    session = _make_session(manufacturer="IVT", model="490", error_code="E12",
                             postal_code="87231", onset="sudden")
    token = make_prefill_token(session)
    resp = _client_get(f"/api/prefill/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["technical"]["brand"] == "IVT"
    assert body["technical"]["model"] == "490"
    assert body["technical"]["error_code"] == "E12"
    assert body["technical"]["postal_code"] == "87231"
    assert body["technical"]["onset"] == "sudden"
    assert "contact" not in body  # no customer linked


def test_prefill_endpoint_omits_contact_without_consent():
    customer = Customer.objects.create(name="Anna", phone="0701234567", consent_to_contact=False)
    session = _make_session(customer=customer)
    token = make_prefill_token(session)
    resp = _client_get(f"/api/prefill/{token}")
    assert "contact" not in resp.json()


def test_prefill_endpoint_includes_contact_with_consent():
    customer = Customer.objects.create(name="Anna", phone="0701234567", email="a@x.se",
                                        address="Storgatan 1", consent_to_contact=True)
    session = _make_session(customer=customer)
    token = make_prefill_token(session)
    resp = _client_get(f"/api/prefill/{token}")
    body = resp.json()
    assert body["contact"] == {"name": "Anna", "phone": "0701234567", "email": "a@x.se",
                                "address": "Storgatan 1"}


def test_prefill_endpoint_derives_problem_and_alarm_from_case_state():
    conv = Conversation.objects.create(
        language="sv", case_state={"slots": {"problem": "Ingen värme sedan igår", "alarm_text": "E12 blinkar"}})
    session = Session.objects.create(conversation=conv)
    token = make_prefill_token(session)
    resp = _client_get(f"/api/prefill/{token}")
    body = resp.json()
    assert body["technical"]["problem"] == "Ingen värme sedan igår"
    assert body["technical"]["alarm_text"] == "E12 blinkar"


def test_prefill_endpoint_includes_service_area_when_known():
    session = _make_session(service_area_status="inside", service_area_name="Umeå")
    token = make_prefill_token(session)
    resp = _client_get(f"/api/prefill/{token}")
    body = resp.json()
    assert body["technical"]["service_area"] == {"name": "Umeå", "status": "inside"}


def test_prefill_endpoint_omits_service_area_when_unknown():
    session = _make_session()
    token = make_prefill_token(session)
    resp = _client_get(f"/api/prefill/{token}")
    body = resp.json()
    assert body["technical"]["service_area"] is None


def test_prefill_endpoint_404s_on_invalid_token():
    resp = _client_get("/api/prefill/garbage-token")
    assert resp.status_code == 404


def test_prefill_endpoint_404s_on_missing_session():
    token = signing.dumps({"sid": 999999}, salt="prefill")
    resp = _client_get(f"/api/prefill/{token}")
    assert resp.status_code == 404


def test_prefill_endpoint_is_rate_limited(settings):
    settings.RATE_LIMIT_PREFILL = 1
    session = _make_session()
    token = make_prefill_token(session)
    first = _client_get(f"/api/prefill/{token}")
    second = _client_get(f"/api/prefill/{token}")
    assert first.status_code == 200
    assert second.status_code == 429


def test_prefill_endpoint_sets_cors_header(settings):
    settings.PREFILL_ALLOWED_ORIGIN = "https://www.nordlandvvs.se"
    session = _make_session()
    token = make_prefill_token(session)
    resp = _client_get(f"/api/prefill/{token}")
    assert resp["Access-Control-Allow-Origin"] == "https://www.nordlandvvs.se"


def _client_get(path):
    from django.test import Client
    return Client().get(path)
