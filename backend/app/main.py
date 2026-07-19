"""FastAPI application entrypoint for cmu-scheduler.

Wires the deterministic core (classifier -> solver -> ranking) behind four
endpoints. The solver owns the calendar everywhere: no endpoint lets a model
place, move, or invent a section.

Endpoints:
- ``POST /survey``    — the prereq tick-off checklist for the student's major.
- ``POST /recommend`` — classify -> solve -> rank -> top-K schedules, each with
  per-course classification and a **deterministic, verifier-gated rationale**,
  plus a confirmation question for every *included* unconfirmed course. No LLM.
- ``POST /confirm``   — apply the student's prereq answers, re-run, return updated
  schedules. This is the cascade loop (project context §3). No LLM.
- ``POST /chat``      — the conversational loop. The LLM classifies the turn and
  *proposes constraints*; the deterministic solver rebuilds the calendar from
  them and the verifier gates every claim. See :mod:`app.orchestrator`.

Statelessness: the catalog and requirements are in-memory caches built at import
and rebuilt on every start; conversation state lives in the request/response, not
on the server. A cold start is always clean.
"""

from __future__ import annotations

from typing import Iterable, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.checklist import ChecklistGroup, checklist_courses
from app.data_loader import load_courses
from app.llm_provider import ProviderError, select_provider
from app.models import (
    Course,
    Schedule,
    Section,
    StudentProfile,
)
from app.orchestrator import (
    ChatMessage,
    ConfirmationQuestion,
    GatedTurn,
    ScheduleConstraints,
    ScheduleContext,
    constraints_to_solver_inputs,
    orchestrate_chat_turn,
)
from app.prereq import Classification, classify, missing_prereqs
from app.rationale import Rationale, build_rationale
from app.requirements import (
    GroupRef,
    RequirementsStatus,
    groups_advanced_by_courses,
    remaining_requirements,
    requirement_bonus,
)
from app.requirements_loader import load_requirements
from app.solver import solve
from app.verifier import Claim

app = FastAPI(title="cmu-scheduler")

# Permissive CORS for local development so the Vite frontend (localhost:5173) can
# call the API. Tighten allow_origins before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Defaults & loaded catalog ----------------------------------------------

DEFAULT_UNITS_CAP = 54.0  # CMU's typical per-semester unit ceiling
DEFAULT_K = 5

# Load the catalog once at import; endpoints read from it (off the request path
# there is no live DB yet — the sample fixture is the source of truth for v1).
CATALOG: list[Course] = load_courses()
CATALOG_BY_NUM: dict[str, Course] = {c.course_num: c for c in CATALOG}

# Curated degree requirements (v1: Computer Science). Loaded once at import.
REQUIREMENTS = load_requirements()
# course_num -> units, from the catalog, used when evaluating unit-based rules.
UNITS_BY_NUM: dict[str, float] = {c.course_num: c.units for c in CATALOG}

# --- Request / response schemas ----------------------------------------------


class SurveyResponse(BaseModel):
    major: str
    # Focused, grouped prereq tick-off checklist (core courses + common prereqs).
    checklist: list[ChecklistGroup]


class ScheduleOut(BaseModel):
    sections: list[Section]
    total_units: float
    total_workload_hours: float
    score: float
    # Per-course state for the courses on this schedule (eligible | unconfirmed).
    classifications: dict[str, Classification]
    # Unmet degree-requirement groups this schedule's courses advance.
    requirements_advanced: list[GroupRef] = Field(default_factory=list)
    # Why this schedule was built + the verifier-approved facts about it. Powers
    # the right-hand rationale panel. Deterministic; never LLM prose.
    rationale: Rationale


class RecommendResponse(BaseModel):
    schedules: list[ScheduleOut]
    confirmation_questions: list[ConfirmationQuestion]
    # NOT an official audit — surfaced so the UI can say so clearly.
    disclaimer: str


