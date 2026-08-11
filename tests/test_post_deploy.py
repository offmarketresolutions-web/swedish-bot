"""Tests for the deploy hardening commands (selfcheck, post_deploy).

Covers: selfcheck passes on a fully-seeded DB; selfcheck fails (SystemExit(1))
when an AgentPrompt body is blanked; FormButton/GeoSettings gaps are WARN not
FAIL (owner go-live items, not code defects); post_deploy is idempotent
(running it twice creates no duplicate rows).
"""
from __future__ import annotations

import io

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _run_selfcheck():
    out = io.StringIO()
    try:
        call_command("selfcheck", stdout=out)
        code = 0
    except SystemExit as e:
        code = e.code
    return code, out.getvalue()


def _seed_full():
    """seed_kb() + PostcodeArea, plus a stopgap AgentPrompt for the "qa" role —
    kb/seed_prompts.py (kb/ logic, out of scope for this deploy-hardening pass)
    doesn't seed it yet, but AGENT_ROLE_CHOICES already lists it. Fill it here so
    tests describe the target fully-seeded state rather than baking in the gap."""
    call_command("seed_kb")
    from crm.models import PostcodeArea
    PostcodeArea.objects.create(code="12345", lat=59.0, lng=18.0)
    from kb.models import AgentPrompt
    AgentPrompt.objects.get_or_create(
        role="qa", defaults={"body": "placeholder qa prompt", "is_active": True})


def test_selfcheck_passes_on_fully_seeded_db():
    _seed_full()

    code, output = _run_selfcheck()

    assert code == 0, output
    assert "PASS" in output


def test_selfcheck_fails_when_agentprompt_body_blanked():
    _seed_full()

    from kb.models import AgentPrompt
    prompt = AgentPrompt.objects.first()
    prompt.body = ""
    prompt.save()

    code, output = _run_selfcheck()

    assert code == 1
    assert "FAIL" in output


def test_selfcheck_fails_when_no_migrations_pending_but_no_vendor():
    _seed_full()

    from kb.models import Vendor
    Vendor.objects.all().delete()

    code, output = _run_selfcheck()

    assert code == 1
    assert "FAIL" in output


def test_selfcheck_warns_not_fails_on_unconfigured_formbutton_and_geosettings():
    _seed_full()

    # FormButton/GeoSettings are untouched (empty) -> should be WARN, not FAIL.
    code, output = _run_selfcheck()

    assert code == 0, output
    assert "WARN" in output


def test_selfcheck_fails_when_agentprompt_role_inactive():
    """A role with a non-blank body but is_active=False passes prompts.get_agent's
    filter into oblivion (returns None), so chat.prompts.render() falls back to an
    unguided system instruction. selfcheck must FAIL this, not silently PASS it."""
    _seed_full()

    from kb.models import AgentPrompt
    prompt = AgentPrompt.objects.filter(role="specialist").first()
    prompt.is_active = False
    prompt.save()

    code, output = _run_selfcheck()

    assert code == 1
    assert "FAIL" in output


def test_post_deploy_idempotent_no_dupes():
    call_command("post_deploy", skip_selfcheck=True)

    from kb.models import AgentPrompt, Category, Vendor
    from crm.models import ServiceArea

    counts_1 = {
        "prompts": AgentPrompt.objects.count(),
        "categories": Category.objects.count(),
        "vendors": Vendor.objects.count(),
        "service_areas": ServiceArea.objects.count(),
    }

    call_command("post_deploy", skip_selfcheck=True)

    counts_2 = {
        "prompts": AgentPrompt.objects.count(),
        "categories": Category.objects.count(),
        "vendors": Vendor.objects.count(),
        "service_areas": ServiceArea.objects.count(),
    }

    assert counts_1 == counts_2


def _make_form_buttons(*, url: str):
    """Create the 4 category rows the dashboard auto-creates on first settings load.
    seed_kb does NOT create them, so a test that merely .update()s would silently
    touch zero rows and assert against an empty table instead of the real state."""
    from crm.models import FormButton
    for slug, label in FormButton.CATEGORY:
        FormButton.objects.update_or_create(
            category_slug=slug, defaults={"label": label, "url": url, "is_active": True})
    assert FormButton.objects.filter(is_active=True).count() == len(FormButton.CATEGORY)


def test_selfcheck_reports_blank_form_button_urls_as_not_ready():
    """A FormButton row with a blank url never renders a chip (form_chip_for returns
    None rather than serve a dead link), so counting ACTIVE ROWS alone reported a
    green 4/4 while the feature was entirely off. The line must report the url-filled
    count, so 'ready' means a customer can actually get the form."""
    _seed_full()
    _make_form_buttons(url="")

    code, output = _run_selfcheck()

    line = next(ln for ln in output.splitlines() if "FormButton" in ln)
    assert "WARN" in line, line
    assert "0/4 with a url" in line, line
    assert code == 0, "a blank url is an owner go-live item, never a hard deploy failure"


def test_selfcheck_form_buttons_ready_when_urls_filled():
    _seed_full()
    _make_form_buttons(url="https://nordlandvvs.se/service")

    _, output = _run_selfcheck()

    line = next(ln for ln in output.splitlines() if "FormButton" in ln)
    assert "PASS" in line, line
