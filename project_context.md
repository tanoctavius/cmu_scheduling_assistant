# CMU Course Scheduler — Project Context

> A single reference for anyone joining this project — teammates, reviewers, or an AI
> coding assistant. Read this before writing code. It captures **what** we're building,
> **why** the architecture is shaped the way it is, and **which decisions are already
> locked in** so they don't get re-litigated mid-build.

---

## 1. What we're building

A **conversational course-scheduling assistant for CMU students.** A student fills out a
short survey (major, expected graduation, courses already taken, fixed outside
commitments, and optional interests or career goals), then converses with the system to
receive **conflict-free, requirement-satisfying schedules ranked by predicted fit**, each
explained in plain language with citations to real course sections.

It is two features working as one product:

1. **Schedule generation** — produce valid, buildable schedules that respect time
   conflicts, prerequisites, unit caps, and the student's outside commitments.
2. **Conversational recommendation** — help the student choose among valid schedules
   using their interests, workload tolerance, and goals, and explain the reasoning.

The target user is a CMU undergrad planning a semester. The value is a *correct* schedule
they can actually register for, plus guidance on which of the valid options fits them best.

---

## 2. The one architectural idea that matters most

**Hard scheduling logic is deterministic. The language model only explains and ranks what
the solver has already validated. The LLM never places classes or invents schedule data.**

This split is the spine of the whole system, so it's worth stating why:

- If an LLM were allowed to build schedules directly, it would occasionally invent a
  section that doesn't exist, violate a prerequisite, or double-book the student against a
  commitment it was told about. For a tool whose entire value is a *correct* schedule,
  those failures are disqualifying.
- So a **deterministic solver** produces only valid schedules, and the **LLM** is confined
  to what it's actually good at: retrieval, ranking against fuzzy preferences, and
  explanation.
- A **deterministic verifier** then checks every factual claim the LLM makes about a
  schedule before it reaches the student.

If you remember one thing from this document, remember this split. Most of the design
decisions below follow from it.

---

## 3. Prerequisites: the three-state model

We can't reliably know a student's full transcript, so the system **never silently assumes
prerequisites are met, and never silently hides courses.** It handles prereqs in two
moments:

- **Upfront checklist** — after the student picks a major, we show that major's foundation
  courses to tick off. Tapping, not typing, seeds a confirmed "completed" set.
- **Per-recommendation confirmation** — any recommended course whose prereqs aren't
  confirmed is surfaced *with the gap named*: "This looks like a strong fit — it requires
  21-127. Have you taken it?" The answer feeds back and re-solves.

Every candidate course is therefore in one of **three states**:

| State | Meaning | Behavior |
|---|---|---|
| **Eligible** | Every prereq is in the confirmed completed set | Scheduled freely, no caveat |
| **Unconfirmed** | Prereq status unknown (not confirmed, not ruled out) | Recommended *conditionally*, carries a confirmation question |
| **Blocked** | A prereq is confirmed *unmet* with no alternative | Excluded, but shown with an "unlocks once you take X" hint |

**Safety rule (non-negotiable):** when prereq data is missing or unparseable, a course
defaults to **`unconfirmed`, never `blocked`.** The failure mode must be an extra question,
never a hidden course. This also makes the confirmation loop double as graceful
degradation when data quality is poor.

A "yes" to a confirmation question promotes a course's dependents from unconfirmed to
eligible and triggers a re-solve — which can **cascade** to unlock further courses. That
loop is a real data path, not just UI copy.

---

## 4. Data & ingestion — we parse it ourselves

**Decision: we scrape and parse CMU course data ourselves, the same way ScottyLabs does.
We do NOT depend on any external or hosted API.**

Context for this decision:

- There is **no official hosted CMU or ScottyLabs API** we can rely on. The
  `cmu_course_api` PyPI package exists but was **last updated in 2019**; its
  DOM-position-dependent parsers are stale against today's pages. The ScottyLabs
  `cmucourses` repo is a full web app (Next.js + Express + Mongo), not a callable API.
- So ingestion is **self-owned**: we write our own scrapers/parsers against the official
  CMU sources. We may read the old `cmu_course_api` parsers as a *reference* for where the
  data lives and how it's shaped, but we assume none of its selectors still work and we
  write our own.

Why this is the right call (and how to frame it to reviewers):
- No dependency on anyone else's uptime or an abandoned endpoint.
- When CMU redesigns a page, it's a parser fix on our side — under our control — not an
  outage we can't fix.
- It's the most defensible position for a graded project: the pipeline depends on nothing
  that can silently rot.

**Sources we parse ourselves:**
- **Schedule of Classes** — sections, meeting days/times, units, locations. (The SOC PDF
  layout is fixed and parses cleanly; the SOC servlet is the structured source.)
- **Course Catalog** (`coursecatalog.web.cmu.edu`) — prerequisites and course descriptions.
- **FCE data** — workload hours/week and ratings. The FCE portal is auth-gated, so v1 uses
  a **manual CSV export**; this is a stated limitation, not a hidden assumption.

**Ingestion engineering rules:**
- Ingestion runs as **scheduled batch work, off the request path.**
- Parsed output must conform to our own normalized data models, identical in shape to our
  sample fixtures — so downstream code never cares whether data came from a sample or a
  live scrape.
- Ingestion must support a **fixture/dry-run mode** that parses a committed local
  HTML/PDF sample instead of hitting the network, so tests and CI never depend on CMU's
  site being up.
- Document sources, the manual-FCE caveat, and how to refresh, in the ingestion README.

