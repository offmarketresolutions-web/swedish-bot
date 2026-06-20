.PHONY: install dev check migrate makemigrations run test lint spike up down logs

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

lint:
	uv run ruff check .

# Phase 0 de-risk spike (needs Gemini creds in .env)
spike:
	uv run python tools/spike_gemini.py

up:
	docker compose up --build

down:
	docker compose down
