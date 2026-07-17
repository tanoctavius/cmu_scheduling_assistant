# Code Provenance Log

This log records the origin and review of every module in the repository, maintained
**per-stage as the code was built** (not reconstructed afterward). It exists to make clear
what was human-written vs. agent-generated, and what review each piece received.

Most of this code was written by an AI agent. That is stated plainly here and in
[`docs/ai-use.md`](docs/ai-use.md), which maps each part of the system to the mode we were
working in (Operator/Agent vs. Critic). This log is the per-artifact register; §2 below is the
part that matters most for accountability.

**Two kinds of evidence live here:**

1. **§1 The log** — who wrote and reviewed each artifact, and how deeply. This is an
   *attestation*: it records what the named reviewer says they did.
2. **§2 How the correctness-critical modules work** — our own explanation, in our own words, of
   what each critical module does and how. This is *demonstrable*: it can be checked against
   the code, and it is the evidence that we can explain what the agent wrote rather than merely
   possessing it.

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
    (prereq classifier, solver, verifier, orchestrator, requirements logic).

> Convention: no agent-generated code is considered done without a named reviewer.
> Correctness-critical modules must be `strict` **and** must appear in §2.

**Contributors:** Octavius (`tanoctavius`) — direction, review, and the stage-by-stage Critic
passes; Ite (`IIbitoye`) — Learner Lab deployment; Wendy (`gwenlli`) — architecture diagram.

**Cross-check against git.** The Operator/Agent → Critic loop is visible in the commit log:
every `Stage N` commit is agent output, and the commits between them (`checked through Claude
outputs`, `reviewed outputs from phase 1`, `verified testing for phase 4`, …) are review passes.
`828eaa1` adds to this log mid-stage — evidence it was kept during the build, not written at the
end. The full transcript is quoted in [`docs/ai-use.md`](docs/ai-use.md) §3.

---

## 1. Log