---

## 5. Component overview

Six layers, top (ingestion) to bottom (interface):

1. **Source scrapers (self-hosted)** — parse SOC + Course Catalog (prereqs, descriptions)
   + FCE directly from official CMU sources into our normalized models. No external API.
2. **Catalog store** — single normalized source of truth: sections, meeting times, the
   prerequisite graph, FCE stats, seat status. (AWS: DynamoDB — access is key-based
   lookups, not relational joins.)
3. **Query router** — sends structured questions (requirements, prereqs, conflicts) to the
   database; sends only fuzzy questions (interests, review tone) to semantic retrieval.
   This prevents using vector search where it would give confident-but-wrong answers.
4. **Fused solver (classify + solve + rank)** — deterministic. Classifies each course
   eligible/unconfirmed/blocked, then branch-and-bound solves and ranks to the **top-K**
   feasible schedules. Does *not* enumerate all schedules (recitations explode the space);
   it prunes with the ranking score as the bound.
5. **LLM orchestrator** — explains the top-K, ranks by fit, cites real sections, attaches
   prereq-confirmation questions. Emits factual claims in a structured format for the
   verifier. (AWS: Amazon Bedrock — keeps the model call inside the same IAM/security
   boundary.)
6. **Claim verifier** — deterministic gate. Re-checks every factual claim (days off, unit
   totals, no conflicts) against the solver's actual output before it reaches the student.
   Failed claims are stripped or regenerated.

Plus the **interface**: survey + prereq checklist, and a chat UI with a week-grid schedule
view, swap mode, and multi-semester planning.

---

## 6. Cloud (AWS) at a glance

Serverless-first, because a scheduling tool spikes hard at registration and is quiet
otherwise — near-ideal for pay-per-use.

| Concern | Service | Why |
|---|---|---|
| Batch ingestion | Lambda + EventBridge | Spiky, infrequent; no always-on server needed |
| Raw scraped artifacts | S3 | Cheap, durable, audit trail of what was ingested when |
| Catalog store | DynamoDB | Key-based lookups, single-digit-ms reads |
| Semantic retrieval | OpenSearch Serverless | Vector search without running our own DB |
| LLM serving | Amazon Bedrock | Model call inside our AWS IAM/security boundary |
| Request path | Lambda (or Fargate) | Scales per-user; Fargate if solve times grow |
| Front end | CloudFront + S3 | Static hosting |
| API | API Gateway | Fronts the request Lambda |
| Auth / user state | Cognito + DynamoDB | Identity and saved schedules |
| Observability | CloudWatch | Logs and metrics |

Known tradeoff: serverless cold-start latency on a conversational tool. For a live demo,
keep one Lambda warm or run the request path on a small always-on Fargate task.

---

## 7. Scope & deliberate non-goals (v1)

**In scope for v1:**
- Self-owned ingestion from official sources (with manual FCE export).
- The three-state prereq model with the confirmation loop.
- Deterministic solver + ranking + verifier.
- LLM explanation guarded by the verifier, with a stub fallback so everything runs
  without an API key.
- Minimal but clean survey + chat + week-grid frontend.

**Deliberately NOT in v1 (call these out as "future work" — the restraint is a feature):**
- **No learned ranking model.** FCE-weighted heuristic ranking is explainable and needs no
  training data; a learned ranker would turn an explainable system into a black box.
- **No live seat availability.** Live counts need authenticated access; v1 shows
  timestamped last-known status.
- **No university-wide requirement coverage.** Requirement rules are curated per major to
  start.

---

## 8. Honest limitations (state these; don't hide them)

- **FCE data** requires a manual CSV export until an authenticated integration exists.
- **Prerequisite accuracy** is bounded by what our parser extracts; that's exactly why
  unparseable prereqs default to `unconfirmed` and get confirmed with the student.
- **Prereq enforcement is advisory** in v1 — tell students to verify against their official
  audit.
- **Verifier scope:** it guarantees *factual* schedule claims (days off, unit totals,
  conflicts). *Soft* claims ("manageable workload") are hedged in the prompt as predictions
  from FCE data, not verified.

---

## 9. Conventions

- **Deterministic core is correctness-critical.** The prereq classifier, solver, and
  verifier each require real tests. No exceptions.
- **Two tests are load-bearing** and must exist:
  1. "missing/unparseable prereq data → `unconfirmed`, never `blocked`"
  2. "a wrong LLM claim is caught by the verifier and never reaches output"
- **Everything runs without secrets.** Ingestion works from a committed fixture; the LLM
  has a stub fallback so the full test suite passes with no API key.
- **No secrets committed.** API keys live in env vars only.
- **The LLM never originates schedule data.** If you find yourself letting the model decide
  what's on the calendar, stop — that violates the core design.
- **Build order:** deterministic, testable pieces first; LLM and cloud last, layered onto a
  validated foundation.

---

## 10. Glossary

- **Eligible / Unconfirmed / Blocked** — the three prereq states (see §3).
- **Top-K** — the solver returns the K best feasible schedules (default 5), not all of
  them.
- **Confirmation question** — the prompt attached to an unconfirmed course asking whether a
  missing prereq is met.
- **Cascade** — confirming one prereq can unlock further dependent courses on re-solve.
- **Claim verifier** — the deterministic gate checking LLM factual claims against solver
  output.
- **FCE** — Faculty Course Evaluations; source of workload hours and ratings.
- **SOC** — Schedule of Classes; source of sections and meeting times.