class ConfirmRequest(BaseModel):
    profile: StudentProfile
    # course number -> whether the student has taken it.
    answers: dict[str, bool] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    profile: StudentProfile
    message: str
    # Prereq answers from the confirmation panel (course number -> taken).
    answers: dict[str, bool] = Field(default_factory=dict)
    # Conversation so far, echoed by the client — the server keeps no session, so
    # a restart mid-conversation loses nothing (Learner Lab session timer).
    history: list[ChatMessage] = Field(default_factory=list)
    # Constraints already in effect from earlier turns, likewise client-held.
    constraints: ScheduleConstraints = Field(default_factory=ScheduleConstraints)
    # Which schedule the student is looking at (index into `schedules`).
    selected: int = 0


class ChatResponse(BaseModel):
    reply: str
    kind: str  # "question" | "modification"
    # The LLM_PROVIDER that answered — "stub" | "groq" | any added later.
    llm_backend: str
    # The calendar after this turn: unchanged for a question, re-solved for a
    # modification. Always the solver's output, never the model's.
    schedules: list[ScheduleOut]
    # The constraints now in effect; the client echoes these back next turn.
    constraints: ScheduleConstraints
    # True when the requested constraints left nothing solvable, so we kept the
    # previous calendar instead of showing an empty one.
    constraints_relaxed: bool = False
    # Only claims that PASSED verification are ever included here.
    verified_claims: list[Claim] = Field(default_factory=list)
    stripped_claim_count: int = 0
    confirmation_questions: list[ConfirmationQuestion] = Field(default_factory=list)
    # The conversation including this turn, for the client to send back.
    history: list[ChatMessage] = Field(default_factory=list)
    disclaimer: str


# --- Helpers -----------------------------------------------------------------


def _question_text(course: Course, missing: list[str]) -> str:
    """Deterministic, templated confirmation copy (not LLM prose)."""
    if not missing:
        return f"Have you met the prerequisites for {course.course_num} {course.title}?"
    joined = " and ".join(missing)
    pronoun = "it" if len(missing) == 1 else "them"
    return (
        f"{course.title} ({course.course_num}) looks like a strong fit — it requires "
        f"{joined}. Have you taken {pronoun}?"
    )


def _solve_for(
    profile: StudentProfile,
    completed: Iterable[str],
    ruled_out: Iterable[str],
    constraints: Optional[ScheduleConstraints] = None,
) -> tuple[
    list[Schedule], dict[str, Classification], set[str], set[str], RequirementsStatus
]:
    """Classify the catalog and solve — the shared front half of every request path.

    ``constraints`` (from a chat turn) are translated into the solver's ordinary
    inputs first, so the chat gets no special code path in the solver and every
    invariant it already guarantees still holds.
    """
    completed_set = set(completed)
    ruled_out_set = set(ruled_out)
    constraints = constraints or ScheduleConstraints()

    classifications: dict[str, Classification] = {
        c.course_num: classify(c, completed_set, ruled_out=ruled_out_set)
        for c in CATALOG
    }

    units_cap, commitments, excluded = constraints_to_solver_inputs(
        constraints,
        base_commitments=list(profile.commitments),
        default_units_cap=DEFAULT_UNITS_CAP,
    )

    # Completed courses play two roles: they satisfy prerequisites (via `classify`
    # above, which reads `completed_set`) AND must be excluded from the schedulable
    # pool — you don't recommend a course the student has already taken. Filter them
    # out of the candidate list before solving; prereq satisfaction is unaffected.
    # Chat-excluded courses ("drop 76-101") drop out of the pool the same way.
    candidates = [
        c
        for c in CATALOG
        if c.course_num not in completed_set and c.course_num not in excluded
    ]

    # Degree-requirement fit as a ranking signal, layered on the FCE/interest score
    # inside the solver (not a hard filter — electives still compete).
    profile_for_req = profile.model_copy(update={"completed_courses": completed_set})
    req_status = remaining_requirements(profile_for_req, REQUIREMENTS, UNITS_BY_NUM)
    value_bonus = {
        c.course_num: requirement_bonus(c.course_num, c.units, REQUIREMENTS, req_status)
        for c in candidates
    }

    schedules = solve(
        candidates,
        profile,
        units_cap=units_cap,
        commitments=commitments,
        classifications=classifications,
        value_bonus=value_bonus,
        k=DEFAULT_K,
    )
    return schedules, classifications, completed_set, ruled_out_set, req_status