| Artifact | Origin | Reviewer | Review type |
|---|---|---|---|
| Repo skeleton (`backend/`, `frontend/`, `data/`, `docs/`, `scripts/`, `pyproject.toml`, `.gitignore`) | agent-generated | Octavius | skim |
| Devcontainer (`.devcontainer/devcontainer.json`, `.devcontainer/Dockerfile`) | agent-generated | Octavius | skim |
| README + conventions (`README.md`, `docs/CONTRIBUTING.md`) | agent-generated | Octavius | skim |
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
| `/ask` endpoint + router (`backend/app/main.py`) — structured/semantic routing, verified LLM results | agent-generated | Octavius | reviewed | <!-- REMOVED later: Part 4 deleted; superseded by `/chat`, see below -->
| `/ask` tests (`backend/tests/test_api.py`) — stub route returns only verified claims | agent-generated | Octavius | reviewed | <!-- REMOVED later with `/ask` -->
| `anthropic` optional dep (`backend/pyproject.toml`: `[llm]` extra) | agent-generated | Octavius | skim | <!-- removed later: superseded by the provider abstraction, see below -->
| Frontend app (`frontend/`) — Vite + React + TS: survey, prereq checklist, chat (`/ask`), week-grid | agent-generated | Octavius | reviewed | <!-- ChatBox (Part 4) REMOVED later; chat now lives in the Part 3 workspace -->
| CORS + lint config (`backend/app/main.py` CORS middleware, `backend/pyproject.toml` ruff) | agent-generated | Octavius | skim |
| README + run instructions (`README.md`) — architecture summary, clone→devcontainer→run→test | agent-generated | Octavius | reviewed |
| Makefile (`Makefile`) — dev / test / lint / ingest targets | agent-generated | Octavius | skim |
| CI workflow (`.github/workflows/backend-tests.yml`) — `uv run pytest` on push, no secrets | agent-generated | Octavius | reviewed |
| Bugfix: exclude completed courses from the candidate pool (`backend/app/main.py` `_solve_for`) + tests (`backend/tests/test_api.py`) — completed courses satisfy prereqs but are never re-recommended | agent-generated | Octavius | reviewed |
| Curated CS degree requirements (`data/samples/computer-science.json`) — hand-curated from the CS degree page, carries a not-an-audit disclaimer | human-written | Octavius | reviewed |
| Requirements models + `remaining_requirements` (`backend/app/requirements.py`) — **correctness-relevant** (a wrong "satisfied" misleads graduation planning); evaluates all/pick_n/pick_min_units/pick_n_min_units_each/units, sequence_alternatives, exclusions | agent-generated | Octavius | strict |
| Requirements loader (`backend/app/requirements_loader.py`) — **correctness-relevant**; loads + validates per-rule fields | agent-generated | Octavius | strict |
| Requirements tests (`backend/tests/test_requirements.py`) — 100% branch cov; every rule type, partial pick_min_units, sequence case, ranking signal | agent-generated | Octavius | strict |
| Solver `value_bonus` param (`backend/app/solver.py`) — additive optional ranking signal; default preserves prior tested behavior | agent-generated | Octavius | reviewed |
| Requirement-bias wiring + response fields (`backend/app/main.py`) — `/recommend` & `/ask` bias ranking, surface `disclaimer` + per-schedule `requirements_advanced` | agent-generated | Octavius | reviewed |
| Requirement API tests (`backend/tests/test_api.py`) — disclaimer surfaced, advanced groups present, completed-course regression | agent-generated | Octavius | reviewed |
| Frontend requirement/disclaimer surfacing (`frontend/src`) — advanced-group chips + disclaimer banner | agent-generated | Octavius | skim |
| Checklist source (`backend/app/checklist.py`) — single `checklist_courses(major, catalog, requirements)`; scope = all-rule core + prereq-graph courses, grouped | agent-generated | Octavius | reviewed |
| Checklist tests (`backend/tests/test_checklist.py`) — core appear, prereq appears, non-core/non-prereq excluded, dedup, focused size | agent-generated | Octavius | reviewed |
| Survey checklist rework (`backend/app/main.py` `/survey` + `SurveyResponse`; replaces foundation) + test (`backend/tests/test_api.py`) — grouped checklist; ticking still feeds classifier/cascade and excludes completed | agent-generated | Octavius | reviewed |
| Frontend grouped checklist (`frontend/src`) — headered sections, wider upfront confirmation | agent-generated | Octavius | skim |
| Interactive prereq-confirmation panel (`frontend/src/components/ConfirmationPanel.tsx`, `SchedulePanel.tsx`, `api.ts`, `types.ts`, `App.tsx`, `ChatBox.tsx`, `styles.css`) — moves prereq confirmation out of the chat answer into per-prereq Yes/No toggles beside the week-grid; each answer calls `/confirm` and re-solves the cascade in place (loading overlay), driving the deterministic classifier/solver path — **never the LLM** | agent-generated | Octavius | reviewed |
| Confirm-updates-schedule test (`backend/tests/test_api.py::test_confirm_answer_updates_returned_schedule`) — answering a confirmation control changes the returned schedule's calendar (dependent leaves every schedule when its prereq is ruled out) | agent-generated | Octavius | reviewed |
| **LLM provider abstraction** (`backend/app/llm_provider.py`) — **correctness-critical**; single `LLMProvider.generate(messages, response_schema)` interface, runtime selection from `LLM_PROVIDER`, `StubProvider` (offline default) + `GroqProvider` (OpenAI-compatible HTTPS, no Bedrock/IAM). All keys, base URLs, model names from env — none in code. Providers are stateless and constructed per call (clean cold start under the Learner Lab session timer) | agent-generated | Octavius | strict |
| **Verifier-gate integration across providers** (`backend/app/orchestrator.py`) — **correctness-critical**; orchestrator rewritten to depend only on the provider interface (Anthropic-specific backend removed). The gate sits downstream of every provider, so the deterministic safety guarantee is provider-independent and unchanged | agent + human-revised | Octavius | strict |
| **Provider + gate tests** (`backend/tests/test_llm_provider.py`, `backend/tests/test_orchestrator.py`) — **correctness-critical**; stub makes no network call (sockets blocked) and returns the right shape, `groq` selected via `LLM_PROVIDER` with the HTTP call mocked (no real key), and the *same* false claim is stripped for two different providers | agent-generated | Octavius | strict |
| Provider selection at the API boundary (`backend/tests/test_api.py`) — the chat path reports the env-selected provider and still strips its false claim (was `/ask`; now `test_chat_uses_the_provider_named_by_env_and_still_verifies`) | agent-generated | Octavius | reviewed |
| Provider config + docs (`backend/.env.example`, `README.md`, `.github/workflows/backend-tests.yml`, `backend/pyproject.toml`) — documents every env var, drops the unused `anthropic` extra; CI runs on the stub with no secrets. Verified `.gitignore` keeps real `.env` out and `.env.example` in | agent-generated | Octavius | reviewed |
| Bedrock assumption retired (`docs/project-context.md` §5, §6) — records *why* the original "LLM serving = Amazon Bedrock" choice was replaced (Learner Lab: no IAM role creation, region limits, ~4h timer, Bedrock possibly unavailable) and what it costs | human-written | Octavius | reviewed |
| Bugfix: duplicate schedules (`backend/app/solver.py` `schedule_key` + dedupe in `consider`) — **correctness-critical**; the DFS re-offered the same section set at every skip node, so the top-K heap filled with copies and 4 of 5 "options" were identical. Deduped at the source, keyed on the section set at its times | agent-generated | Octavius | strict |
| Dedup tests (`backend/tests/test_solver.py`) — **correctness-critical**; property-style "no two returned schedules identical" over 200 random scenarios, all-subsets-distinct case, and times (not just course numbers) key the identity | agent-generated | Octavius | strict |
| **Chat → solver translation** (`backend/app/orchestrator.py`: `ScheduleConstraints`, `constraints_to_solver_inputs`, `orchestrate_chat_turn`) — **correctness-critical, strict**: a modification request that bypassed the solver or the verifier would break the core safety guarantee. The LLM may only classify intent and fill a closed constraint vocabulary; constraints become ordinary solver inputs (units cap, commitment blocks, exclusions) so the solver's tested invariants apply unchanged, and every claim still passes the verifier. No field lets a model place or edit a section | agent + human-revised | Octavius | strict |
| Chat/translation tests (`backend/tests/test_orchestrator.py`) — **correctness-critical**; constraint→solver mapping, cap can never be raised, base commitments never dropped, context accumulates across turns, and the same false claim is stripped for two different providers | agent-generated | Octavius | strict |
| Deterministic rationale (`backend/app/rationale.py`) — **correctness-critical**; derives claims from the solved schedule and returns only those that PASS `verify`. The panel's green checkmarks are verifier outputs, never LLM prose; LLM-free so it costs no API call and reads identically under every provider | agent-generated | Octavius | strict |
| `/chat` endpoint + rationale wiring (`backend/app/main.py`) — replaces `/ask`; question turns leave the calendar untouched, modification turns re-solve, unsatisfiable requests keep the previous calendar rather than emptying it. Conversation state is client-held (no server session) | agent-generated | Octavius | reviewed |
| `/chat` API tests (`backend/tests/test_api.py`) — question returns verified info without changing the schedule; modification yields a genuinely different, verified, independently-checked conflict-free schedule; context retained across turns; provider-selected path still gated | agent-generated | Octavius | reviewed |
| Stub chat turn (`backend/app/llm_provider.py` `StubProvider`, `_stub_constraints`) — deterministic keyword intent/constraint proposal so the chat is demoable and testable with no key and no network. Shallow by design: like every provider it can only propose, never schedule | agent-generated | Octavius | reviewed |
| Part 4 removed (`frontend/src/components/ChatBox.tsx` deleted, `/ask` route + `AskRequest`/`AskResult`/`AskResponse` + keyword router deleted, `/ask` tests deleted) — verified no remaining dependency; full suite green after deletion | agent-generated | Octavius | reviewed |
| Part 3 workspace (`frontend/src/components/SchedulePanel.tsx`, `RationalePanel.tsx`, `ChatThread.tsx`, `App.tsx`, `api.ts`, `types.ts`, `styles.css`) — calendar beside a right-hand panel carrying the rationale + verifier checkmarks + prereq confirmation controls, with the iterative chat below. Rationale follows the selected schedule | agent-generated | Octavius | reviewed |
| **Learner Lab deploy scripts + guide** (`deploy/user-data.sh`, `deploy/update.sh`, `docs/deployment.md`) — one-shot EC2 provisioning (Node/uv/clone/build + three systemd units) and the boot-time IP refresh that makes the changing public IP a non-issue. **Not agent output** — authored by Ite, merged via PR #1 (`415b7ea`) | human-written | Ite | reviewed (PR) |
| **Architecture diagram** (`docs/architecture.svg`) — hand-drawn system sketch (`1f4b408`). Depicts the *target* design; see `docs/architecture.md` §8 for where it now differs from the build | human-written | Wendy | skim |
| Architecture narrative (`docs/architecture.md`) — what we built, which cloud services, why those choices, and what we designed but did not build. Claims verified against the repo (no `boto3` anywhere; `/recommend` + `/confirm` return full rationales with the provider rigged to raise) | agent-generated | Octavius | reviewed |
| AI-use account (`docs/ai-use.md`) — maps each part of the system to Operator/Agent vs. Critic, with the git-history evidence and three defects the Critic pass actually caught | agent-generated | Octavius | reviewed |
| Repo reorganization (docs moved to `docs/`; root reduced to `README.md` + `PROVENANCE.md`; README slimmed to what-it-is + run + one-paragraph architecture + links) — documentation only, no code touched; full suite re-run after | agent-generated | Octavius | reviewed |
| Devcontainer fix (`.devcontainer/devcontainer.json` `postCreateCommand`) — also installs frontend deps and seeds `frontend/.env`. Previously the README told devcontainer users to skip `make install`, so `make frontend` failed on a fresh clone with no `node_modules` | agent-generated | Octavius | reviewed |

