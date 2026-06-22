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
