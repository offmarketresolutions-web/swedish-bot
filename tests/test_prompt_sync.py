"""Sync mechanics for moving owner-edited agent config between environments
(prod VPS <-> local dev): export/import round-trip, no-clobber seeding, drift
visibility. See docs/plans/2026-07-14-prompt-sync.md."""
import io
import json

import tempfile

import pytest
from django.core.management import call_command

from kb import models as m

pytestmark = pytest.mark.django_db


def _run(cmd, *args):
    out = io.StringIO()
    call_command(cmd, *args, stdout=out)
    return out.getvalue()


def _export_json():
    out = io.StringIO()
    call_command("export_agent_config", stdout=out)
    return json.loads(out.getvalue())


# -- no-clobber seeding -----------------------------------------------------

def test_seed_kb_does_not_overwrite_owner_edited_prompt():
    call_command("seed_kb")
    prompt = m.AgentPrompt.objects.get(role="router")
    prompt.body = "OWNER EDITED BODY"
    prompt.save()

    call_command("seed_kb")  # re-seed, as a redeploy would do

    prompt.refresh_from_db()
    assert prompt.body == "OWNER EDITED BODY"


def test_seed_kb_force_resets_prompt_to_code_default():
    call_command("seed_kb")
    prompt = m.AgentPrompt.objects.get(role="router")
    original_body = prompt.body
    prompt.body = "OWNER EDITED BODY"
    prompt.save()

    call_command("seed_kb", "--force")

    prompt.refresh_from_db()
    assert prompt.body == original_body


def test_seed_kb_does_not_overwrite_owner_edited_chip_label():
    call_command("seed_kb")
    chip = m.QuickReplyChip.objects.get(intake_step="category", value="heat_pump")
    text = chip.texts.get(lang="en")
    text.label = "Owner's Custom Label"
    text.save()

    call_command("seed_kb")

    text.refresh_from_db()
    assert text.label == "Owner's Custom Label"


def test_seed_kb_still_creates_missing_rows_without_force():
    call_command("seed_kb")
    m.AgentPrompt.objects.filter(role="summarizer").delete()

    call_command("seed_kb")

    assert m.AgentPrompt.objects.filter(role="summarizer").exists()


# -- export/import round trip -----------------------------------------------

def test_export_import_round_trip_is_a_no_op():
    call_command("seed_kb")
    data = _export_json()
    assert data["schema_version"] == 1
    assert len(data["agent_prompts"]) == m.AgentPrompt.objects.count()

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(data, fh)
        path = fh.name

    out = _run("import_agent_config", path)
    assert "No differences" in out


def test_import_dry_run_reports_diff_without_writing():
    call_command("seed_kb")
    data = _export_json()

    prompt = m.AgentPrompt.objects.get(role="router")
    prompt.body = "SOMETHING NEW ON THIS SIDE"
    prompt.save()

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(data, fh)
        path = fh.name

    out = _run("import_agent_config", path)  # dry-run (default)
    assert "router" in out
    assert "body" in out

    prompt.refresh_from_db()
    assert prompt.body == "SOMETHING NEW ON THIS SIDE"  # untouched — dry-run only


def test_import_prefer_file_applies_the_diff():
    call_command("seed_kb")
    data = _export_json()
    original_router_body = m.AgentPrompt.objects.get(role="router").body

    prompt = m.AgentPrompt.objects.get(role="router")
    prompt.body = "LOCAL DRIFTED BODY"
    prompt.save()

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(data, fh)
        path = fh.name

    _run("import_agent_config", path, "--prefer", "file")

    prompt.refresh_from_db()
    assert prompt.body == original_router_body


def test_import_never_deletes_rows_absent_from_file():
    call_command("seed_kb")
    data = _export_json()
    data["agent_prompts"] = [r for r in data["agent_prompts"] if r["role"] != "router"]

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(data, fh)
        path = fh.name

    _run("import_agent_config", path, "--prefer", "file")

    assert m.AgentPrompt.objects.filter(role="router").exists()


# -- drift visibility ---------------------------------------------------

def test_agent_config_diff_reports_no_drift_on_fresh_seed():
    call_command("seed_kb")
    out = _run("agent_config_diff")
    assert "No drift" in out


def test_agent_config_diff_reports_owner_edited_prompt():
    call_command("seed_kb")
    prompt = m.AgentPrompt.objects.get(role="specialist")
    prompt.body = "CUSTOM"
    prompt.save()

    out = _run("agent_config_diff")
    assert "specialist" in out
    assert "owner-edited" in out
