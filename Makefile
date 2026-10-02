# Developer entry points. Each directory also works on its own (uv / pnpm).
.PHONY: all test lint fmt demo dev-infra api-dev web-dev db-upgrade db-revision

all: lint test

test:
	cd core && uv run pytest -q
	cd api && uv run pytest -q
	cd web && pnpm build && pnpm test

lint:
	cd core && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd web && pnpm lint

fmt:
	cd core && uv run ruff format . && uv run ruff check --fix .
	cd api && uv run ruff format . && uv run ruff check --fix .

# Write the faulty demo shop and scan it.
demo:
	cd core && uv run sahifa synth /tmp/sahifa-shop && uv run sahifa scan /tmp/sahifa-shop --pretty

# Postgres 17 for metadata and a demo source (docker compose).
dev-infra:
	docker compose -f deploy/compose.dev.yaml up -d

db-upgrade:
	cd api && uv run python -m sahifa.db.migrate upgrade head

db-revision:
	cd api && uv run alembic revision --autogenerate -m "$(m)"

api-dev:
	cd api && uv run uvicorn sahifa.main:app --reload --port 8000

web-dev:
	cd web && pnpm dev
