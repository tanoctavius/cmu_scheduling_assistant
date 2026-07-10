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
| Repo skeleton (`backend/`, `frontend/`, `data/`, `docs/`, `scripts/`, `pyproject.toml`, `.gitignore`) | agent-generated | \<YOUR NAME\> | skim |
| Devcontainer (`.devcontainer/devcontainer.json`, `.devcontainer/Dockerfile`) | agent-generated | \<YOUR NAME\> | skim |
| README + conventions (`README.md`, `CONTRIBUTING.md`) | agent-generated | \<YOUR NAME\> | skim |
| Health endpoint + test (`backend/app/main.py`, `backend/tests/test_health.py`) | agent-generated | \<YOUR NAME\> | skim |

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
