# cmu-scheduler

A conversational course-scheduling assistant for CMU students. A student fills out a short
survey, then converses with the system to receive **conflict-free, requirement-satisfying
schedules ranked by predicted fit** — each explained in plain language with citations to
real course sections. A deterministic solver builds and validates every schedule; the
language model only explains and ranks what the solver has already proven correct.

See [`project_context.md`](project_context.md) for the full architecture and rationale.

## Repo layout

```
backend/          Python 3.11 + FastAPI service (managed with uv)
  app/            application code (app.main is the FastAPI entrypoint)
  tests/          pytest suite
frontend/         placeholder — survey + chat UI (Node 20), added later
data/
  samples/        committed example inputs (shape of normalized data)
  fixtures/       committed fixtures for dry-run ingestion & tests
docs/             design notes and documentation
scripts/          dev/ops helper scripts
.devcontainer/    Dockerfile + devcontainer.json (Python 3.11, Node 20, uv, deps)
```

## Getting started (zero setup)

The repo ships a devcontainer. Clone, open in a container (VS Code: *Reopen in
Container*), and the toolchain — Python 3.11, Node 20, uv, and the backend
dependencies — is already installed. No local setup required.

Prefer a local toolchain? Install [uv](https://docs.astral.sh/uv/) and run the commands
below.

## Run the backend

```bash
cd backend
uv run uvicorn app.main:app --reload
```

Then check the health endpoint:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

## Run the tests

```bash
cd backend
uv run pytest
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
- **Tests are required for the deterministic core.** The prerequisite **classifier**, the
  constraint **solver**, and the claim **verifier** are correctness-critical — no change to
  any of them is complete without tests. Two tests are load-bearing and must always exist:
  1. missing/unparseable prereq data resolves to `unconfirmed`, never `blocked`;
  2. a wrong LLM claim is caught by the verifier and never reaches output.
- **Everything runs without secrets.** Ingestion works from committed fixtures; the LLM has
  a stub fallback so the full suite passes with no API key. No secrets are committed — API
  keys live in env vars only.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the short version and
[`PROVENANCE.md`](PROVENANCE.md) for the per-stage record of what was human- vs.
agent-written.
