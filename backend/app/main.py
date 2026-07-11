"""FastAPI application entrypoint for cmu-scheduler.

Wires the deterministic core (classifier -> solver -> ranking) behind three
endpoints. Deliberately **no LLM yet**: these return structured JSON so the whole
pipeline is validated with no API key (project context §7 build order). The LLM
orchestrator layers on top of this in a later stage.

Endpoints:
- ``POST /survey``    — foundation courses for the student's major, to tick off.
- ``POST /recommend`` — classify -> solve -> rank -> top-K schedules, each with
  per-course classification, plus a confirmation question for every *included*
  unconfirmed course.
- ``POST /confirm``   — apply the student's prereq answers, re-run, return updated
  schedules. This is the cascade loop (project context §3).
"""

from __future__ import annotations

from typing import Iterable, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.data_loader import load_courses
from app.models import (
    Course,
    PrereqAnd,
    PrereqCourse,
    PrereqNode,
    PrereqOr,
    Schedule,
    Section,
    StudentProfile,
)
from app.orchestrator import (
    ConfirmationQuestion,
    ScheduleContext,
    build_confirmation_questions,
    orchestrate,
)
from app.prereq import Classification, classify, missing_prereqs
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

# Curated per-major department prefixes (project context §7: requirement rules are
# curated per major to start). Unknown majors fall back to no prefix filter.
_MAJOR_PREFIXES: dict[str, tuple[str, ...]] = {
    "computer science": ("15", "21"),
    "mathematics": ("21",),
    "statistics and machine learning": ("21", "36"),
}


def _collect_referenced(node: Optional[PrereqNode], out: set[str]) -> None:
    if isinstance(node, PrereqCourse):
        out.add(node.course_num)
    elif isinstance(node, (PrereqAnd, PrereqOr)):
        for operand in node.operands:
            _collect_referenced(operand, out)
    # None / PrereqUnparsed reference no concrete course.


# Courses that are prerequisites of some other course — the building blocks.
_REFERENCED_PREREQS: set[str] = set()
for _course in CATALOG:
    _collect_referenced(_course.prereqs, _REFERENCED_PREREQS)


# --- Request / response schemas ----------------------------------------------


class FoundationCourse(BaseModel):
    course_num: str
    title: str
    units: float


class SurveyResponse(BaseModel):
    major: str
    foundation_courses: list[FoundationCourse]


class ScheduleOut(BaseModel):
    sections: list[Section]
    total_units: float
    total_workload_hours: float
    score: float
    # Per-course state for the courses on this schedule (eligible | unconfirmed).
    classifications: dict[str, Classification]
    # Unmet degree-requirement groups this schedule's courses advance.
    requirements_advanced: list[GroupRef] = Field(default_factory=list)


class RecommendResponse(BaseModel):
    schedules: list[ScheduleOut]
    confirmation_questions: list[ConfirmationQuestion]
    # NOT an official audit — surfaced so the UI can say so clearly.
    disclaimer: str


class ConfirmRequest(BaseModel):
    profile: StudentProfile
    # course number -> whether the student has taken it.
    answers: dict[str, bool] = Field(default_factory=dict)


class AskRequest(BaseModel):
    profile: StudentProfile
    question: str


class AskResult(BaseModel):
    sections: list[Section]
    total_units: float
    total_workload_hours: float
    score: float
    classifications: dict[str, Classification]
    fit_rank: Optional[int] = None
    # LLM prose (semantic route only); None on the structured route.
    explanation: Optional[str] = None
    # Only claims that PASSED verification are ever included here.
    verified_claims: list[Claim] = Field(default_factory=list)
    stripped_claim_count: int = 0
    confirmation_questions: list[ConfirmationQuestion] = Field(default_factory=list)
    requirements_advanced: list[GroupRef] = Field(default_factory=list)


class AskResponse(BaseModel):
    question: str
    route: str  # "structured" | "semantic"
    llm_backend: str  # "none" (structured) | "stub" | "anthropic"
    results: list[AskResult]
    disclaimer: str


# --- Helpers -----------------------------------------------------------------


def _foundation_courses(major: str) -> list[Course]:
    """Derive a major's foundation checklist from the loaded catalog.

    A foundation course is a lower-division building block: it either has **no
    prerequisites** (a gateway) or is itself **a prerequisite of another course**.
    Filtered to the major's department prefixes when known.
    """
    prefixes = _MAJOR_PREFIXES.get(major.strip().lower())
    prefix_match = tuple(f"{p}-" for p in prefixes) if prefixes else None

    result = [
        c
        for c in CATALOG
        if (prefix_match is None or c.course_num.startswith(prefix_match))
        and (c.prereqs is None or c.course_num in _REFERENCED_PREREQS)
    ]
    return sorted(result, key=lambda c: c.course_num)


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
) -> tuple[
    list[Schedule], dict[str, Classification], set[str], set[str], RequirementsStatus
]:
    """Classify the catalog and solve — the shared front half of every request path."""
    completed_set = set(completed)
    ruled_out_set = set(ruled_out)

    classifications: dict[str, Classification] = {
        c.course_num: classify(c, completed_set, ruled_out=ruled_out_set)
        for c in CATALOG
    }

    # Completed courses play two roles: they satisfy prerequisites (via `classify`
    # above, which reads `completed_set`) AND must be excluded from the schedulable
    # pool — you don't recommend a course the student has already taken. Filter them
    # out of the candidate list before solving; prereq satisfaction is unaffected.
    candidates = [c for c in CATALOG if c.course_num not in completed_set]

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
        units_cap=DEFAULT_UNITS_CAP,
        commitments=profile.commitments,
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
                schedule=sched, classifications=per_course, confirmation_targets=targets
            )
        )
    return contexts