def _advanced_groups(schedule: Schedule, status: RequirementsStatus) -> list[GroupRef]:
    """Which unmet requirement groups this schedule's courses advance."""
    return groups_advanced_by_courses(
        schedule.course_nums, UNITS_BY_NUM, REQUIREMENTS, status
    )


def _build_contexts(
    schedules: list[Schedule],
    classifications: dict[str, Classification],
    completed: set[str],
    ruled_out: set[str],
    req_status: RequirementsStatus,
) -> list[ScheduleContext]:
    """Package each schedule's facts for the orchestrator — the LLM invents nothing."""
    contexts: list[ScheduleContext] = []
    for sched in schedules:
        per_course = {s.course_num: classifications[s.course_num] for s in sched.sections}
        targets = {
            s.course_num: missing_prereqs(
                CATALOG_BY_NUM[s.course_num], completed, ruled_out=ruled_out
            )
            for s in sched.sections
            if classifications[s.course_num] == "unconfirmed"
        }
        contexts.append(
            ScheduleContext(
                schedule=sched,
                classifications=per_course,
                confirmation_targets=targets,
                requirements_advanced=[
                    g.name for g in _advanced_groups(sched, req_status)
                ],
            )
        )
    return contexts


def _split_answers(
    profile: StudentProfile, answers: dict[str, bool]
) -> tuple[set[str], set[str]]:
    """Fold prereq answers into the completed / ruled-out sets."""
    completed = set(profile.completed_courses)
    ruled_out: set[str] = set()
    for course_num, taken in answers.items():
        (completed if taken else ruled_out).add(course_num)
    return completed, ruled_out


def _run_recommendation(
    profile: StudentProfile,
    completed: Iterable[str],
    ruled_out: Iterable[str],
    constraints: Optional[ScheduleConstraints] = None,
) -> RecommendResponse:
    """Classify every catalog course, solve, rank, and attach confirmation questions.

    Each schedule carries a deterministic, verifier-gated rationale — no LLM is
    involved here, so this stays fast enough to re-run on every prereq toggle.
    """
    schedules, classifications, completed_set, ruled_out_set, req_status = _solve_for(
        profile, completed, ruled_out, constraints
    )

    schedule_outs: list[ScheduleOut] = []
    unconfirmed_included: dict[str, Course] = {}
    for rank, sched in enumerate(schedules, start=1):
        per_course = {s.course_num: classifications[s.course_num] for s in sched.sections}
        advanced = _advanced_groups(sched, req_status)
        schedule_outs.append(
            ScheduleOut(
                sections=sched.sections,
                total_units=sched.total_units,
                total_workload_hours=sched.total_workload_hours,
                score=sched.score,
                classifications=per_course,
                requirements_advanced=advanced,
                rationale=build_rationale(
                    sched, fit_rank=rank, requirements_advanced=advanced
                ),
            )
        )
        for section in sched.sections:
            if classifications[section.course_num] == "unconfirmed":
                unconfirmed_included.setdefault(
                    section.course_num, CATALOG_BY_NUM[section.course_num]
                )

    questions = []
    for course_num, course in unconfirmed_included.items():
        missing = missing_prereqs(course, completed_set, ruled_out=ruled_out_set)
        questions.append(
            ConfirmationQuestion(
                course_num=course_num,
                title=course.title,
                missing_prereqs=missing,
                question=_question_text(course, missing),
            )
        )

    return RecommendResponse(
        schedules=schedule_outs,
        confirmation_questions=questions,
        disclaimer=REQUIREMENTS.disclaimer,
    )


# --- Endpoints ---------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/survey", response_model=SurveyResponse)
def survey(profile: StudentProfile) -> SurveyResponse:
    """Return the grouped prereq tick-off checklist for the student's major."""
    return SurveyResponse(
        major=profile.major,
        checklist=checklist_courses(profile.major, CATALOG, REQUIREMENTS),
    )


