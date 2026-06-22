.PHONY: install dev check migrate makemigrations run test test-live test-e2e lint spike seed demo css up down logs

install:
	uv sync

# Compile the dashboard Tailwind CSS (committed to static/dashboard/css/app.css so
# the Docker image stays Python-only). Re-run after editing dashboard templates.
css:
	npx -y tailwindcss@3.4.17 -c tailwind.config.js -i static/src/input.css -o static/dashboard/css/app.css --minify

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
