# Prompt/config version drift — sync mechanics (2026-07-14)

## Access check (done first)

No SSH alias for the VPS exists on this machine: `~/.ssh/config` has no entry and
`~/.ssh/known_hosts` has no `nordland` host. `DEPLOY.md` never assumes SSH from a
dev laptop either — it documents `git clone`/`scp` from *your* machine to the VPS,
not the reverse. **This machine cannot reach the VPS directly.** The commands below
are the copy-paste path for the owner to run themselves (VPS side, then local side).

## What was actually broken (root cause)

`kb/management/commands/seed_kb.py` called `AgentPrompt.objects.update_or_create(...)`
and `QuickReplyChip.objects.update_or_create(...)` for every seed run. Any
`docker compose ... exec web python manage.py seed_kb` — which the deploy docs run
on every fresh setup, and which could plausibly be re-run during a redeploy —
silently overwrote `body`, `model_id`, `language_directive`, `is_active`, chip
`order`, and chip labels back to the code defaults, discarding whatever the owner
had tuned in the dashboard. That's the version-drift bug: DB edits were never safe
from a reseed.

## Fix

1. **No-clobber seeding** (`kb/management/commands/seed_kb.py`): prompts and chips
   now use `get_or_create` — seeding only ever creates missing rows. Owner edits in
   the dashboard now survive any re-seed. Added `--force` to explicitly reset a role
   back to the code default when that's genuinely wanted.
2. **Export** (`kb/management/commands/export_agent_config.py`): dumps
   `AgentPrompt`, `AgentGuardrail`, `QuickReplyChip(+Text)`, `FlowConfig`,
   `RoutingRule` to one JSON document (stdout), with `schema_version` +
   `exported_at`.
3. **Import** (`kb/management/commands/import_agent_config.py <file>`): idempotent
   reconciler, matches rows by natural key (role / rule / intake_step+category+value
   / name). Default is a dry-run field-level diff; `--prefer file` applies the file
   onto the DB. Never deletes rows absent from the file.
4. **Drift visibility** (`kb/management/commands/agent_config_diff.py`): read-only,
   compares the DB's `AgentPrompt` rows against `kb/seed_prompts.py`'s code
   defaults and lists which roles have owner edits.

## The operating rule going forward

**The DB is the source of truth for prompts/guardrails/chips/flow/routing rules.**
`kb/seed_prompts.py` + `seed_kb.py`'s constants are first-boot defaults only — they
create a role's row once and never touch it again. Moving config between
environments (prod -> local, or restoring after a DB reset) goes through
`export_agent_config` / `import_agent_config`, not through re-running the seed.

## Commands

**On the VPS** (pull the owner's current live edits into a file):
```bash
docker compose -f docker-compose.prod.yaml exec -T web \
    python manage.py export_agent_config > prod-export.json
```
Copy it to your machine:
```bash
scp user@<VPS_IP>:~/swedish-bot/prod-export.json .
```

**Locally** (see what would change, then apply):
```bash
python manage.py import_agent_config prod-export.json                 # dry-run diff
python manage.py import_agent_config prod-export.json --prefer file    # apply
```

**Before any deploy/redeploy**, sanity-check nothing will be silently lost:
```bash
python manage.py agent_config_diff
```
(On the VPS, run the same command before pulling new code + running `seed_kb`
again — anything listed is an owner edit that `seed_kb` will now correctly leave
alone, but it's worth confirming before a release.)

## Status

Blocked on VPS access from this machine — pull not performed here. The owner
should run the two VPS-side commands above and hand `prod-export.json` back (or
run `import_agent_config` themselves, following this doc) to actually apply prod's
live-edited prompts to a local dev DB.
