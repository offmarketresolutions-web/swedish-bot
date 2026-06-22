"""Live test console + local demo open-admin (DEMO_OPEN_ADMIN)."""
import pytest
from django.contrib.auth.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser():
    return User.objects.create_superuser("root", "root@x.se", "x")


# ── open-admin middleware ─────────────────────────────────────────────
def test_dashboard_requires_login_by_default(client, settings):
    settings.DEMO_OPEN_ADMIN = False
    resp = client.get("/dashboard/")
    assert resp.status_code == 302 and "login" in resp.headers["Location"]


def test_demo_open_admin_bypasses_login(client, settings, superuser):
    settings.DEMO_OPEN_ADMIN = True
    resp = client.get("/dashboard/")
    assert resp.status_code == 200  # auto-logged-in as the superuser
    assert b"Overview" in resp.content


def test_demo_open_admin_noop_without_superuser(client, settings):
    settings.DEMO_OPEN_ADMIN = True  # no superuser exists → still gated
    resp = client.get("/dashboard/")
    assert resp.status_code == 302


# ── playground page gating ────────────────────────────────────────────
def test_playground_hidden_in_prod(client, settings):
    settings.DEMO_OPEN_ADMIN = False
    settings.DEBUG = False
    assert client.get("/playground").status_code == 404


def test_playground_available_in_demo(client, settings, superuser):
    settings.DEMO_OPEN_ADMIN = True
    resp = client.get("/playground")
    assert resp.status_code == 200
    assert b"Live Test Console" in resp.content
    assert b"One-click scenarios" in resp.content


# ── debug internals only exposed in demo/DEBUG ────────────────────────
def _last_message_frame(content):
    import json
    frames = [json.loads(line[6:]) for line in content.decode().splitlines()
              if line.startswith("data: ")]
    return next(f for f in frames if f.get("type") == "message")


def test_sse_includes_debug_in_demo(client, settings, seeded_min, mock_gemini):
    settings.DEMO_OPEN_ADMIN = True
    pid = client.post("/api/chat/session", data="{}", content_type="application/json").json()["public_id"]
    resp = client.post(f"/api/chat/{pid}/message", data='{"message":"heat_pump"}',
                       content_type="application/json")
    frame = _last_message_frame(b"".join(resp.streaming_content))
    assert "debug" in frame and "state" in frame["debug"]


def test_sse_omits_debug_in_prod(client, settings, seeded_min, mock_gemini):
    settings.DEMO_OPEN_ADMIN = False
    settings.DEBUG = False
    pid = client.post("/api/chat/session", data="{}", content_type="application/json").json()["public_id"]
    resp = client.post(f"/api/chat/{pid}/message", data='{"message":"heat_pump"}',
                       content_type="application/json")
    frame = _last_message_frame(b"".join(resp.streaming_content))
    assert "debug" not in frame


@pytest.fixture
def seeded_min():
    from django.core.management import call_command
    call_command("seed_kb")