<!--
Each build stage appends its rows below this line. Keep entries in stage order.
Correctness-critical modules (prereq classifier, solver, verifier, orchestrator,
requirements logic) MUST be marked `strict` AND get an entry in §2. Keep this consistent
with git history — a reviewer may cross-check commits against this log.
-->

---

## 2. How the correctness-critical modules work

An agent wrote these modules. The point of this section is to show we understand what it
wrote. Each entry is our own explanation — what the module is for, the mechanism it uses, and
the one design decision that matters most. Every claim here is checkable against the code.

### 2.1 Prereq classifier — `backend/app/prereq.py`

**What it does.** Puts every candidate course into exactly one of three states: `eligible`,
`unconfirmed`, or `blocked`.

**How it works.** Prerequisites are an AND/OR tree, not a flat list, because real CMU prereqs
nest ("21-127 AND (15-112 OR 15-122)"). The module evaluates that tree with **three-valued
(Kleene) logic**. A leaf course is TRUE if it's in the confirmed `completed` set, FALSE if it's
in `ruled_out` (the student answered "No"), and **UNKNOWN otherwise**. The connectives combine
three-valued: an AND is FALSE if any operand is FALSE, otherwise UNKNOWN if any operand is
UNKNOWN, otherwise TRUE; an OR is TRUE if any operand is TRUE, otherwise UNKNOWN if any is
UNKNOWN, otherwise FALSE. A `PrereqUnparsed` node — prereq text ingestion couldn't parse —
evaluates to UNKNOWN by construction. The final mapping is trivial: TRUE → eligible, FALSE →
blocked, UNKNOWN → unconfirmed.

