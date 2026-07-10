"""Explainable ranking for candidate schedules.

The ranking is a **weighted linear mix of three per-course signals**, summed over
the courses in a schedule. It is deliberately a transparent heuristic, not a
learned model (see project context §7): every number that moves the score can be
pointed at and explained to a student.

Signals (per course)
---------------------
1. **Interest match** — higher is better. Fraction of the student's stated
   interests whose keyword appears in the course title/description, in ``[0, 1]``.
2. **FCE rating** — higher is better. Normalized to ``[0, 1]`` by ``RATING_SCALE``.
3. **FCE workload hours** — *lower* is better, so it enters as a *penalty*
   (subtracted), normalized by ``WORKLOAD_NORM``.

    course_value = W_INTEREST * interest_match
                 + W_RATING   * (fce_rating / RATING_SCALE)
                 - W_WORKLOAD * (fce_workload_hours / WORKLOAD_NORM)

A schedule's score is the sum of its courses' values. Because the value is purely
additive over courses (independent of which *section* is chosen), the solver can
use ``max(0, course_value)`` of the not-yet-placed courses as an admissible upper
bound for branch-and-bound pruning.

Weights live as named constants below so they're easy to find, tune, and cite.
"""

from __future__ import annotations

from typing import Iterable

from app.models import Course, StudentProfile

# --- Weights (tunable, named on purpose) -------------------------------------
W_INTEREST: float = 1.0  # pull toward courses matching stated interests
W_RATING: float = 0.6  # reward well-reviewed courses
W_WORKLOAD: float = 0.4  # penalize heavy workloads

# --- Normalizers -------------------------------------------------------------
RATING_SCALE: float = 5.0  # FCE ratings are on a 1–5 scale
WORKLOAD_NORM: float = 20.0  # ~hours/week that counts as a "full" heavy course


def interest_match(course: Course, profile: StudentProfile) -> float:
    """Fraction of the student's interests whose keyword appears in the course.

    Returns a value in ``[0, 1]``. With no stated interests the signal is neutral
    (``0.0``) rather than undefined. This is a simple keyword-substring heuristic;
    semantic retrieval is a later concern (project context §5).
    """
    if not profile.interests:
        return 0.0
    haystack = f"{course.title} {course.description}".lower()
    hits = sum(1 for interest in profile.interests if interest.lower() in haystack)
    return hits / len(profile.interests)


def course_value(course: Course, profile: StudentProfile) -> float:
    """Weighted per-course contribution to a schedule's score (higher is better)."""
    return (
        W_INTEREST * interest_match(course, profile)
        + W_RATING * (course.fce_rating / RATING_SCALE)
        - W_WORKLOAD * (course.fce_workload_hours / WORKLOAD_NORM)
    )


def schedule_score(courses: Iterable[Course], profile: StudentProfile) -> float:
    """Total ranking score for a schedule: sum of its courses' values."""
    return sum(course_value(course, profile) for course in courses)
