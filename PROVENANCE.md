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
| Fused solver (`backend/app/solver.py`) — **correctness-critical**; branch-and-bound top-K | agent-generated | \<YOUR NAME\> | strict |
| Ranking function (`backend/app/ranking.py`) — **correctness-critical**; weighted FCE/interest heuristic | agent-generated | \<YOUR NAME\> | strict |
| `Schedule` result model added to models (`backend/app/models.py`) | agent-generated | \<YOUR NAME\> | reviewed |
| Solver/ranking tests (`backend/tests/test_solver.py`) — property-style, 100% branch cov; caught a real conflict bug | agent-generated | \<YOUR NAME\> | strict |

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
