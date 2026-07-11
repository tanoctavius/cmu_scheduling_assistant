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
from pydantic import BaseModel, Field

from app.data_loader import load_courses
from app.models import (
    Course,
    PrereqAnd,
    PrereqCourse,
    PrereqNode,
    PrereqOr,
    Section,
    StudentProfile,
)
from app.prereq import Classification, classify, missing_prereqs
from app.solver import solve

app = FastAPI(title="cmu-scheduler")

# --- Defaults & loaded catalog ----------------------------------------------

DEFAULT_UNITS_CAP = 54.0  # CMU's typical per-semester unit ceiling
DEFAULT_K = 5

# Load the catalog once at import; endpoints read from it (off the request path
# there is no live DB yet — the sample fixture is the source of truth for v1).
CATALOG: list[Course] = load_courses()
CATALOG_BY_NUM: dict[str, Course] = {c.course_num: c for c in CATALOG}

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


class ConfirmationQuestion(BaseModel):
    course_num: str
    title: str
    missing_prereqs: list[str]
    question: str


class RecommendResponse(BaseModel):
    schedules: list[ScheduleOut]
    confirmation_questions: list[ConfirmationQuestion]


class ConfirmRequest(BaseModel):
    profile: StudentProfile
    # course number -> whether the student has taken it.
    answers: dict[str, bool] = Field(default_factory=dict)


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


def _run_recommendation(
    profile: StudentProfile,
    completed: Iterable[str],
    ruled_out: Iterable[str],
) -> RecommendResponse:
    """Classify every catalog course, solve, rank, and attach confirmation questions."""
    completed_set = set(completed)
    ruled_out_set = set(ruled_out)

    classifications: dict[str, Classification] = {
        c.course_num: classify(c, completed_set, ruled_out=ruled_out_set)
        for c in CATALOG
    }

    schedules = solve(
        CATALOG,
        profile,
        units_cap=DEFAULT_UNITS_CAP,
        commitments=profile.commitments,
        classifications=classifications,
        k=DEFAULT_K,
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

    return RecommendResponse(schedules=schedule_outs, confirmation_questions=questions)


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
