# Deploy Nordland VVS bot to a VPS (nordland.3dpresence.com)

Production stack: **Caddy (auto-HTTPS) → gunicorn/Django → Postgres**, all via
`docker-compose.prod.yaml`. The prod compose forces the safe flags
(`DEBUG=0`, `DEMO_OPEN_ADMIN=0`, `HTTPS_ENABLED=1`); secrets + domain live in `.env`.

---

## 0. DNS — add the subdomain FIRST (TLS depends on it)

At your DNS provider for **3dpresence.com**, add one record:

| Type | Name (host) | Value           | TTL  |
|------|-------------|-----------------|------|
| A    | `nordland`  | `<VPS_PUBLIC_IP>` | 300 / Auto |

(If the VPS has IPv6, also add an `AAAA` record `nordland` → the IPv6 address.)

Verify it resolves before continuing:
```bash
dig +short nordland.3dpresence.com     # must print your VPS IP
```
Caddy can only issue the Let's Encrypt certificate once this points at the VPS and
ports 80 + 443 are open.

---

## 1. VPS prerequisites (Ubuntu/Debian, run as root or with sudo)

```bash
# Docker + compose plugin
curl -fsSL https://get.docker.com | sh
# firewall: allow SSH + web
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
```

## 2. Get the code + the Vertex key onto the VPS

```bash
git clone <your-repo-url> ~/swedish-bot        # or: scp -r the project folder to ~/swedish-bot
cd ~/swedish-bot
mkdir -p secrets data/uploads
# copy your Google Vertex service-account JSON to this exact path:
cp /path/to/your-vertex-sa.json secrets/gcp-vertex-ai.json
```

## 3. Configure + launch (the one-shot)

```bash
cd ~/swedish-bot
cat > .env <<EOF
DJANGO_SECRET_KEY=$(openssl rand -hex 48)
PHONE_HASH_PEPPER=$(openssl rand -hex 48)
POSTGRES_DB=nordland
POSTGRES_USER=nordland
POSTGRES_PASSWORD=$(openssl rand -hex 24)
DJANGO_ALLOWED_HOSTS=nordland.3dpresence.com,localhost,127.0.0.1,web
CSRF_TRUSTED_ORIGINS=https://nordland.3dpresence.com
WIDGET_ALLOWED_ORIGINS=https://www.nordlandvvs.se,https://nordland.3dpresence.com
GEMINI_USE_VERTEX=True
GOOGLE_CLOUD_PROJECT=YOUR_GCP_PROJECT_ID
GOOGLE_CLOUD_LOCATION=europe-north1
ALLOW_NON_EU_RESIDENCY=0
LEAD_EMAIL_FROM=bot@nordlandvvs.se
LEAD_EMAIL_TO=
EOF

docker compose -f docker-compose.prod.yaml up -d --build
```

> **Vertex region:** keep `GOOGLE_CLOUD_LOCATION=europe-north1` for GDPR. If your only
> service account is the temporary `us-central1` one, set `GOOGLE_CLOUD_LOCATION=us-central1`
> **and** `ALLOW_NON_EU_RESIDENCY=1` — acceptable for a demo, **not** for real customer PII.

## 4. Load the knowledge base + create your admin login

**Option A — copy the fully-configured data from your local machine (recommended: brings the imported IVT manuals + tuned prompts).**
On your local machine (where the app currently runs):
```bash
docker compose exec -T db pg_dump -U nordland nordland | gzip > nordland.sql.gz
scp nordland.sql.gz   user@<VPS_IP>:~/swedish-bot/
scp -r data/uploads/* user@<VPS_IP>:~/swedish-bot/data/uploads/
```
Then on the VPS:
```bash
cd ~/swedish-bot
gunzip -c nordland.sql.gz | docker compose -f docker-compose.prod.yaml exec -T db psql -U nordland -d nordland
docker compose -f docker-compose.prod.yaml restart web
docker compose -f docker-compose.prod.yaml exec web python manage.py createsuperuser
```