**The decision that matters.** `blocked` requires *positive* knowledge that a prereq is unmet,
and a completed-set alone can never establish that — a course you haven't confirmed might still
have been taken. That knowledge only ever arrives from the confirmation loop, via `ruled_out`.
This is what makes the safety rule fall out of the design rather than being bolted on: missing
or unparseable data lands in UNKNOWN, so it becomes `unconfirmed`, never `blocked`. **The
failure mode is an extra question, never a hidden course.**

`missing_prereqs()` powers the confirmation controls: it walks the branches that aren't
satisfied and collects their course numbers, order-preserving and de-duplicated. It prunes
satisfied disjuncts — once one OR alternative holds, its siblings aren't "needed", so we don't
ask about them.

### 2.2 Fused solver + ranking — `backend/app/solver.py`, `ranking.py`

**What it does.** Returns up to K valid schedules, best-ranked first. Valid means: at most one
section per course, no two sections overlapping, every commitment respected, total units under
the cap, and no `blocked` course present.

**How it works.** It does *not* enumerate schedules and sort them — recitations make that space
explode. It's a **depth-first branch-and-bound**: at each course, either skip it or take one of
its sections, scoring incrementally. Complete schedules go into a **bounded min-heap of size
K**, so only the best K are ever retained.

The pruning is the clever part, and it's only sound because of a specific property. The ranking
score is **additive over courses** (`ranking.course_value` per course, plus an optional
`value_bonus`), so for the courses not yet decided we can compute `suffix[i]` = the sum of
`max(0, value)` over the rest. That's an **admissible upper bound**: no completion can score
higher, because taking a course adds at most its own value and we can always skip. Once the
heap is full, any subtree whose `score + suffix[index]` can't beat the current K-th best is
abandoned. The `max(0, ...)` matters — a negatively-valued course must contribute 0 to the
bound, not a negative number, or the bound would stop being admissible and we'd prune correct
answers.

