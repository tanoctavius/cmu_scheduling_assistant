# cmu-scheduler

A conversational course-scheduling assistant for CMU students. A student fills out a short
survey, then converses with the system to receive **conflict-free, requirement-satisfying
schedules ranked by predicted fit** — each explained in plain language and checked against
the real schedule. A deterministic solver builds and validates every schedule; the language
model only explains and ranks what the solver has already proven correct.

## Architecture at a glance

The spine of the system is one rule: **hard scheduling logic is deterministic; the LLM only
explains and ranks what the solver has already validated, and a deterministic verifier
checks every factual claim before it reaches the student.** The request path is:

```
survey ─▶ prereq classifier ─▶ fused solver + ranking ─▶ LLM orchestrator ─▶ claim verifier ─▶ UI
        (eligible/unconfirmed/    (branch-and-bound        (explains, ranks,    (strips any
         blocked, §3)             top-K, §5)               emits claims)        false claim, §6)
```

Ingestion runs **off the request path**: we parse the CMU Schedule of Classes and Course
Catalog ourselves into normalized models (no hosted API). Everything runs without secrets —
ingestion reads committed fixtures, and the LLM has a deterministic stub fallback.

- **Full design write-up & rationale:** [`project_context.md`](project_context.md)
- **Per-stage record of what was human- vs. agent-written:** [`PROVENANCE.md`](PROVENANCE.md)
- **Ingestion (self-owned, dry-run mode, manual-FCE caveat):** [`scripts/ingest/README.md`](scripts/ingest/README.md)

## Repo layout

```
backend/          Python 3.11 + FastAPI service (managed with uv)
  app/            classifier, solver, ranking, verifier, orchestrator, API (app.main)
  tests/          pytest suite (classifier/solver/verifier/orchestrator have strict tests)
frontend/         React (Vite + TypeScript): survey, prereq checklist, chat, week-grid
data/
  samples/        committed example inputs (shape of normalized data)
  fixtures/       committed HTML/CSV fixtures for dry-run ingestion & tests
scripts/ingest/   self-owned scrapers/parsers for SOC + Catalog + FCE
docs/             design notes
.devcontainer/    Dockerfile + devcontainer.json (Python 3.11, Node 20, uv, deps)
.github/workflows/ CI: backend tests on push
Makefile          dev / test / lint / ingest targets
```

## Quick start

A new teammate should be able to go from clone to a running app with the steps below.

### 1. Clone

```bash
git clone <repo-url> cmu-scheduler
cd cmu-scheduler
```

### 2. Open in the devcontainer (recommended — zero setup)

The repo ships a devcontainer. In VS Code, **Reopen in Container**; the toolchain — Python
3.11, Node 20, [uv](https://docs.astral.sh/uv/), and the backend dependencies — is already
installed. Skip to step 4.

Prefer a local toolchain? Install **uv**, **Python 3.11+**, and **Node 20+**, then continue.

### 3. Install dependencies (local toolchain only)

```bash
make install          # backend: uv sync   +   frontend: npm install
```

### 4. Run the backend

```bash
make backend          # -> http://localhost:8000
# or: cd backend && uv run uvicorn app.main:app --reload
```

Sanity check:

```bash
curl http://127.0.0.1:8000/health      # {"status":"ok"}
```

The LLM orchestrator uses the deterministic **stub** unless `ANTHROPIC_API_KEY` is set — no
key is needed to run or demo. To use the real model: `export ANTHROPIC_API_KEY=…` and
install the optional extra (`cd backend && uv sync --extra llm`).

### 5. Run the frontend (in a second terminal)

```bash
cd frontend && cp .env.example .env    # set VITE_BACKEND_URL if not on :8000
make frontend                          # -> http://localhost:5173
```

Open http://localhost:5173: fill the survey, tick off completed prereqs, and ask for a
schedule in the chat box.

### 6. Run the tests

```bash
make test             # cd backend && uv run pytest
```

The full suite passes from a clean clone with no secrets (CI runs exactly this on push).

## Other tasks

```bash
make lint             # ruff (backend) + tsc --noEmit (frontend)
make ingest           # dry-run ingestion from committed fixtures -> generated JSON
make build            # production build of the frontend
make help             # list all targets
```

## Conventions

- **Branch naming:** `type/short-description`, e.g. `feat/solver-branch-bound`,
  `fix/prereq-parse`, `docs/readme`. Types: `feat`, `fix`, `docs`, `chore`, `test`,
  `refactor`.
- **Commit style:** imperative, present tense, ideally
  [Conventional Commits](https://www.conventionalcommits.org/) —
  `feat: add branch-and-bound solver`. Keep the subject under ~72 chars.
- **Where tests live:** backend tests in `backend/tests/`, named `test_*.py`, run with
  `uv run pytest`.
- **The deterministic core requires tests.** The prerequisite **classifier**, the constraint
  **solver**, the claim **verifier**, and the LLM **orchestrator** are correctness-critical —
  no change to any of them is complete without tests, and they get `strict` review (see
  [`PROVENANCE.md`](PROVENANCE.md)). Two tests are load-bearing and must always exist:
  1. missing/unparseable prereq data resolves to `unconfirmed`, never `blocked`;
  2. a wrong LLM claim is caught by the verifier and never reaches output.
- **Everything runs without secrets.** Ingestion works from committed fixtures; the LLM has a
  stub fallback so the full suite passes with no API key. No secrets are committed — API keys
  live in env vars only.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the short version.