@app.post("/recommend", response_model=RecommendResponse)
def recommend(profile: StudentProfile) -> RecommendResponse:
    """Classify -> solve -> rank; return top-K schedules and confirmation questions."""
    return _run_recommendation(profile, profile.completed_courses, ruled_out=set())


@app.post("/confirm", response_model=RecommendResponse)
def confirm(request: ConfirmRequest) -> RecommendResponse:
    """Apply prereq answers to the completed/ruled-out sets and re-run (the cascade)."""
    completed, ruled_out = _split_answers(request.profile, request.answers)
    return _run_recommendation(request.profile, completed, ruled_out)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """One conversational turn against the current calendar.

    The division of labour is the whole point:

    - The **LLM** reads the conversation and decides whether this turn is a
      question or a change request, and if it's a change, which *constraints* the
      student is asking for. That is all it does.
    - The **solver** rebuilds the calendar from those constraints. The model never
      places a section or edits a schedule; a modification is just the same
      deterministic solve with different inputs.
    - The **verifier** checks every factual claim the model made against the real
      schedule before any of it is shown, exactly as on every other path.

    A question leaves the calendar untouched. A modification re-solves; if the
    request turns out to be unsatisfiable, we keep the previous constraints and
    say so rather than hand back an empty week.
    """
    profile = request.profile
    completed, ruled_out = _split_answers(profile, request.answers)

    # The calendar as it stands — both the grounding for a question and the
    # fallback if a requested change proves infeasible.
    current = _run_recommendation(profile, completed, ruled_out, request.constraints)

    ctx: Optional[ScheduleContext] = None
    if current.schedules:
        index = min(max(request.selected, 0), len(current.schedules) - 1)
        schedules, classifications, completed_set, ruled_out_set, req_status = _solve_for(
            profile, completed, ruled_out, request.constraints
        )
        contexts = _build_contexts(
            schedules, classifications, completed_set, ruled_out_set, req_status
        )
        ctx = contexts[index] if index < len(contexts) else None

    # A provider that misbehaves — missing config, transport failure, or output
    # that doesn't parse into the ChatTurn schema — must never crash the turn or
    # leak an unverified claim. Treat it like a failed verification: no claims,
    # constraints unchanged, calendar untouched, and an honest fallback reply.
    backend_name = "unavailable"
    try:
        provider = select_provider()
        backend_name = provider.name
        turn = orchestrate_chat_turn(
            provider,
            profile,
            message=request.message,
            history=request.history,
            constraints=request.constraints,
            ctx=ctx,
        )
    except ProviderError:
        turn = GatedTurn(
            kind="question",
            reply=(
                "I couldn't turn the model's response into a verified answer, so "
                "I'm not showing any claims for this turn. Your schedule is "
                "unchanged — please try rephrasing."
            ),
            constraints=request.constraints,
            backend=backend_name,
        )

    result = current
    constraints = request.constraints
    relaxed = False

    if turn.kind == "modification":
        proposed = _run_recommendation(profile, completed, ruled_out, turn.constraints)
        if any(s.sections for s in proposed.schedules):
            result, constraints = proposed, turn.constraints
        else:
            # Unsatisfiable: keep the working calendar rather than showing nothing.
            relaxed = True

    history = [
        *request.history,
        ChatMessage(role="user", content=request.message),
        ChatMessage(role="assistant", content=turn.reply),
    ]

    reply = turn.reply
    if relaxed:
        reply = (
            f"{turn.reply} (I couldn't satisfy that without emptying your schedule, "
            f"so I've kept the previous one.)"
        )

    return ChatResponse(
        reply=reply,
        kind=turn.kind,
        llm_backend=turn.backend,
        schedules=result.schedules,
        constraints=constraints,
        constraints_relaxed=relaxed,
        verified_claims=turn.verified_claims,
        stripped_claim_count=len(turn.stripped_claims),
        confirmation_questions=result.confirmation_questions,
        history=history,
        disclaimer=REQUIREMENTS.disclaimer,
    )
