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
