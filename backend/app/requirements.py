"""Degree-requirement models and evaluation.

Correctness-relevant: a wrong "requirement satisfied" result would mislead a
student's graduation planning. The curated requirements file is explicitly **not**
an authoritative audit (see its ``disclaimer``), and this module preserves that
honesty — when unit data or an open pool makes satisfaction genuinely unknown, we
report *not satisfied / open-ended* rather than guessing "done".

Rule types (from the curated file)
----------------------------------
- ``all``                   — every course in ``courses`` is required.
- ``pick_n``                — choose ``n`` from ``courses``.
- ``pick_min_units``        — choose courses from ``courses`` totaling ≥ ``min_units``.
- ``pick_n_min_units_each`` — choose ``n`` courses each ≥ ``min_units_each`` from an
  **open pool** (SCS depts, 200-level+), honoring ``excluded_courses``.
- ``units``                 — ≥ ``units_required`` from an un-enumerated pool (e.g.
  GenEd). Treated as satisfied-by-unit-count only; we never enumerate courses for it.

A group may also carry ``sequence_alternatives`` — a set of course lists, any one of
which (all its courses completed) satisfies the group on its own.
"""

from __future__ import annotations

from typing import Iterable, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import StudentProfile

# --- Ranking-signal constants (named on purpose) -----------------------------
# Weight of the "this course advances an unmet requirement" signal, layered on top
# of the FCE/interest score. Deliberately smaller than a strong interest match so
# it biases — not dictates — the ranking (electives still compete).
W_REQUIREMENT: float = 0.8
# Extra pull toward groups the student hasn't started yet (spread progress out).
UNSTARTED_MULTIPLIER: float = 1.5

# Assumed units for a course whose real unit count is unknown (not in the catalog).
# Most CMU electives are ≥ 9 units; used only for unit accumulation of completed
# courses we can't look up. Documented simplification (see module docstring).
DEFAULT_COURSE_UNITS: float = 9.0

# Departments that count as "School of Computer Science" for the open SCS-elective
# pool (from the curated group's constraint text).
_SCS_DEPARTMENTS = frozenset({"02", "05", "10", "11", "15", "16", "17"})

Rule = Literal["all", "pick_n", "pick_min_units", "pick_n_min_units_each", "units"]


# --- Requirement models ------------------------------------------------------