**Option B — build the data fresh on the VPS** (upload the IVT manuals to `data/asistent/` first):
```bash
docker compose -f docker-compose.prod.yaml exec web python manage.py seed_kb
docker compose -f docker-compose.prod.yaml exec web python manage.py import_kb \
    --source /app/data/asistent/Asistent --vendor IVT --lang sv --include-terms
docker compose -f docker-compose.prod.yaml exec web python manage.py import_site_faq \
    --base-url https://www.nordlandvvs.se
docker compose -f docker-compose.prod.yaml exec web python manage.py createsuperuser
```

## 5. Verify

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://nordland.3dpresence.com/healthz   # 200
docker compose -f docker-compose.prod.yaml exec web python manage.py check_ai      # AI stack OK
```
- Dashboard: `https://nordland.3dpresence.com/dashboard/` (log in with the superuser)
- Admin: `https://nordland.3dpresence.com/admin/`
- Live widget demo: `https://nordland.3dpresence.com/widget-demo`

## 6. Embed the widget on the WordPress site

Add to the WordPress site (`<head>` or footer scripts):
```html
<script src="https://nordland.3dpresence.com/static/widget/nordland-widget.js" data-lang="sv" defer></script>
```
`WIDGET_ALLOWED_ORIGINS` already whitelists `https://www.nordlandvvs.se` for CORS.

## Ops
```bash
docker compose -f docker-compose.prod.yaml logs -f web        # logs
docker compose -f docker-compose.prod.yaml up -d --build      # deploy an update (after git pull)
docker compose -f docker-compose.prod.yaml exec web python manage.py summarize_idle   # cron these:
docker compose -f docker-compose.prod.yaml exec web python manage.py resend_leads     #  every 10-15 min
docker compose -f docker-compose.prod.yaml exec web python manage.py purge_pii        #  daily (GDPR)
```

---

## V2 — upgrading an existing VPS deploy

