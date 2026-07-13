"""E2E harness (real browser, live Gemini, real dev DB).

This suite is deliberately kept OUT of the default `uv run pytest` run: every test
is marked BOTH `e2e` and `live`, and the project addopts is `-m 'not live'`, so a
normal run skips it. Opt in with:

    uv run pytest -m e2e tests/e2e -s

It boots a real Django dev server on port 8077 against the dev `nordland` DB
(NOT the eval `eval_nordland` DB), drives Chromium via Playwright, and asserts
against the live DB through pytest-django's db blocker (no test DB is created —
these tests never request the `db` fixture, so `settings.DATABASES` stays pinned
to `nordland`, the same DB the server uses).
"""
from __future__ import annotations

import os

# Playwright's sync API runs the test body inside a greenlet event loop, which trips
# Django's "SynchronousOnlyOperation" guard on ORM calls. This suite talks to the real
# dev DB synchronously (never truly async), so opt out of the guard for the harness.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_PY = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
HOST = "127.0.0.1"
PORT = 8077
BASE_URL = f"http://{HOST}:{PORT}"
SHOT_DIR = PROJECT_ROOT / "docs" / "evals" / "2026-07-13-e2e"
SERVER_LOG = SHOT_DIR / "server.log"

E2E_ADMIN_USER = "e2e_admin"
E2E_ADMIN_PASS = "e2e-pass-2026"


def _server_up() -> bool:
    """Server is 'up' if it returns ANY HTTP response. We probe /admin/login/ (cheap,
    no Gemini) rather than /healthz — the latter does a LIVE Gemini ping that can hang
    for many seconds while the concurrent eval saturates Vertex, which would starve the
    readiness poll. Any HTTP status (even a redirect/4xx) proves the socket is serving."""
    try:
        with urllib.request.urlopen(f"{BASE_URL}/admin/login/", timeout=5):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001 — connection refused / not listening yet
        return False


@pytest.fixture(scope="session", autouse=True)
def dev_server():
    """Boot `manage.py runserver` on the dev DB, wait until it serves, tear down at end."""
    if _server_up():
        # A server is already listening on 8077 — reuse it, don't double-bind.
        yield BASE_URL
        return

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    log = open(SERVER_LOG, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(VENV_PY), "manage.py", "runserver", f"{HOST}:{PORT}", "--noreload"],
        cwd=str(PROJECT_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            if proc.poll() is not None:
                log.flush()
                raise RuntimeError(f"runserver exited early; see {SERVER_LOG}")
            if _server_up():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"runserver did not become healthy; see {SERVER_LOG}")
        yield BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture(scope="session")
def orm(django_db_blocker):
    """Access the REAL dev DB from the test process (no test DB is created for this
    suite). Use as: `with orm.unblock(): ServiceRequest.objects.count()`."""
    return django_db_blocker


@pytest.fixture(scope="session", autouse=True)
def e2e_seed(orm):
    """Idempotently seed the fixtures the browser tests need in the dev DB:
    an E2E superuser (for the login form) and a customer whose session is linked to
    a machine that has an uploaded document (so the customer-detail 'docs' tab shows
    the machine-documentation modal)."""
    from django.conf import settings
    assert settings.DATABASES["default"]["NAME"] == "nordland", (
        "E2E must run against the dev 'nordland' DB, got "
        f"{settings.DATABASES['default']['NAME']!r}")

    with orm.unblock():
        from django.contrib.auth.models import User

        from chat.models import Conversation
        from crm.models import Customer, Session
        from kb.models import Machine, MachineDocument

        u, _ = User.objects.get_or_create(
            username=E2E_ADMIN_USER,
            defaults={"is_staff": True, "is_superuser": True, "is_active": True},
        )
        u.is_staff = u.is_superuser = u.is_active = True
        u.set_password(E2E_ADMIN_PASS)
        u.save()

        # A machine that actually has a parsed document -> the doc modal has content.
        doc = MachineDocument.objects.select_related("machine__vendor").first()
        machine = doc.machine if doc else Machine.objects.first()

        cust, created = Customer.objects.get_or_create(
            name="E2E Testkund",
            defaults={"phone": "+46700000001", "email": "e2e@example.se",
                      "postal_code": "11152", "consent_to_contact": True},
        )
        if not cust.sessions.filter(machine=machine).exists():
            conv = Conversation.objects.create(language="sv")
            Session.objects.create(
                conversation=conv, customer=cust, machine=machine,
                manufacturer=machine.vendor.name, model=machine.model_name,
                severity="normal", ai_summary="E2E seed session for doc-modal coverage.",
            )
        seed = {"customer_id": cust.pk, "machine_id": machine.pk,
                "machine_label": f"{machine.vendor.name} {machine.model_name}"}
    return seed


# ── Playwright plumbing ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def _play():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(_play):
    b = _play.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(locale="sv-SE")
    ctx.set_default_timeout(15_000)
    pg = ctx.new_page()
    yield pg
    ctx.close()


def shot(page, name: str):
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / name
    page.screenshot(path=str(path), full_page=False)
    return path
