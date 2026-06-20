.PHONY: install dev check migrate makemigrations run test test-live lint spike seed demo up down logs

install:
	uv sync

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
