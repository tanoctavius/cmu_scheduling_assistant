"""Deterministic claim verifier — the safety gate on the LLM's output.

The LLM orchestrator (later stage) explains a schedule in prose *and* emits a
parallel, structured list of the factual assertions it made. This module
re-checks every such assertion against the actual solver schedule before anything
reaches the student. Per the project context (§2, §5), the model never originates
schedule facts; this gate guarantees the ones it repeats are true. Failed claims
are handed back so the orchestrator can **strip or regenerate** them.

Claim schema (the LLM stage emits *exactly* this JSON)
-----------------------------------------------------
A claim is one JSON object with a ``type`` tag plus type-specific fields:

- ``{"type": "no_class_on",     "day": "F"}``
      Asserts the student has no class on that weekday (M/T/W/R/F).
- ``{"type": "total_units",     "value": 45}``
      Asserts the schedule's total units equal ``value``.
- ``{"type": "includes_course", "course_num": "21-259"}``
      Asserts the schedule contains that course.
- ``{"type": "no_conflicts"}``
      Asserts no two sections overlap in time.

Anything else fails validation. An unrecognized-but-valid claim that the verifier
does not know how to check is treated as **failed** (unverifiable → strip), never
silently passed — the gate must never let an unchecked factual claim through.

Result
------
:func:`verify` returns a :class:`VerificationResult` — one :class:`ClaimCheck`
per input claim, each with ``ok`` and, on failure, a ``corrected_value`` (the
true value measured from the schedule) plus a human-readable ``message``. Helpers
``passed_claims`` / ``failed_checks`` / ``all_passed`` let the orchestrator keep
the survivors and drop the rest.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterable, Literal, Mapping, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter

from app.models import Day, Schedule

# Canonical weekday order for stable, readable output.
_DAY_ORDER = ["M", "T", "W", "R", "F"]


# --- Claim schema ------------------------------------------------------------


class NoClassOnClaim(BaseModel):
    """"The student has no class on ``day``." """

    type: Literal["no_class_on"] = "no_class_on"
    day: Day


class TotalUnitsClaim(BaseModel):
    """"The schedule totals ``value`` units." """

    type: Literal["total_units"] = "total_units"
    value: float


class IncludesCourseClaim(BaseModel):
    """"The schedule includes ``course_num``." """

    type: Literal["includes_course"] = "includes_course"
    course_num: str


class NoConflictsClaim(BaseModel):
    """"No two sections overlap in time." """

    type: Literal["no_conflicts"] = "no_conflicts"


# Discriminated union: Pydantic selects the variant by the "type" tag. Used both
# as the claim field type and to parse raw LLM dicts into typed claims.
Claim = Annotated[
    Union[NoClassOnClaim, TotalUnitsClaim, IncludesCourseClaim, NoConflictsClaim],
    Field(discriminator="type"),
]
_CLAIM_ADAPTER: TypeAdapter = TypeAdapter(Claim)


# --- Result types ------------------------------------------------------------


class ClaimCheck(BaseModel):
    """The outcome of verifying one claim against the schedule."""

    claim: Claim
    ok: bool
    # The true value measured from the schedule; set only when the claim failed.
    corrected_value: Optional[Any] = None
    message: str = ""


class VerificationResult(BaseModel):
    """All per-claim outcomes, with convenience views for the orchestrator."""

    checks: list[ClaimCheck] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failed_checks(self) -> list[ClaimCheck]:
        """Checks that failed — strip or regenerate these before output."""
        return [c for c in self.checks if not c.ok]

    @property
    def passed_claims(self) -> list[Claim]:
        """The claims that survived verification — safe to keep."""
        return [c.claim for c in self.checks if c.ok]


# --- Measurements from the schedule ------------------------------------------


def _minutes(value) -> int:
    return value.hour * 60 + value.minute


def _days_with_class(schedule: Schedule) -> set[str]:
    days: set[str] = set()
    for section in schedule.sections:
        days.update(section.days)
    return days


def _free_days(schedule: Schedule) -> list[str]:
    busy = _days_with_class(schedule)
    return [d for d in _DAY_ORDER if d not in busy]


def _actual_units(schedule: Schedule) -> float:
    return sum(s.units for s in schedule.sections)


def _conflicting_pairs(schedule: Schedule) -> list[list[str]]:
    """Course-number pairs whose sections overlap in time (should be empty)."""
    pairs: list[list[str]] = []
    sections = schedule.sections
    for i in range(len(sections)):
        a = sections[i]
        a_start, a_end, a_days = _minutes(a.begin), _minutes(a.end), set(a.days)
        for j in range(i + 1, len(sections)):
            b = sections[j]
            b_start, b_end = _minutes(b.begin), _minutes(b.end)
            if a_days & set(b.days) and a_start < b_end and b_start < a_end:
                pairs.append([a.course_num, b.course_num])
    return pairs


# --- Per-claim checks --------------------------------------------------------


def _check(claim: Claim, schedule: Schedule) -> ClaimCheck:
    if isinstance(claim, NoClassOnClaim):
        has_class = claim.day in _days_with_class(schedule)
        if not has_class:
            return ClaimCheck(claim=claim, ok=True)
        return ClaimCheck(
            claim=claim,
            ok=False,
            corrected_value=_free_days(schedule),
            message=f"A class meets on {claim.day}; actual free days: "
            f"{_free_days(schedule)}.",
        )

    if isinstance(claim, TotalUnitsClaim):
        actual = _actual_units(schedule)
        if abs(actual - claim.value) < 1e-9:
            return ClaimCheck(claim=claim, ok=True)
        return ClaimCheck(
            claim=claim,
            ok=False,
            corrected_value=actual,
            message=f"Claimed {claim.value} units; schedule totals {actual}.",
        )

    if isinstance(claim, IncludesCourseClaim):
        present = claim.course_num in schedule.course_nums
        if present:
            return ClaimCheck(claim=claim, ok=True)
        return ClaimCheck(
            claim=claim,
            ok=False,
            corrected_value=sorted(schedule.course_nums),
            message=f"{claim.course_num} is not in the schedule; it contains "
            f"{sorted(schedule.course_nums)}.",
        )

    if isinstance(claim, NoConflictsClaim):
        conflicts = _conflicting_pairs(schedule)
        if not conflicts:
            return ClaimCheck(claim=claim, ok=True)
        return ClaimCheck(
            claim=claim,
            ok=False,
            corrected_value=conflicts,
            message=f"Schedule has time conflicts: {conflicts}.",
        )

    # Defensive: a claim type we can't check must be stripped, never passed.
    return ClaimCheck(  # pragma: no cover
        claim=claim, ok=False, message="Unverifiable claim type; stripped."
    )


def _coerce(raw: Union[Claim, Mapping[str, Any]]) -> Claim:
    """Accept either a typed Claim or a raw LLM dict; validate dicts to a Claim."""
    if isinstance(raw, (NoClassOnClaim, TotalUnitsClaim, IncludesCourseClaim, NoConflictsClaim)):
        return raw
    return _CLAIM_ADAPTER.validate_python(raw)


def verify(
    claims: Iterable[Union[Claim, Mapping[str, Any]]],
    schedule: Schedule,
) -> VerificationResult:
    """Verify each claim against the schedule.

    Args:
        claims: The structured assertions emitted by the LLM. Each may be a typed
            Claim or the raw dict form documented in the module docstring.
        schedule: The authoritative schedule from the solver.

    Returns:
        A :class:`VerificationResult`; failed checks carry the corrected value.
    """
    checks = [_check(_coerce(raw), schedule) for raw in claims]
    return VerificationResult(checks=checks)
