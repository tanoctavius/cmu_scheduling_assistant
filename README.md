# cmu-scheduler

A conversational course-scheduling assistant for CMU students. A student fills out a short
survey, ticks off the prerequisites they've taken, and gets **conflict-free,
requirement-satisfying schedules ranked by predicted fit** — each explained in plain language
and checked against the real schedule. They can then *talk* to the calendar: ask about it
("what's my workload?") or change it ("swap the Friday class", "make it lighter").

A deterministic solver builds and validates every schedule. The language model never places a
class, never edits a calendar, and never authors a fact the student sees.

## Architecture at a glance

The spine of the system is one rule: **hard scheduling logic is deterministic; the LLM only
proposes, and a deterministic verifier checks every factual claim before it reaches the
student.** There are two request paths, and the solver owns the calendar on both.

**Build / confirm** — no LLM at all:

```
survey ─▶ prereq classifier ─▶ fused solver + ranking ─▶ rationale + claim verifier ─▶ UI
        (eligible/unconfirmed/   (branch-and-bound,       (facts derived from the
         blocked, §3)             deduped top-K, §5)       schedule, then gated §6)
```

**Chat** — the LLM proposes; the solver disposes:

```
"make it lighter" ─▶ LLM ─▶ ScheduleConstraints ─▶ same solver ─▶ rationale + verifier ─▶ UI
                     (classify + propose only)     (builds the actual new schedule)
```

The LLM's entire authority is: decide whether a turn is a *question* or a *change*, and if
it's a change, fill a closed `ScheduleConstraints` struct. Those constraints become ordinary
solver inputs (a units cap, commitment blocks, an exclusion set), so the solver's tested
invariants — no conflicts, commitments respected, cap honored — hold unchanged. There is no
field in which a model can say "put 15-213 here."

Ingestion runs **off the request path**: we parse the CMU Schedule of Classes and Course
Catalog ourselves into normalized models (no hosted API). Everything runs without secrets —
ingestion reads committed fixtures, and the LLM defaults to a deterministic, offline stub.

- **Full design write-up & rationale:** [`project_context.md`](project_context.md)
- **Per-stage record of what was human- vs. agent-written:** [`PROVENANCE.md`](PROVENANCE.md)
- **Ingestion (self-owned, dry-run mode, manual-FCE caveat):** [`scripts/ingest/README.md`](scripts/ingest/README.md)

## Repo layout

```
backend/               Python 3.11 + FastAPI service (managed with uv)
  app/
    main.py            the API: /survey, /recommend, /confirm, /chat
    prereq.py          classifier: eligible / unconfirmed / blocked
    solver.py          branch-and-bound top-K, deduped by section set
    ranking.py         FCE/interest fit score
    requirements.py    degree-requirement rules (+ requirements_loader.py)
    checklist.py       the prereq tick-off list
    rationale.py       why a schedule was built + verifier-gated facts (no LLM)
    orchestrator.py    chat turn: intent + constraints, then the verifier gate
    llm_provider.py    LLMProvider interface; stub (default) and groq
    verifier.py        the deterministic claim gate
    models.py          normalized data models
    data_loader.py     loads the committed catalog
  tests/               pytest suite (the deterministic core has strict tests)
  .env.example         every env var, documented
frontend/              React (Vite + TypeScript)
  src/components/      SurveyForm, PrereqChecklist, SchedulePanel (the workspace),
                       WeekGrid, RationalePanel, ConfirmationPanel, ChatThread
data/
  samples/             committed example inputs (shape of normalized data)
  fixtures/            committed HTML/CSV fixtures for dry-run ingestion & tests
scripts/ingest/        self-owned scrapers/parsers for SOC + Catalog + FCE
docs/                  design notes
deploy/                Learner Lab deployment notes
.devcontainer/         Dockerfile + devcontainer.json (Python 3.11, Node 20, uv, deps)
.github/workflows/     CI: backend tests on push
Makefile               dev / test / lint / ingest targets
```

## The API

| Endpoint | LLM? | Purpose |
|---|---|---|
| `GET /health` | no | Liveness probe |
| `POST /survey` | no | The grouped prereq tick-off checklist for a major |
| `POST /recommend` | no | classify → solve → rank → top-K schedules + rationale |
| `POST /confirm` | no | Apply prereq answers, re-run the cascade, return updated schedules |
| `POST /chat` | **yes** | One conversational turn: answer a question, or re-solve under new constraints |

Only `/chat` involves a model, and only to classify intent and propose constraints. Every
other path — including all the green checkmarks — is deterministic.

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

### 6. Use it

Open http://localhost:5173. The app is three parts:

1. **Tell us about you** — a short survey (major, expected graduation, interests).
2. **Which of these have you taken?** — tick off completed core courses and common
   prerequisites. This seeds the classifier and cuts down on follow-up questions.