The class of failure this section exists to prevent: code gets pulled and the
container rebuilt, but the post-code steps (migrate, re-seed, re-check) don't
happen, and the bot serves a half-migrated or half-seeded DB for hours before
anyone notices (the 2026-07-12 live-eval outage — DB ran a day broken because
`migrate` + seed weren't re-run after a merge).

### Upgrade steps (every deploy after the first)

```bash
cd ~/swedish-bot
git pull
docker compose -f docker-compose.prod.yaml up -d --build
docker compose -f docker-compose.prod.yaml exec web python manage.py migrate
docker compose -f docker-compose.prod.yaml exec web python manage.py post_deploy
docker compose -f docker-compose.prod.yaml exec web python manage.py selfcheck
```

`post_deploy` chains `seed_kb` (no-clobber — never overwrites a dashboard-edited
prompt/chip), `import_general_knowledge` (only if you pass `--faq <path>`),
`seed_service_areas`, `import_postcodes` (only if `PostcodeArea` is empty, or pass
`--force-postcodes`), then `selfcheck`. It's idempotent — safe to run on every
deploy, code change or not. `selfcheck` alone exits 1 (and prints a PASS/FAIL/WARN
table) if anything a live deploy needs is actually missing — migrations pending,
an `AgentPrompt` row missing/blank for any of the 11 `AGENT_ROLE_CHOICES`, no
active vendor/machine, no `PostcodeArea` rows, or the static widget file missing.
`GeoSettings`/`ServiceArea` and `FormButton` gaps print as **WARN**, not FAIL —
those are owner go-live items (see checklist below), not code defects.

Equivalent one-liner from a dev machine with `uv`/local Postgres (not the VPS):
`make deploy-migrate`. `make smoke` runs `selfcheck` plus `tools/smoke.py`
(hits `/`, `/demo/homepage`, `POST /api/chat/session` against `SMOKE_BASE_URL`,
default `http://localhost:8000`) to confirm the running server actually serves.

### Env-var inventory (everything added since v1, from `config/settings.py`)

| Var | Default | Notes |
|---|---|---|
| `PREFILL_ALLOWED_ORIGIN` | `https://www.nordlandvvs.se` | Origin allowed to cross-origin-fetch `/api/prefill/<token>` (the real WordPress form). |
| `RATE_LIMIT_PREFILL` | `30` | Prefill lookups / IP / window. |
| `RATE_LIMIT_SESSION` | `20` | Chat sessions / IP / window. |
| `RATE_LIMIT_MESSAGE` | `40` | Messages / session / window. |
| `RATE_LIMIT_WINDOW` | `300` | Seconds, shared by the two limits above. |
| `MAX_TOTAL_TURNS` | `25` | Hard per-conversation turn ceiling. |
| `MAX_IMAGES_PER_CONVERSATION` | `8` | Image-upload ceiling per conversation. |
| `SEMANTIC_SEARCH_ENABLED` | `1` | Embedding-backed FAQ/guide retrieval augment. On by default; disabled automatically under pytest. |
| `WIDGET_ALLOWED_ORIGINS` | `http://localhost:8000` | CORS allow-list for embedding the widget / hitting the chat API. **Add the widget's real embed origin(s)** here (comma-separated) — already includes `https://www.nordlandvvs.se,https://nordland.3dpresence.com` in the §3 `.env` example. |
| `VOICE_ENABLED` | `1` | Phone/WhatsApp channel toggle. **Fail-closed**: if `1` in production and `VAPI_WEBHOOK_SECRET` or `WA_APP_SECRET` is unset, the app refuses to boot (`ImproperlyConfigured`). Set `0` to run without the voice channel. |
| `VAPI_PRIVATE_KEY` / `VAPI_WEBHOOK_SECRET` / `VAPI_PHONE_NUMBER_ID` / `VAPI_ASSISTANT_ID` / `VAPI_ASSISTANT_MODEL` / `VAPI_VOICE_ID` | `""` | Vapi voice-channel credentials. DB-editable from the dashboard credentials catalog (live-applied over these `.env` defaults) once provisioned. |
| `VAPI_SIGNATURE_HEADER` / `VAPI_SECRET_HEADER` | `X-Vapi-Signature` / `X-Vapi-Secret` | Vapi webhook auth header names — only change if Vapi changes theirs. |
| `WA_PHONE_NUMBER_ID` / `WA_ACCESS_TOKEN` / `WA_APP_SECRET` / `WA_VERIFY_TOKEN` / `WA_PHOTO_TEMPLATE_NAME` | `""` | WhatsApp Cloud API credentials. Same fail-closed rule as Vapi (`WA_APP_SECRET` required if `VOICE_ENABLED=1`). |
| `WA_GRAPH_VERSION` | `v21.0` | WhatsApp Graph API version pin. |
| `N8N_WEBHOOK_URL` | `""` | n8n Drive-mirror webhook (outbound file links). |
| `VOICE_WEBHOOK_DEV_BYPASS` | `0` | Local-dev-only voice webhook signature bypass — honored only when `DJANGO_DEBUG=1`; ignored in prod regardless of value. |
| `PUBLIC_BASE_URL` | `""` | Absolute base URL for building outbound file links (n8n Drive mirror). Set to `https://nordland.3dpresence.com` in prod. |

(v1 vars — `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`,
`PHONE_HASH_PEPPER`, `POSTGRES_*`, `CSRF_TRUSTED_ORIGINS`, `GOOGLE_CLOUD_*`,
`ALLOW_NON_EU_RESIDENCY`, `LEAD_EMAIL_*`, `HTTPS_ENABLED` — already covered above
in §3, unchanged.)

### Prompt-sync operating rule

`AgentPrompt`/`QuickReplyChip` rows are dashboard-editable and seeding never
overwrites them (`seed_kb --force` is the only way to reset to code defaults).
That means the VPS and local dev DBs *will* drift from each other as the owner
tunes prompts live. The operating rule, full mechanics in
[`docs/plans/2026-07-14-prompt-sync.md`](docs/plans/2026-07-14-prompt-sync.md):

- **Owner tunes a prompt on the VPS dashboard** → `export_agent_config` on the VPS
  → copy the JSON down → `import_agent_config` locally, so local dev matches prod.
- **You change a prompt in code/seed locally** → same export/import round-trip in
  reverse before it ships, so the deploy doesn't silently clobber a live-tuned
  prompt with a stale code default.
- Never assume `seed_kb` (or `post_deploy`) on a redeploy resets prompts — it
  can't, by design.

**You do NOT need `--force` to enable a new feature.** That was a real trap: a
feature whose JSON contract key was added in code (`no_action_needed`,
`consult_web`, …) would have stayed permanently inert against an owner-edited
prompt that never emits it — silently, with the whole test suite green, because
tests always run against a freshly seeded prompt. `chat/prompts.py::render()` now
appends any missing contract line itself (`contract_addendum`), so backend and
agent output stay aligned no matter how the body was edited. Run
`manage.py agent_config_diff` after a deploy to *see* the drift, but never reach
for `seed_kb --force` on the VPS just to pick up a new contract key — that would
throw away the owner's live tuning to fix a problem the code already handles.
`--force` remains only for a deliberate "reset this prompt to the code default".

### Widget embed cache-bust

`static/widget/nordland-widget.js` is served through WhiteNoise's manifest
storage (`CompressedManifestStaticFilesStorage`) — but the WordPress `<script src>`
tag in §6 points at the **unhashed** path directly, so a new deploy that changes
the widget's behavior won't automatically bust the browser/CDN cache on
`nordlandvvs.se`. After shipping a widget change, either bump a manual query
string on the WordPress embed (`nordland-widget.js?v=2`) or purge any CDN/edge
cache in front of `nordland.3dpresence.com`.

### Owner go-live checklist

These are `selfcheck` **WARN** items — the code works without them, but the bot
isn't fully "live" for a real customer until an owner has:

1. **Approved the FAQ backlog** — `import_general_knowledge` lands every row
   `is_approved=False`. Review and approve the ~102 imported entries in
   `/dashboard/knowledge/` before relying on them in production answers.
2. **Enabled `GeoSettings` and reviewed the service-area polygons** —
   `seed_service_areas` loads the initial polygons but leaves `GeoSettings.enabled`
   at its default `False`. Review the polygons at `/dashboard/settings/service-area/`,
   then flip it on.
3. **Filled in the 4 `FormButton` URLs** (heat pump / water pump / water
   filtration / quote-request) at `/dashboard/settings/forms/` — the bot never
   invents a URL, so an unset button is simply not offered to customers.
4. **Installed the prefill snippet with its `FIELD_MAP`** on the real
   `nordlandvvs.se` WordPress contact form (see `templates/widget_demo.html` /
   `/api/prefill/<token>` for the field-mapping contract) so a bot handoff
   actually pre-fills the form instead of dropping the customer at a blank one.
5. **Provisioned Vapi** (phone channel) once real credentials exist — set
   `VAPI_*` in `.env` (or the dashboard credentials catalog) and confirm
   `VOICE_ENABLED=1` boots clean (no `ImproperlyConfigured` on startup).

### Upgrade to the 2026-08 release (a32d332 … HEAD) — read before `git pull`

Everything below is the same six-command upgrade as above; these are the three things
that are DIFFERENT about this release and will bite if skipped.

1. **New migrations** — kb 0019/0020 (`Vendor.official_domains`, `consult_web` tool row)
   and crm 0010 (`UnrevokedExternalCopy`). `migrate` applies them; `selfcheck` fails if any
   are pending.

2. **Owner-edited prompts are safe — but check the diff first.** `seed_kb` inside
   `post_deploy` is no-clobber, so dashboard-edited `AgentPrompt` rows are NOT overwritten.
   The features that depend on new prompt content (`no_action_needed`, `consult_web`, the
   gas/fuel switch-off exception) are delivered by a code-owned addendum in
   `chat/prompts.py::render()` whenever a body lacks them — they do not need `--force`.
   Still run, before and after:
   ```bash
   docker compose -f docker-compose.prod.yaml exec web python manage.py agent_config_diff
   ```
   Rows it lists as differing are owner edits and stay as they are. If you WANT the new
   repo defaults everywhere (and accept losing dashboard edits), and only then:
   `python manage.py seed_kb --force`.

3. **`selfcheck` is stricter now.** It FAILS on an inactive `AgentPrompt` row (an inactive
   role used to pass and then ran the model with no rules) and WARNS when a `FormButton`
   row has a blank URL (a blank-url button never renders a chip; the old check reported a
   green 4/4 while no form could be reached). Expect `WARN` for FormButton until the real
   form URLs are entered in the dashboard — that is an owner go-live item, not a failure.

Post-deploy proof, in this order: `selfcheck` exit 0 → `make smoke` (or `tools/smoke.py`
against the public URL) → `GET /healthz` shows `gemini.ready: true`.

### Website form integration (spec §13) — what the live site runs, and the wiring

Checked 2026-09-04 against the public site: **nordlandvvs.se is WordPress running
Fluent Forms.** One multi-step form (`fluentform_3`) serves both `/offert/` and
`/kontakta-oss/`; `/kundservice/` has no form. Field names as rendered today:

| Bot fact | Fluent Forms field (`name=`) |
|---|---|
| customer name | `names[first_name]` |
| phone / email | `phone` / `email` |
| installation address / postcode / city | `address_line_1` / `input_zip` / `input_city` |
| problem description + safe checks tried | `description` (textarea) |
| ärende (service / offert) | `dropdown` ("Välj ett ärende") — option values need reading from the live form |
| photos | `file-upload` — **cannot be prefilled** (browsers block programmatic file inputs); the lead already carries them, the technician sees them in the dashboard |

**Recommendation: keep the signed-token prefill already built (`/api/prefill/<token>`,
`PREFILL_ALLOWED_ORIGIN=https://www.nordlandvvs.se`, 30-min expiry, no PII in the URL) and add
one small script to the WordPress page.** The chip the bot shows links to
`/offert/?nl_case=<token>`; the script reads `nl_case`, fetches the prefill JSON cross-origin,
and fills the fields above by `name`. No plugin change, no REST/webhook, nothing sensitive in
the URL — the token resolves server-side and only for the allowed origin. Fluent Forms' own
"populate from GET parameter" would put the customer's name/phone in the URL, which §13 rules
out; a webhook/REST push into Fluent Forms Pro would create a duplicate submission before the
customer has confirmed anything, which §13's "showing the button ≠ submitted" rules out.

Owner to-do to switch it on: (1) paste the snippet (Fluent Forms → Settings → Custom
JS/CSS, or the theme footer) — `chat/prefill.py` docstring has the reference version;
(2) set the four `FormButton` URLs in the dashboard to the real `/offert/` / `/kontakta-oss/`
pages (blank URLs never render a chip — `selfcheck` warns until they're filled);
(3) confirm the `dropdown` option values so the ärende can be preselected.

**If `selfcheck` reports `PostcodeArea loaded FAIL 0 rows`** (a fresh or reset database):
`post_deploy` only imports postcodes when given the file — run once:
```bash
docker compose -f docker-compose.prod.yaml exec web python manage.py import_postcodes /app/data/SE.zip
```
(GeoNames `SE.zip` — the same file the dev DB was loaded from; 18,870 rows.) Rehearsed
2026-09-05 against a July-shaped replica DB: `migrate` (3 new), `post_deploy`, owner-edited
prompts kept verbatim, every new contract key delivered by the code-owned addendum — this
postcode step was the only manual one.
