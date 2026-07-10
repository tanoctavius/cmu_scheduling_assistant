# Contributing

Short version of the conventions — see the [README](README.md#conventions) and
[`project_context.md`](project_context.md) for the full picture.

## Branches

`type/short-description` — e.g. `feat/solver-branch-bound`, `fix/prereq-parse`.
Types: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`.

## Commits

Imperative, present tense, [Conventional Commits](https://www.conventionalcommits.org/)
preferred: `feat: add branch-and-bound solver`. Subject under ~72 chars.

## Tests

- Live in `backend/tests/`, named `test_*.py`, run with `uv run pytest` from `backend/`.
- **The deterministic core requires tests — no exceptions.** The prerequisite
  **classifier**, the constraint **solver**, and the claim **verifier** are
  correctness-critical; a change to any of them is not done without tests. These two must
  always pass:
  1. missing/unparseable prereq data → `unconfirmed`, never `blocked`;
  2. a wrong LLM claim is caught by the verifier and never reaches output.

## Ground rules

- Everything runs without secrets: fixtures for ingestion, a stub LLM fallback for tests.
- No secrets committed — API keys live in env vars only.
- The LLM never originates schedule data; the solver builds schedules, the LLM explains.
- Build order: deterministic, testable pieces first; LLM and cloud last.
- Record each change in [`PROVENANCE.md`](PROVENANCE.md); correctness-critical modules need
  a named reviewer and `strict` review.