class RequirementGroup(BaseModel):
    """One requirement group. Rule-specific fields are optional and validated per rule."""

    model_config = ConfigDict(extra="allow")  # tolerate curated-file annotations

    id: str
    name: str
    rule: Rule
    courses: list[str] = Field(default_factory=list)

    n: Optional[int] = None
    min_units: Optional[float] = None
    min_units_each: Optional[float] = None
    units_required: Optional[float] = None
    excluded_courses: list[str] = Field(default_factory=list)
    sequence_alternatives: list[list[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_rule_fields(self) -> "RequirementGroup":
        if self.rule in ("all",) and not self.courses:
            raise ValueError(f"group {self.id}: 'all' requires a non-empty courses list")
        if self.rule == "pick_n" and (self.n is None or self.n < 1):
            raise ValueError(f"group {self.id}: 'pick_n' requires n >= 1")
        if self.rule == "pick_min_units" and self.min_units is None:
            raise ValueError(f"group {self.id}: 'pick_min_units' requires min_units")
        if self.rule == "pick_n_min_units_each" and (
            self.n is None or self.min_units_each is None
        ):
            raise ValueError(
                f"group {self.id}: 'pick_n_min_units_each' requires n and min_units_each"
            )
        if self.rule == "units" and self.units_required is None:
            raise ValueError(f"group {self.id}: 'units' requires units_required")
        return self


class Requirements(BaseModel):
    """A curated degree-requirements document."""

    model_config = ConfigDict(extra="allow")

    major: str
    disclaimer: str
    total_units_required: Optional[float] = None
    requirement_groups: list[RequirementGroup]


# --- Per-group status --------------------------------------------------------


class GroupRef(BaseModel):
    """Lightweight reference to a requirement group (for the API response)."""

    id: str
    name: str


class GroupStatus(BaseModel):
    """Where the student stands on one requirement group."""

    id: str
    name: str
    rule: Rule
    satisfied: bool
    started: bool
    completed_from_group: list[str] = Field(default_factory=list)
    remaining_courses: list[str] = Field(default_factory=list)
    courses_still_needed: int = 0
    units_still_needed: float = 0.0
    open_ended: bool = False  # can't enumerate specific remaining courses
    detail: str = ""


class RequirementsStatus(BaseModel):
    major: str
    disclaimer: str
    groups: list[GroupStatus] = Field(default_factory=list)


# --- Small helpers -----------------------------------------------------------


def _units(course_num: str, units_lookup: Optional[Mapping[str, float]]) -> float:
    if units_lookup is not None and course_num in units_lookup:
        return units_lookup[course_num]
    return DEFAULT_COURSE_UNITS


def _course_level(course_num: str) -> Optional[int]:
    parts = course_num.split("-")
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def _is_scs_upper(course_num: str) -> bool:
    """SCS department (by prefix) and 200-level or above — the open-pool constraint."""
    dept = course_num.split("-")[0]
    level = _course_level(course_num)
    return dept in _SCS_DEPARTMENTS and level is not None and level >= 200


def _sequence_satisfied(group: RequirementGroup, completed: set[str]) -> bool:
    return any(
        seq and all(c in completed for c in seq) for seq in group.sequence_alternatives
    )


def _sequence_started(group: RequirementGroup, completed: set[str]) -> bool:
    return any(c in completed for seq in group.sequence_alternatives for c in seq)


def _scs_qualifying(
    completed: set[str], group: RequirementGroup, units_lookup: Optional[Mapping[str, float]]
) -> list[str]:
    """Completed courses that qualify for the open SCS-elective pool."""
    threshold = group.min_units_each or 0.0
    return [
        c
        for c in sorted(completed)
        if c not in group.excluded_courses
        and _is_scs_upper(c)
        and _units(c, units_lookup) >= threshold
    ]


# --- Evaluation --------------------------------------------------------------


def _evaluate_group(
    group: RequirementGroup,
    completed: set[str],
    units_lookup: Optional[Mapping[str, float]],
) -> GroupStatus:
    done = [c for c in group.courses if c in completed]
    seq_ok = _sequence_satisfied(group, completed)
    started = bool(done) or _sequence_started(group, completed)

    if group.rule == "all":
        remaining = [c for c in group.courses if c not in completed]
        satisfied = not remaining or seq_ok
        return GroupStatus(
            id=group.id, name=group.name, rule=group.rule,
            satisfied=satisfied, started=started,
            completed_from_group=done,
            remaining_courses=[] if satisfied else remaining,
            courses_still_needed=0 if satisfied else len(remaining),
            detail=f"{len(done)}/{len(group.courses)} required courses complete",
        )

    if group.rule == "pick_n":
        n = group.n or 0
        satisfied = len(done) >= n or seq_ok
        still = 0 if satisfied else max(0, n - len(done))
        return GroupStatus(
            id=group.id, name=group.name, rule=group.rule,
            satisfied=satisfied, started=started,
            completed_from_group=done,
            remaining_courses=[] if satisfied else [c for c in group.courses if c not in completed],
            courses_still_needed=still,
            detail=f"chose {len(done)} of {n} needed",
        )

    if group.rule == "pick_min_units":
        min_units = group.min_units or 0.0
        accumulated = sum(_units(c, units_lookup) for c in done)
        satisfied = accumulated >= min_units or seq_ok
        return GroupStatus(
            id=group.id, name=group.name, rule=group.rule,
            satisfied=satisfied, started=started,
            completed_from_group=done,
            remaining_courses=[] if satisfied else [c for c in group.courses if c not in completed],
            units_still_needed=0.0 if satisfied else round(min_units - accumulated, 2),
            detail=f"{accumulated:g}/{min_units:g} units from this group",
        )

    if group.rule == "pick_n_min_units_each":
        n = group.n or 0
        qualifying = _scs_qualifying(completed, group, units_lookup)
        satisfied = len(qualifying) >= n
        return GroupStatus(
            id=group.id, name=group.name, rule=group.rule,
            satisfied=satisfied, started=bool(qualifying),
            completed_from_group=qualifying,
            remaining_courses=[],  # open pool: no specific list
            courses_still_needed=0 if satisfied else max(0, n - len(qualifying)),
            open_ended=True,
            detail=f"{len(qualifying)} of {n} qualifying SCS electives (≥"
            f"{group.min_units_each:g} units each)",
        )

    # rule == "units": satisfied-by-unit-count only; the pool isn't enumerated, so
    # completed_courses alone can't credit it. Report as open/unknown, not "done".
    units_required = group.units_required or 0.0
    return GroupStatus(
        id=group.id, name=group.name, rule=group.rule,
        satisfied=False, started=False,
        units_still_needed=units_required,
        open_ended=True,
        detail=f"{units_required:g} units required from an un-enumerated pool "
        "(verify against your audit)",
    )


def remaining_requirements(
    profile: StudentProfile,
    requirements: Requirements,
    units_lookup: Optional[Mapping[str, float]] = None,
) -> RequirementsStatus:
    """Evaluate every requirement group against the student's completed courses.

    Args:
        profile: The student (only ``completed_courses`` is read here).
        requirements: The curated requirements document.
        units_lookup: Optional ``course_num -> units`` map (e.g. from the catalog).
            Courses absent from it are assumed :data:`DEFAULT_COURSE_UNITS`.

    Returns:
        A :class:`RequirementsStatus` with per-group satisfaction and what remains.
    """
    completed = set(profile.completed_courses)
    groups = [
        _evaluate_group(g, completed, units_lookup) for g in requirements.requirement_groups
    ]
    return RequirementsStatus(
        major=requirements.major, disclaimer=requirements.disclaimer, groups=groups
    )


# --- Ranking signal & advancement --------------------------------------------


def _course_advances(
    course_num: str, units: float, group: RequirementGroup
) -> bool:
    """Would taking this course make progress on this (assumed-unmet) group?"""
    if group.rule == "units":
        return False  # open, un-enumerated pool — can't map a specific course
    if group.rule == "pick_n_min_units_each":
        threshold = group.min_units_each or 0.0
        return (
            course_num not in group.excluded_courses
            and _is_scs_upper(course_num)
            and units >= threshold
        )
    # all / pick_n / pick_min_units: in the enumerated pool or a sequence alternative.
    if course_num in group.courses:
        return True
    return any(course_num in seq for seq in group.sequence_alternatives)


def advancing_group_ids(
    course_num: str,
    units: float,
    requirements: Requirements,
    status: RequirementsStatus,
) -> list[str]:
    """Ids of currently-unmet groups this course would advance."""
    satisfied_ids = {s.id for s in status.groups if s.satisfied}
    return [
        g.id
        for g in requirements.requirement_groups
        if g.id not in satisfied_ids and _course_advances(course_num, units, g)
    ]


def requirement_bonus(
    course_num: str,
    units: float,
    requirements: Requirements,
    status: RequirementsStatus,
) -> float:
    """Ranking bonus for a course, by the best unmet group it advances.

    Advancing any unmet group earns :data:`W_REQUIREMENT`; advancing a group the
    student hasn't started yet earns an extra :data:`UNSTARTED_MULTIPLIER`. Bonuses
    don't stack across groups — we take the strongest single pull.
    """
    started_by_id = {s.id: s.started for s in status.groups}
    best = 0.0
    for gid in advancing_group_ids(course_num, units, requirements, status):
        weight = W_REQUIREMENT * (1.0 if started_by_id.get(gid) else UNSTARTED_MULTIPLIER)
        best = max(best, weight)
    return best


def groups_advanced_by_courses(
    course_nums: Iterable[str],
    units_lookup: Optional[Mapping[str, float]],
    requirements: Requirements,
    status: RequirementsStatus,
) -> list[GroupRef]:
    """The unmet requirement groups a set of courses (a schedule) advances."""
    by_id = {g.id: g for g in requirements.requirement_groups}
    seen: dict[str, GroupRef] = {}
    for course_num in course_nums:
        units = _units(course_num, units_lookup)
        for gid in advancing_group_ids(course_num, units, requirements, status):
            if gid not in seen:
                seen[gid] = GroupRef(id=gid, name=by_id[gid].name)
    return list(seen.values())