3. **Your schedule** — press **Build schedule**. You get:
   - a **week-grid calendar**, with tabs for each distinct option;
   - a **right-hand panel** holding the *rationale* for the selected schedule (why it was
     built, plus green ✓ chips for every verified fact and ◆ chips for requirement coverage)
     and any **prerequisite confirmation controls** — Yes/No per missing prereq, each answer
     immediately re-running the cascade and updating the calendar in place;
   - a **chat** below, which either answers from the verified schedule data
     ("what's my workload?") or re-solves the calendar ("swap the Friday class", "make it
     lighter", "prioritize morning classes"). Follow-ups build on earlier turns, and the
     constraints currently applied are shown as chips above the calendar.

### 7. Run the tests

```bash
make test             # cd backend && uv run pytest
```

The full suite passes from a clean clone with no secrets (CI runs exactly this on push).

## Configuring the LLM provider

The LLM layer is **model- and provider-agnostic**. The orchestrator talks to one interface —
`LLMProvider.generate(messages, response_schema)` in
[`backend/app/llm_provider.py`](backend/app/llm_provider.py) — and never knows which provider
is behind it. Selection is runtime configuration via env vars; **no provider, model ID, base
URL, or key appears in code**. `backend/.env.example` documents every variable.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `LLM_PROVIDER` | no | `stub` | Which implementation answers: `stub` or `groq` |
| `LLM_MODEL` | for `groq` | — | Model name, e.g. `llama-3.3-70b-versatile` |
| `GROQ_API_KEY` | for `groq` | — | Groq key ([console](https://console.groq.com/keys)) |
| `GROQ_BASE_URL` | no | `https://api.groq.com/openai/v1` | OpenAI-compatible base URL |
| `LLM_TIMEOUT_SECONDS` | no | `30` | Per-request timeout |

**`stub` (default)** — deterministic, offline. No key, no SDK, no network call. This is why
the full test suite and CI pass with zero cloud dependency, and why the app is demoable with
no account anywhere.

**`groq`** — Groq's OpenAI-compatible Chat Completions API over plain HTTPS. The backend reads
these from its **environment**; `make backend` does not load `backend/.env` for you (nothing
in the app parses a `.env` file), so export them in the shell you run it from:

```bash
export LLM_PROVIDER=groq
export GROQ_API_KEY=…              # never commit this; .env is gitignored
export LLM_MODEL=llama-3.3-70b-versatile
make backend
```

> `backend/.env` is a convenient place to keep your values, but treat it as a notepad you copy
> from — or `pip install python-dotenv` and run
> `uv run uvicorn app.main:app --env-file .env`, which uvicorn ignores without that package.

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
claims are stripped. `backend/tests/test_orchestrator.py` asserts exactly this by feeding the
*same* false claim through two different providers (a mock and a real `GroqProvider` over
mocked HTTP) and requiring both to be caught.

Behavior is identical across providers in every other respect too: the LLM only ever describes
schedulable (eligible/unconfirmed — never blocked, never already completed) courses the solver
produced, and unconfirmed prereqs surface as confirmation controls in the right-hand panel.

Two properties are worth calling out because they are what make the guarantee cheap to trust:

- **The chat cannot reach the calendar.** A modification is the same solver run with different
  inputs (see the diagram above). The worst a bad proposal can do is produce a valid schedule
  you didn't ask for — never an invalid or fabricated one.
- **The rationale panel has no LLM in it at all.** The summary and the green ✓ chips are
  derived from the solved schedule and gated by the verifier
  ([`backend/app/rationale.py`](backend/app/rationale.py)). So they cost no API call, stay fast
  enough to re-render on every prereq toggle, and read identically under `stub` and `groq`.

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
  **solver**, the claim **verifier**, the **chat → solver translation**, and the **rationale**
  are correctness-critical — no change to any of them is complete without tests, and they get
  `strict` review (see [`PROVENANCE.md`](PROVENANCE.md)). These tests are load-bearing and must
  always exist:
  1. missing/unparseable prereq data resolves to `unconfirmed`, never `blocked`;
  2. a wrong LLM claim is caught by the verifier and never reaches output — *for every
     provider*;
  3. a chat modification goes through the solver and comes back conflict-free and verified;
  4. no two returned schedules are identical by course-section set.
- **The LLM proposes; it never acts.** If you extend the chat, extend `ScheduleConstraints` and
  its translation into solver inputs. Never add a path that lets a model write a section, a
  time, or a fact the student sees.
- **Everything runs without secrets.** Ingestion works from committed fixtures; the LLM
  defaults to an offline stub, so the full suite passes with no API key and no network. No
  secrets are committed — keys live in env vars only, and `.env` is gitignored.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the short version.