# Keyword router: structured questions (facts) go to the deterministic pipeline;
# fuzzy questions (fit, preferences) go to the LLM. Prevents using the LLM where
# the database is authoritative (project context §5).
_STRUCTURED_KEYWORDS = (
    "conflict", "unit", "prereq", "prerequisite", "requirement", "days off",
    "day off", "free day", "how many", "what time", "when does", "which days",
)
_SEMANTIC_KEYWORDS = (
    "best", "recommend", "interest", "enjoy", "like", "fun", "fit", "should i",
    "prefer", "easier", "lighter", "harder", "manageable", "worth",
)


def _route_question(question: str) -> str:
    q = question.lower()
    structured = sum(1 for kw in _STRUCTURED_KEYWORDS if kw in q)
    semantic = sum(1 for kw in _SEMANTIC_KEYWORDS if kw in q)
    return "structured" if structured > semantic else "semantic"


def _run_recommendation(
    profile: StudentProfile,
    completed: Iterable[str],
    ruled_out: Iterable[str],
) -> RecommendResponse:
    """Classify every catalog course, solve, rank, and attach confirmation questions."""
    schedules, classifications, completed_set, ruled_out_set, req_status = _solve_for(
        profile, completed, ruled_out
    )

    schedule_outs: list[ScheduleOut] = []
    unconfirmed_included: dict[str, Course] = {}
    for sched in schedules:
        per_course = {s.course_num: classifications[s.course_num] for s in sched.sections}
        schedule_outs.append(
            ScheduleOut(
                sections=sched.sections,
                total_units=sched.total_units,
                total_workload_hours=sched.total_workload_hours,
                score=sched.score,
                classifications=per_course,
                requirements_advanced=_advanced_groups(sched, req_status),
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
    """Return the major's foundation courses for the student to tick off."""
    foundation = _foundation_courses(profile.major)
    return SurveyResponse(
        major=profile.major,
        foundation_courses=[
            FoundationCourse(course_num=c.course_num, title=c.title, units=c.units)
            for c in foundation
        ],
    )


@app.post("/recommend", response_model=RecommendResponse)
def recommend(profile: StudentProfile) -> RecommendResponse:
    """Classify -> solve -> rank; return top-K schedules and confirmation questions."""
    return _run_recommendation(profile, profile.completed_courses, ruled_out=set())


@app.post("/confirm", response_model=RecommendResponse)
def confirm(request: ConfirmRequest) -> RecommendResponse:
    """Apply prereq answers to the completed/ruled-out sets and re-run (the cascade)."""
    completed = set(request.profile.completed_courses)
    ruled_out: set[str] = set()
    for course_num, taken in request.answers.items():
        (completed if taken else ruled_out).add(course_num)
    return _run_recommendation(request.profile, completed, ruled_out)


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Answer a question about the top schedules, routing structured vs semantic.

    Structured questions (units, conflicts, prereqs) are answered from the solver's
    output with no prose. Fuzzy questions (fit, interests) go to the LLM
    orchestrator, whose every factual claim passes the verifier before returning —
    so no unverified claim about a schedule ever reaches the student.
    """
    profile = request.profile
    schedules, classifications, completed, ruled_out, req_status = _solve_for(
        profile, profile.completed_courses, ruled_out=set()
    )
    contexts = _build_contexts(schedules, classifications, completed, ruled_out)
    route = _route_question(request.question)

    if route == "structured":
        results = [
            AskResult(
                sections=ctx.schedule.sections,
                total_units=ctx.schedule.total_units,
                total_workload_hours=ctx.schedule.total_workload_hours,
                score=ctx.schedule.score,
                classifications=ctx.classifications,
                fit_rank=rank,
                confirmation_questions=build_confirmation_questions(ctx),
                requirements_advanced=_advanced_groups(ctx.schedule, req_status),
            )
            for rank, ctx in enumerate(contexts, start=1)
        ]
        return AskResponse(
            question=request.question,
            route=route,
            llm_backend="none",
            results=results,
            disclaimer=REQUIREMENTS.disclaimer,
        )

    orch = orchestrate(contexts, profile, question=request.question)
    results = []
    for exp in orch.explanations:
        results.append(
            AskResult(
                sections=exp.schedule.sections,
                total_units=exp.schedule.total_units,
                total_workload_hours=exp.schedule.total_workload_hours,
                score=exp.schedule.score,
                classifications=exp.classifications,
                fit_rank=exp.fit_rank,
                explanation=exp.explanation,
                verified_claims=exp.verified_claims,
                stripped_claim_count=len(exp.stripped_claims),
                confirmation_questions=exp.confirmation_questions,
                requirements_advanced=_advanced_groups(exp.schedule, req_status),
            )
        )
    return AskResponse(
        question=request.question,
        route=route,
        llm_backend=orch.backend,
        results=results,
        disclaimer=REQUIREMENTS.disclaimer,
    )
