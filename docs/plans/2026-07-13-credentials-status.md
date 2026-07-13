# Voice channel credentials — status (2026-07-13)

Source: `happytime-budtender/voice/.env` (sibling project, same owner). Destination:
`swedish-bot/.env`, appended under `# --- voice channel (copied from happytime-budtender 2026-07-13) ---`.
No existing `.env` lines were touched — pure append. Full secret values are never
printed below; only presence/length/prefix.

## Status table

| Credential | In happytime-budtender | Action | Verified |
|---|---|---|---|
| `VAPI_PRIVATE_KEY` | present (len 36) | **copied** — same Vapi org/account, account-scoped REST bearer key | ✅ `GET https://api.vapi.ai/assistant` → 200, 7 assistants returned |
| `VAPI_WEBHOOK_SECRET` | present (len 43) | **not copied** — generated a fresh random value for swedish-bot (per-assistant shared secret; happytime's only matches happytime's Vapi Server-URL config) | N/A (no live endpoint to verify against until set on a provisioned assistant) |
| `VAPI_PHONE_NUMBER_ID` | present (len 36) | **not copied** — happytime's own inbound number; Nordland needs its own | — still missing |
| `VAPI_ASSISTANT_ID` / `VAPI_SQUAD_ID` | empty/absent | not applicable | — created by `provision_vapi` once run for real |
| `VAPI_VOICE_ID` | present (len 36) | **not copied** — happytime's voice is not Swedish; Nordland needs an ElevenLabs sv-SE voice id | — still missing |
| `ELEVENLABS_API_KEY` (any `ELEVEN*`) | **not found anywhere** in happytime-budtender | nothing to copy | N/A — architecturally not needed by this stack; Vapi resolves ElevenLabs from its own dashboard (see `dashboard/credentials.py` docstring in both repos) |
| `WA_PHONE_NUMBER_ID` | not found | nothing to copy | — still missing (real Meta credential, cannot be fabricated) |
| `WA_ACCESS_TOKEN` | not found | nothing to copy | — still missing (real Meta credential, cannot be fabricated) |
| `WA_APP_SECRET` | not found | **generated fresh** (own signing secret; must match whatever Meta app you configure) | N/A |
| `WA_VERIFY_TOKEN` | not found | **generated fresh** (echoed during Meta webhook subscribe handshake) | N/A |
| `N8N_*` (url/webhook/secret) | not found | nothing to copy | — still missing |
| `TWILIO_*` | not found (this stack uses Vapi, not Twilio, for telephony) | nothing to copy | N/A — not part of this architecture |

## Boot verification

- `uv run python manage.py check` — **passes** with the new `.env` (dev mode, `DJANGO_DEBUG=1`).
- Same check re-run with `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` overridden, `GOOGLE_CLOUD_LOCATION=europe-north1` (env-only overrides, `.env` untouched) to exercise the production fail-closed path in `config/settings.py` — **passes**: the `VOICE_ENABLED` guard requires `VAPI_WEBHOOK_SECRET` and `WA_APP_SECRET` both non-empty, and both are now set (one copied's sibling generated fresh, one generated fresh).
- `uv run python manage.py provision_vapi --dry-run` — reaches the Vapi-credential-dependent code path (confirms `VAPI_PRIVATE_KEY` loads and Postgres connects) but errors on `relation "voice_vapiobject" does not exist` — **the `voice` app's migrations haven't been applied in this DB**, unrelated to credentials. Not fixed here: migrating could touch the Postgres DB the concurrent 200-conversation eval / Playwright run may be using, which is out of scope per the task's "don't touch running server/containers" rule. Flag this as a prerequisite before provisioning can actually run.

## What the owner must still provide (definitive missing list)

1. **A Vapi phone number for Nordland** — happytime-budtender's `VAPI_PHONE_NUMBER_ID` is a different business's inbound number and was deliberately not copied.
2. **An ElevenLabs Swedish (sv-SE) voice id** for the Vapi assistant — happytime's voice id is not Swedish.
3. **WhatsApp Business / Meta credentials** — none exist in either project yet: a Meta app + WhatsApp Business phone number, `WA_PHONE_NUMBER_ID`, `WA_ACCESS_TOKEN`. (`WA_APP_SECRET`/`WA_VERIFY_TOKEN` are now set locally with fresh generated values — but they still need to be entered into the Meta app's webhook config to mean anything.)
4. **n8n instance URL** (`N8N_WEBHOOK_URL`) — not configured in happytime-budtender either; if the lead fan-out / Drive-mirror sink is wanted for Nordland, this needs a real n8n webhook URL.
5. **Apply `voice` app migrations** to the target Postgres DB before `provision_vapi` can run for real (currently blocked on a missing table, unrelated to credentials — do this outside the concurrent eval window).
6. **Go/no-go to publish the Vapi assistant** — `VAPI_PRIVATE_KEY` is verified live and reachable, but nothing has been provisioned or published; that requires items 1–2 above plus an explicit decision to run `provision_vapi` for real (not `--dry-run`) and then publish.

ElevenLabs API key and Twilio credentials are architecturally not part of this stack (Vapi owns ElevenLabs directly; telephony is Vapi, not Twilio) — no gap to fill there.
