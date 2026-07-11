# cmu-scheduler dev tasks. Run `make <target>`.
# Backend is managed with uv; frontend with npm.

.PHONY: help install dev backend frontend build test lint ingest

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

install: ## Install backend (uv) and frontend (npm) dependencies
	cd backend && uv sync
	cd frontend && npm install

dev: backend ## Alias for `backend` (run `make frontend` in a second terminal)

backend: ## Run the FastAPI backend with autoreload (http://localhost:8000)
	cd backend && uv run uvicorn app.main:app --reload

frontend: ## Run the Vite dev server (http://localhost:5173)
	cd frontend && npm run dev

build: ## Production build of the frontend
	cd frontend && npm run build

test: ## Run the backend test suite
	cd backend && uv run pytest

lint: ## Lint the backend (ruff) and type-check the frontend (tsc)
	cd backend && uv run ruff check . ../scripts
	cd frontend && npm run typecheck

ingest: ## Dry-run ingestion from committed fixtures into a generated JSON file
	cd backend && uv run python ../scripts/ingest/cli.py --dry-run \
		--out ../data/samples/courses.generated.json
