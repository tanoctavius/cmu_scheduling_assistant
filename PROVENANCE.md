# Code Provenance Log

This log records the origin and review of every module in the repository, maintained
**per-stage as the code was built** (not reconstructed afterward). It exists to make clear
what was human-written vs. agent-generated, and what review each piece received.

## Columns

- **Artifact** — the file or module.
- **Origin** — one of:
  - `human-written` — authored by a team member.
  - `agent-generated` — produced by Claude Code, accepted with light review.
  - `agent + human-revised` — drafted by Claude Code, then materially edited by a team member.
- **Reviewer** — the team member accountable for reviewing it.
- **Review type** — depth of review:
  - `skim` — read for obvious defects and convention fit.
  - `reviewed` — read in full, with change requests.
  - `strict` — line-by-line plus tests. **Required for any correctness-critical module**
    (prereq classifier, solver, verifier, LLM orchestrator).

> Convention: no agent-generated code is considered done without a named reviewer.
> Correctness-critical modules must be `strict`.

---

## Log

| Artifact | Origin | Reviewer | Review type |
|---|---|---|---|
| Repo skeleton (`backend/`, `frontend/`, `data/`, `docs/`, `scripts/`, `pyproject.toml`, `.gitignore`) | agent-generated | Octavius | skim |
| Devcontainer (`.devcontainer/devcontainer.json`, `.devcontainer/Dockerfile`) | agent-generated | Octavius | skim |
| README + conventions (`README.md`, `CONTRIBUTING.md`) | agent-generated | Octavius | skim |
| Health endpoint + test (`backend/app/main.py`, `backend/tests/test_health.py`) | agent-generated | Octavius | skim |
| Core data models (`backend/app/models.py`) | agent-generated | Octavius | reviewed |
| Sample course fixtures (`data/samples/courses.json`) | agent-generated | Octavius | reviewed |
| Data loader (`backend/app/data_loader.py`) | agent-generated | Octavius | skim |
| Model/fixture tests (`backend/tests/test_models.py`) | agent-generated | Octavius | skim |
| Prereq classifier (`backend/app/prereq.py`) — **correctness-critical** | agent-generated | Octavius | strict |
| Prereq classifier tests (`backend/tests/test_prereq.py`) — 100% branch cov | agent-generated | Octavius| strict |
| `PrereqUnparsed` node added to models (`backend/app/models.py`) — encodes the unparseable→`unconfirmed` safety rule | agent-generated | Octavius | strict |
| Fused solver (`backend/app/solver.py`) — **correctness-critical**; branch-and-bound top-K | agent-generated | Octavius | strict |
| Ranking function (`backend/app/ranking.py`) — **correctness-critical**; weighted FCE/interest heuristic | agent-generated | Octavius | strict |
| `Schedule` result model added to models (`backend/app/models.py`) | agent-generated | Octavius | reviewed |
| Solver/ranking tests (`backend/tests/test_solver.py`) — property-style, 100% branch cov; caught a real conflict bug | agent-generated | Octavius | strict |
| Claim verifier (`backend/app/verifier.py`) — **correctness-critical**; the LLM-output safety gate + claim schema | agent-generated | Octavius | strict |
| Verifier tests (`backend/tests/test_verifier.py`) — 100% branch cov; each claim type passes/fails with correction | agent-generated | Octavius | strict |
| Ingestion parsers (`scripts/ingest/parsers.py`) — self-owned SOC/Catalog/FCE + prereq-text parser | agent-generated | Octavius | reviewed |
| Ingestion orchestrator + CLI (`scripts/ingest/ingest.py`, `scripts/ingest/cli.py`) — dry-run/live, JSON writer | agent-generated | Octavius | reviewed |
| Ingestion fixtures (`data/fixtures/soc_sample.html`, `catalog_sample.html`, `fce_sample.csv`) | agent-generated | Octavius | skim |
| Ingestion README (`scripts/ingest/README.md`) — sources, self-owned rationale, manual-FCE caveat, refresh | agent-generated | Octavius | skim |
| Ingestion fixture test (`backend/tests/test_ingest.py`) — dry-run → valid models, round-trips JSON | agent-generated | Octavius | reviewed |
| Deps + test path for ingestion (`backend/pyproject.toml`: +httpx, +beautifulsoup4, pytest `pythonpath`) | agent-generated | Octavius | skim |
| API endpoints (`backend/app/main.py`) — `/survey`, `/recommend`, `/confirm`; wires classify→solve→rank, cascade loop, no LLM | agent-generated | Octavius | reviewed |
| API integration tests (`backend/tests/test_api.py`) — shapes + cascade (confirming a prereq unlocks a course) | agent-generated | Octavius | reviewed |
| LLM orchestrator (`backend/app/orchestrator.py`) — **correctness-critical**; enforces the verifier safety gate, stub fallback | agent-generated | Octavius | strict |
| Orchestrator tests (`backend/tests/test_orchestrator.py`) — stub claims verify; wrong LLM claim caught & stripped | agent-generated | Octavius | strict |
| `/ask` endpoint + router (`backend/app/main.py`) — structured/semantic routing, verified LLM results | agent-generated | Octavius | reviewed |
| `/ask` tests (`backend/tests/test_api.py`) — stub route returns only verified claims | agent-generated | Octavius | reviewed |
| `anthropic` optional dep (`backend/pyproject.toml`: `[llm]` extra) | agent-generated | Octavius | skim |
| Frontend app (`frontend/`) — Vite + React + TS: survey, prereq checklist, chat (`/ask`), week-grid | agent-generated | Octavius | reviewed |
| CORS + lint config (`backend/app/main.py` CORS middleware, `backend/pyproject.toml` ruff) | agent-generated | Octavius | skim |
| README + run instructions (`README.md`) — architecture summary, clone→devcontainer→run→test | agent-generated | Octavius | reviewed |
| Makefile (`Makefile`) — dev / test / lint / ingest targets | agent-generated | Octavius | skim |
| CI workflow (`.github/workflows/backend-tests.yml`) — `uv run pytest` on push, no secrets | agent-generated | Octavius | reviewed |
| Bugfix: exclude completed courses from the candidate pool (`backend/app/main.py` `_solve_for`) + tests (`backend/tests/test_api.py`) — completed courses satisfy prereqs but are never re-recommended | agent-generated | Octavius | reviewed |
| Curated CS degree requirements (`data/samples/computer-science.json`) — hand-curated, carries a not-an-audit disclaimer | human-written | Octavius | reviewed |
| Requirements models + `remaining_requirements` (`backend/app/requirements.py`) — **correctness-relevant** (a wrong "satisfied" misleads graduation planning); evaluates all/pick_n/pick_min_units/pick_n_min_units_each/units, sequence_alternatives, exclusions | agent-generated | Octavius | strict |
| Requirements loader (`backend/app/requirements_loader.py`) — **correctness-relevant**; loads + validates per-rule fields | agent-generated | Octavius | strict |
| Requirements tests (`backend/tests/test_requirements.py`) — 100% branch cov; every rule type, partial pick_min_units, sequence case, ranking signal | agent-generated | Octavius | strict |
| Solver `value_bonus` param (`backend/app/solver.py`) — additive optional ranking signal; default preserves prior tested behavior | agent-generated | Octavius | reviewed |
| Requirement-bias wiring + response fields (`backend/app/main.py`) — `/recommend` & `/ask` bias ranking, surface `disclaimer` + per-schedule `requirements_advanced` | agent-generated | Octavius | reviewed |
| Requirement API tests (`backend/tests/test_api.py`) — disclaimer surfaced, advanced groups present, completed-course regression | agent-generated | Octavius | reviewed |
| Frontend requirement/disclaimer surfacing (`frontend/src`) — advanced-group chips + disclaimer banner | agent-generated | Octavius | skim |

<!--
Each build stage appends its rows below this line. Keep entries in stage order.
Correctness-critical modules (prereq classifier, solver, verifier, orchestrator) MUST be
marked `strict`. Replace <YOUR NAME> with real reviewers. Keep this consistent with git
history — a reviewer may cross-check commits against this log.
-->

---

## Closing note

_(Added at Stage 8.)_ This log was maintained incrementally, one block per build stage.
All correctness-critical modules — the prerequisite classifier, the constraint solver, the
claim verifier, and the LLM orchestrator — received `strict` review (line-by-line plus
tests). Origins and review depths reflect what the team actually did at each stage.
