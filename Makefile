export UV_CACHE_DIR ?= .uv-cache
UV_RUN = uv run --locked --no-sync

.PHONY: sync lint format test verify smoke run-api run-worker infra-up infra-down db-up db-down migrate

sync:
	uv sync --locked

lint:
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .
	$(UV_RUN) mypy src tests

format:
	$(UV_RUN) ruff format .

test:
	$(UV_RUN) pytest

verify: lint test

smoke:
	$(UV_RUN) python -m transcription.smoke "$(WAV)"

run-api:
	$(UV_RUN) uvicorn bootstrap.main:create_app --factory --host 127.0.0.1 --port 8000 --ws websockets --ws-max-size 16384 --ws-max-queue 4

run-worker:
	$(UV_RUN) python -m worker

infra-up:
	docker compose up --wait postgres rabbitmq

infra-down:
	docker compose down

db-up:
	docker compose up --wait postgres

db-down:
	docker compose stop postgres

migrate:
	$(UV_RUN) alembic upgrade head
