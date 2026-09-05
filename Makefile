.PHONY: install dev check migrate makemigrations run test test-live test-e2e lint spike seed demo css messages up down logs deploy-migrate smoke

install:
	uv sync

# Compile the dashboard Tailwind CSS (committed to static/dashboard/css/app.css so
# the Docker image stays Python-only). Re-run after editing dashboard templates.
css:
	npx -y tailwindcss@3.4.17 -c tailwind.config.js -i static/src/input.css -o static/dashboard/css/app.css --minify
	uv run python tools/css_inputs_hash.py --write

# Rebuild the translation catalogue. Django's makemessages/compilemessages need the GNU
# gettext binaries (xgettext/msgfmt), which aren't installed on Windows — these do the same
# two jobs via polib. Django reads ONLY the compiled .mo, so `compile` is what makes a
# translation actually appear; committing a .po without it changes nothing.
messages:
	uv run python tools/i18n_messages.py extract
	uv run python tools/i18n_messages.py compile
	uv run python tools/i18n_messages.py stats

# Playwright end-to-end (needs the stack up on :8080 + staff user admin/nordland123).
test-e2e:
	uv run python tools/e2e_playwright.py

check:
	uv run python manage.py check

makemigrations:
	uv run python manage.py makemigrations

migrate:
	uv run python manage.py migrate

run:
	uv run python manage.py runserver

test:
	uv run pytest

test-live:
	uv run pytest -m live

lint:
	uv run ruff check .

seed:
	uv run python manage.py seed_kb

# End-to-end live demo: build a manual PDF, seed, ingest, run a real conversation
demo:
	uv run python tools/make_demo_pdf.py
	uv run python manage.py seed_kb
	uv run python manage.py ingest_pdf ivt-490 data/uploads/ivt490_demo_manual.pdf
	uv run python tools/demo_live.py

# Phase 0 de-risk spike (needs Gemini creds in .env)
spike:
	uv run python tools/spike_gemini.py

up:
	docker compose up --build

down:
	docker compose down

# Run after every deploy (git pull + docker build): migrate, seed/import chain, selfcheck.
deploy-migrate:
	uv run python manage.py migrate
	uv run python manage.py post_deploy
	uv run python manage.py selfcheck

# Post-deploy smoke test: selfcheck + hit the 3 load-bearing routes against a running server.
smoke:
	uv run python manage.py selfcheck
	uv run python tools/smoke.py