Overlap uses a **half-open** interval test (`a_start < b_end and b_start < a_end`), so a class
ending at 10:50 and one starting at 10:50 don't conflict. Commitments are just intervals, which
is why chat constraints can reuse them (§2.4).

**The decision that matters — and the bug it hid.** `consider()` is called at *every* DFS node,
including each "skip" step, so the same chosen section set is offered many times over. We
originally let those all through, and the K-heap filled with **copies of the same schedule** —
four of five "options" were byte-identical. The fix is `schedule_key()` (course, section, days,
begin, end — sorted, so order-independent) plus a `seen` set, de-duplicating **at the source**
so the K slots hold K genuinely distinct options. First-offer-wins is safe precisely because
the score is additive over the chosen set: the same key always carries the same score.

### 2.3 Claim verifier — `backend/app/verifier.py`

**What it does.** It is the gate. Nothing factual reaches the student without passing through
it. Given a list of claims and the real schedule, it returns which claims are true.

**How it works.** A claim is a small tagged JSON object, validated as a discriminated union on
`type`: `no_class_on{day}`, `total_units{value}`, `includes_course{course_num}`,
`no_conflicts`. `verify()` re-derives each fact from the actual schedule and returns one
`ClaimCheck` per claim, carrying `ok`, a `corrected_value` measured from the schedule, and a
human-readable message. `passed_claims` / `failed_checks` / `all_passed` let callers keep the
survivors and drop the rest.

**The decision that matters.** A claim that is *well-formed but unrecognized* — one the verifier
doesn't know how to check — is treated as **failed**, not passed. Unverifiable is not the same
as true. A gate that defaulted to "allow" for claims it didn't understand would be no gate at
all, since that's exactly the case a novel model output would hit.

The same gate serves both callers: LLM claims from the chat (§2.4), and the claims the rationale
derives from the schedule itself (§2.6). Provider choice cannot change what is checked.

### 2.4 Orchestrator: the chat turn and the chat→solver translation — `backend/app/orchestrator.py`

**What it does.** This is the only place a language model touches the pipeline. It gets one
chat turn's worth of work out of the model and then throws away anything it can't verify.

**How it works.** The model is asked for a `ChatTurn`: a `kind` (`question` or `modification`),
a `reply`, a `ScheduleConstraints`, and any `claims`. Its authority stops there. Constraints are
a **closed vocabulary** — `avoid_days`, `max_units`, `no_class_before`, `no_class_after`,
`exclude_courses` — and the model returns the *full* set that should hold after this turn, not a
delta, which is what lets follow-ups accumulate ("make it lighter", then "also no Fridays")
without the client merging anything.

`constraints_to_solver_inputs()` is the translation, and it's pure and total. Time-based wishes
become **ordinary commitment blocks**: `avoid_days: [F]` becomes a Friday block from 00:00 to
23:59; `no_class_after: 12:00` becomes a 12:00–23:59 block across every weekday. `max_units`
becomes the units cap; `exclude_courses` filters the candidate pool.

**The decision that matters.** Reusing commitments means the solver needs **no new code path**
for the chat. Every invariant it already has tests for — no conflicts, commitments respected,
cap honored — applies to a chat-modified schedule automatically. And the cap is clamped with
`min(default, requested)`, so a student can ask for a lighter load but never an overload past
the institutional ceiling.

