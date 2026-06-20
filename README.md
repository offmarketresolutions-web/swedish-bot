# Nordland VVS — AI Support Bot + Dashboard

Multi-agent Gemini support chatbot (embeds on nordlandvvs.se) + admin dashboard,
self-hosted on a VPS. Identifies the customer's equipment, gives **safe** light
troubleshooting from the full manufacturer manual (loaded into Gemini context — no
RAG), and captures a qualified lead + escalates anything non-trivial to Nordland.

Full design + rationale: `~/.claude/plans/monday-june-8-magical-piglet.md`.

## Stack
Django 5.2 · Postgres (+pg_trgm) · Google Gemini (Vertex AI, `europe-north1`) ·
Tailwind + Django templates · Docker (Caddy + gunicorn + Postgres).

## Local dev
```bash
cp .env.example .env        # fill in Gemini creds (Vertex project or dev API key)
make install                # uv sync
make migrate
make run                    # http://localhost:8000/healthz
```

## Phase 0 — de-risk first
```bash
make spike                  # verifies model ids + caching + live cost
```
Confirms the gemini ids/prices in `core/constants.py` against the live API before
the architecture relies on them. **Do this before trusting the cost model.**

## Layout
```
config/   Django settings, urls, wsgi/asgi
core/     gemini client, model-id/pricing constants, /healthz
kb/       editable agent config: vendors, machines, PDFs, prompts, FAQ, chips  (Phase 2)
chat/     thin append-only transcript + the orchestrator/agents               (Phase 3)
crm/      customers, sessions (canonical reporting), leads + sinks             (Phase 3/5/6)
dashboard/ staff monitoring UI                                                 (Phase 5)
widget/   embeddable chat bundle for WordPress                                 (Phase 4)
tools/    spike_gemini.py (Phase 0)
```
