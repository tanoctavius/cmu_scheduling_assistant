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

The LLM layer defaults to a deterministic **stub** that makes no network call, so no key and
no cloud account are needed to run, demo, or test. To use a real model, see
[Configuring the LLM provider](#configuring-the-llm-provider) below.

The server holds **no persistent state**: the catalog and requirements are in-memory caches
built at import and rebuilt on every start, and no LLM client is cached across requests. A
cold start is always clean — safe against a Learner Lab session timing out.

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

## Configuring the LLM provider

The LLM layer is **model- and provider-agnostic**. The orchestrator talks to one interface —
`LLMProvider.generate(messages, response_schema)` in
[`backend/app/llm_provider.py`](backend/app/llm_provider.py) — and never knows which provider
is behind it. Selection is runtime configuration via env vars; **no provider, model ID, base
URL, or key appears in code**. Copy `backend/.env.example` to `backend/.env` and edit.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `LLM_PROVIDER` | no | `stub` | Which implementation answers: `stub` or `groq` |
| `LLM_MODEL` | for `groq` | — | Model name, e.g. `llama-3.3-70b-versatile` |
| `GROQ_API_KEY` | for `groq` | — | Groq key ([console](https://console.groq.com/keys)) |
| `GROQ_BASE_URL` | no | `https://api.groq.com/openai/v1` | OpenAI-compatible base URL |
| `LLM_TIMEOUT_SECONDS` | no | `30` | Per-request timeout |

**`stub` (default)** — deterministic, offline. No key, no SDK, no network call. This is why
the full test suite and CI pass with zero cloud dependency.

**`groq`** — Groq's OpenAI-compatible Chat Completions API over plain HTTPS:

```bash
export LLM_PROVIDER=groq
export GROQ_API_KEY=…              # never commit this; .env is gitignored
export LLM_MODEL=llama-3.3-70b-versatile
```

### Why this shape (AWS Academy Learner Lab)

Learner Lab constrains us to `us-east-1`/`us-west-2`, forbids creating IAM roles, expires the
session after ~4 hours, and may not have Bedrock enabled at all. The `groq` path is a direct
HTTPS call that touches **neither AWS Bedrock nor AWS IAM**, so it works there unchanged, and
the `stub` default runs with no cloud at all. Nothing in the app assumes Bedrock.

Adding a provider later (Anthropic direct, Bedrock, OpenAI) means writing **one class** with a
`generate` method and registering it in `_PROVIDERS` — no change to the orchestrator, and none
to the verifier.

### The safety gate is provider-independent

Provider choice never changes what is checked. Every factual claim — whoever produced it —
passes the deterministic [claim verifier](backend/app/verifier.py) before display; failed
claims are stripped. Behavior is identical across providers: the LLM only ever describes
schedulable (eligible/unconfirmed, never blocked or completed) courses the solver already
produced, and unconfirmed prereqs surface as confirmation controls in the right-hand panel.
`backend/tests/test_orchestrator.py` asserts this by feeding the *same* false claim through
two different providers and requiring both to be caught.

The LLM's authority is narrower still in the chat (`/chat`). It does exactly two things:
classify the turn (question or change request) and, for a change, fill a **closed
`ScheduleConstraints` vocabulary** — avoid these days, cap units here, no class before/after,
drop this course. Those constraints are translated into the solver's existing inputs (a units
cap, commitment blocks, an exclusion set) and the **solver** builds the calendar. There is no
field in which a model can express "put 15-213 here", so it cannot hand-edit a schedule or
invent a section; the worst a bad proposal can do is produce a valid schedule you didn't ask
for. The rationale panel is LLM-free entirely — it is derived from the solved schedule and
gated by the verifier (`backend/app/rationale.py`), so it costs no API call and reads the same
under every provider.

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