The structural guarantee is what's absent: **there is no field in which a model can say "put
15-213 at 9am"**. It can only hand the solver a differently-shaped question. The worst a bad
proposal can do is produce a valid schedule the student didn't want — never an invalid or
fabricated one. Claims are then verified against the schedule actually on screen; if there's no
schedule, no claim can be presented as verified.

### 2.5 Requirements logic — `backend/app/requirements.py`, `requirements_loader.py`

**What it does.** Evaluates a curated degree-requirements file against a student's completed
courses to say which groups are still unmet, and biases the ranking toward courses that advance
them.

**How it works.** Five rule types cover the CS degree: `all` (every listed course), `pick_n`
(choose n), `pick_min_units` (courses totalling ≥ units), `pick_n_min_units_each` (n courses
each ≥ some units from an *open pool* — SCS departments at 200-level or above, honoring an
exclusion list), and `units` (≥ N units from a pool we deliberately never enumerate, e.g.
GenEd). A group may also carry `sequence_alternatives`: any one listed sequence, completed in
full, satisfies the group by itself. The loader validates that each group carries the fields its
rule actually needs, so a malformed curation fails at startup rather than silently mis-evaluating.

The ranking signal is additive and deliberately weak: `requirement_bonus` yields `W_REQUIREMENT
= 0.8`, multiplied by `UNSTARTED_MULTIPLIER = 1.5` for groups not yet begun (to spread progress
rather than finish one group). It's passed to the solver as `value_bonus` and layered on the
FCE/interest score — it **biases, it doesn't dictate**, so a strong elective still competes.

**The decision that matters.** This module is where it would be easiest to lie helpfully. A
wrong "requirement satisfied" misleads someone's graduation plan, so when unit data is missing
or an open pool makes satisfaction genuinely unknown, it reports **not satisfied / open-ended
rather than guessing "done"**. The curated file carries an explicit `disclaimer` that this is
not an official audit, and that disclaimer is surfaced through the API to the UI rather than
buried. (`DEFAULT_COURSE_UNITS = 9.0` for a completed course we can't look up is a documented
simplification, not a hidden assumption.)

### 2.6 Deterministic rationale — `backend/app/rationale.py`

**What it does.** Produces the right-hand panel's content: why a schedule was built, plus the
green ✓ chips.

**How it works.** It derives the candidate claims *from the solved schedule itself* —
`total_units` from the totals, `no_conflicts`, an `includes_course` per course, a `no_class_on`
per free day — and then runs every one of them through `verify()` against that same schedule,
returning only the ones that pass.

**The decision that matters.** Running self-derived claims through the verifier looks redundant
and isn't. The totals come from the solver's *cached* fields; if those ever drifted from the
sections actually on the schedule, the verifier catches it and strips the claim rather than
showing a student a wrong number. `stripped_claim_count` is surfaced in the UI for exactly that
reason — a non-zero value is a bug signal, not a normal state.

Keeping this path LLM-free is also what makes it fast enough to re-render on every prereq
toggle, and why the panel reads identically whether `LLM_PROVIDER` is `stub` or `groq`.

---

## 3. Closing note

_(Started at Stage 8; §2 added during the provenance-strengthening pass.)_ This log was
maintained incrementally, one block per build stage — `828eaa1` adds to it mid-build, and the
alternating agent/review commit pattern in [`docs/ai-use.md`](docs/ai-use.md) §3 corroborates
it. All correctness-critical modules — the prerequisite classifier, the constraint solver, the
claim verifier, the orchestrator (including the chat→solver translation), the requirements
logic, and the rationale — are marked `strict` and are explained in §2.

Two honest caveats, because a provenance log that only reassures is not doing its job:

- **`strict` is an attestation.** Nothing in the repo can prove how deeply a human read a
  file. §2 exists as the evidence we can actually offer: explanations that are checkable
  against the code. The defects we caught are listed in [`docs/ai-use.md`](docs/ai-use.md) §4.
- **The agent wrote the tests for the code the agent wrote.** The duplicate-schedule bug
  (§2.2) passed hundreds of agent-written property tests and shipped anyway; it was caught by a
  human looking at the UI. Agent-generated coverage does not substitute for a person checking
  the output against what the product is for.
