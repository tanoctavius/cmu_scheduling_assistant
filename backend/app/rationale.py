"""Deterministic rationale — why a schedule was built, with verified facts only.

The right-hand panel explains each schedule and shows green checkmarks next to
the facts about it (total units, no conflicts, days off, courses included). Those
checkmarks are **outputs of the claim verifier**, never LLM prose:

1. :func:`schedule_claims` derives the candidate factual claims *from the solved
   schedule itself* — no model is asked, and nothing is invented.
2. Every one of them is then put through :func:`app.verifier.verify` against that
   same schedule, and only the claims that **pass** are returned.

Step 2 is not ceremony. The claims come from the solver's cached totals
(``total_units``, ``total_workload_hours``), so if those ever drifted from the
sections actually on the schedule, the verifier would catch it and strip the
claim rather than show the student a wrong number.

This path is deliberately LLM-free and provider-independent: the rationale is
identical whether ``LLM_PROVIDER`` is ``stub`` or ``groq``, it costs no API call,
and it stays fast enough to re-render on every prereq toggle. The LLM's role in
the chat is to propose *intent*; it never authors these facts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import Schedule
from app.requirements import GroupRef
from app.verifier import (
    Claim,
    IncludesCourseClaim,
    NoClassOnClaim,
    NoConflictsClaim,
    TotalUnitsClaim,
    verify,
)

_DAY_ORDER = ["M", "T", "W", "R", "F"]
_DAY_NAMES = {"M": "Monday", "T": "Tuesday", "W": "Wednesday", "R": "Thursday", "F": "Friday"}


def free_days(schedule: Schedule) -> list[str]:
    """Weekdays on which the schedule has no meeting, in weekday order."""
    busy: set[str] = set()
    for section in schedule.sections:
        busy.update(section.days)
    return [d for d in _DAY_ORDER if d not in busy]


class Rationale(BaseModel):
    """Why this schedule was constructed, plus only verifier-approved facts."""

    summary: str
    # ONLY claims that passed verification against this exact schedule.
    verified_claims: list[Claim] = Field(default_factory=list)
    # Non-zero would mean a derived claim failed its own check — a real bug signal.
    stripped_claim_count: int = 0


def schedule_claims(schedule: Schedule) -> list[Claim]:
    """The factual claims we assert about a solved schedule, before verification."""
    claims: list[Claim] = [
        TotalUnitsClaim(value=schedule.total_units),
        NoConflictsClaim(),
    ]
    claims.extend(IncludesCourseClaim(course_num=num) for num in schedule.course_nums)
    claims.extend(NoClassOnClaim(day=day) for day in free_days(schedule))
    return claims


def _summary(
    schedule: Schedule, fit_rank: int, requirements_advanced: list[GroupRef]
) -> str:
    if not schedule.sections:
        return "An empty schedule — no courses fit the current constraints."

    parts = [
        f"Ranked #{fit_rank} by fit. Carries {schedule.total_units:g} units across "
        f"{len(schedule.sections)} course(s) — {', '.join(schedule.course_nums)} — "
        f"at about {schedule.total_workload_hours:g} hours/week."
    ]

    free = free_days(schedule)
    if free:
        parts.append(f"Keeps {', '.join(_DAY_NAMES[d] for d in free)} free.")

    if requirements_advanced:
        names = ", ".join(g.name for g in requirements_advanced)
        parts.append(f"Advances {names}.")

    parts.append("Every section is conflict-free and fits your commitments.")
    return " ".join(parts)


def build_rationale(
    schedule: Schedule,
    *,
    fit_rank: int,
    requirements_advanced: list[GroupRef],
) -> Rationale:
    """Explain a schedule and attach only the claims that pass the verifier."""
    result = verify(schedule_claims(schedule), schedule)
    return Rationale(
        summary=_summary(schedule, fit_rank, requirements_advanced),
        verified_claims=result.passed_claims,
        stripped_claim_count=len(result.failed_checks),
    )
