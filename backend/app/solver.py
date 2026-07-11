"""Fused solve-and-rank engine — the deterministic core that builds schedules.

Given classified candidate courses, the student's commitments, and a units cap,
this returns the **top-K conflict-free schedules ranked by fit**. It is the piece
the project context (§2) insists must be deterministic: the LLM never places a
class, it only explains what this produced.

What "valid" means
-------------------
A schedule is valid iff:

- **at most one section per course** (you can't attend a course twice);
- **no two chosen sections overlap** in time on a shared day;
- **every commitment is respected** — a section may not overlap a busy block;
- the **total units stay within the cap**.

``blocked`` courses are excluded up front; only ``eligible`` and ``unconfirmed``
courses are schedulable (an unconfirmed course rides along and carries its
confirmation question downstream).

Why branch-and-bound, not enumerate-then-sort
----------------------------------------------
Enumerating every schedule is exponential (recitations alone explode the space).
Instead we DFS over courses — at each course, *skip* it or *take one of its
sections* — scoring incrementally and keeping only the best K complete schedules
in a bounded min-heap. Because the ranking score is additive over courses
(:mod:`app.ranking`), the sum of ``max(0, value)`` over the not-yet-decided
courses is an **admissible upper bound** on any completion. Once the K-heap is
full, any subtree whose optimistic bound can't beat the current K-th best is
pruned — we never materialize, let alone sort, the full space.
"""

from __future__ import annotations

import heapq
from typing import Iterable, Mapping, Optional

from app.models import Course, Schedule, Section, StudentProfile, TimeBlock
from app.prereq import Classification
from app.ranking import course_value

# A meeting interval on one weekday: (day, start_minute, end_minute).
_Interval = tuple[str, int, int]

DEFAULT_K = 5


def _minutes(value) -> int:
    return value.hour * 60 + value.minute


def _section_intervals(section: Section) -> list[_Interval]:
    start, end = _minutes(section.begin), _minutes(section.end)
    return [(day, start, end) for day in section.days]


def _commitment_intervals(commitments: Iterable[TimeBlock]) -> list[_Interval]:
    intervals: list[_Interval] = []
    for block in commitments:
        start, end = _minutes(block.begin), _minutes(block.end)
        intervals.extend((day, start, end) for day in block.days)
    return intervals


def _overlaps_any(candidate: list[_Interval], busy: list[_Interval]) -> bool:
    """True if any candidate interval overlaps any busy interval on the same day."""
    for c_day, c_start, c_end in candidate:
        for b_day, b_start, b_end in busy:
            # Half-open overlap: touching end-to-start (e.g. 10:50–11:00) is fine.
            if c_day == b_day and c_start < b_end and b_start < c_end:
                return True
    return False


def solve(
    courses: Iterable[Course],
    profile: StudentProfile,
    *,
    units_cap: float,
    commitments: Optional[Iterable[TimeBlock]] = None,
    classifications: Optional[Mapping[str, Classification]] = None,
    value_bonus: Optional[Mapping[str, float]] = None,
    k: int = DEFAULT_K,
) -> list[Schedule]:
    """Return up to ``k`` valid schedules, best-ranked first.

    Args:
        courses: Candidate courses to draw from.
        profile: Student profile (drives the ranking's interest match).
        units_cap: Maximum total units a returned schedule may carry.
        commitments: Busy time blocks to schedule around. Defaults to the
            profile's commitments if not given.
        classifications: Map of course number -> classification. Courses
            classified ``blocked`` are excluded; anything else is schedulable.
            If omitted, all provided courses are treated as schedulable.
        value_bonus: Optional ``course_num -> bonus`` added to each course's
            ranking value (a caller-supplied signal, e.g. degree-requirement
            fit). Omit for the pure FCE/interest ranking — the default preserves
            the exact prior behavior.
        k: Number of top schedules to return (default 5).

    Returns:
        Up to ``k`` :class:`~app.models.Schedule` objects sorted by descending
        score. Deterministic: ties break on the sorted section-id key.
    """
    if k < 1:
        return []

    def _value(course: Course) -> float:
        base = course_value(course, profile)
        return base + (value_bonus.get(course.course_num, 0.0) if value_bonus else 0.0)

    busy_base = _commitment_intervals(
        commitments if commitments is not None else profile.commitments
    )

    # Exclude blocked; keep eligible + unconfirmed (or everything if unclassified).
    schedulable = [
        c
        for c in courses
        if not (classifications and classifications.get(c.course_num) == "blocked")
    ]

    # Order by descending value so the heap fills with strong schedules early,
    # which tightens the bound and prunes more.
    valued = sorted(
        ((_value(c), c) for c in schedulable),
        key=lambda pair: pair[0],
        reverse=True,
    )
    values = [v for v, _ in valued]
    ordered = [c for _, c in valued]
    n = len(ordered)

    # suffix[i] = optimistic additional score achievable from courses[i:].
    suffix = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + max(0.0, values[i])

    # Pair each course's sections with their precomputed intervals, indexed by
    # position (not section_id, which isn't guaranteed unique within a course).
    prepared: list[list[tuple[Section, list[_Interval]]]] = [
        [(s, _section_intervals(s)) for s in c.sections] for c in ordered
    ]

    # Bounded min-heap of the best complete schedules seen so far.
    heap: list[tuple[float, int, Schedule]] = []
    seq = 0  # tiebreaker so Schedules are never compared directly

    def consider(
        chosen: list[Section], score: float, units: float, workload: float
    ) -> None:
        nonlocal seq
        sched = Schedule(
            sections=list(chosen),
            total_units=units,
            total_workload_hours=workload,
            score=round(score, 6),
        )
        if len(heap) < k:
            heapq.heappush(heap, (score, seq, sched))
        elif score > heap[0][0]:
            heapq.heapreplace(heap, (score, seq, sched))
        seq += 1

    def dfs(
        index: int,
        chosen: list[Section],
        busy: list[_Interval],
        units: float,
        workload: float,
        score: float,
    ) -> None:
        # Every node is itself a valid (possibly partial) schedule.
        consider(chosen, score, units, workload)
        if index == n:
            return
        # Prune: even the most optimistic completion can't crack the top K.
        if len(heap) == k and score + suffix[index] <= heap[0][0]:
            return

        course = ordered[index]
        # Option 1: skip this course.
        dfs(index + 1, chosen, busy, units, workload, score)
        # Option 2: take one of its sections, if it fits units and time.
        if units + course.units <= units_cap:
            for section, ivs in prepared[index]:
                if not _overlaps_any(ivs, busy):
                    dfs(
                        index + 1,
                        chosen + [section],
                        busy + ivs,
                        units + course.units,
                        workload + course.fce_workload_hours,
                        score + values[index],
                    )

    dfs(0, [], busy_base, 0.0, 0.0, 0.0)

    # Deterministic ordering: score desc, then a stable section-key.
    def sort_key(sched: Schedule) -> tuple:
        section_key = tuple(sorted((s.course_num, s.section_id) for s in sched.sections))
        return (-sched.score, section_key)

    return sorted((sched for _, _, sched in heap), key=sort_key)
