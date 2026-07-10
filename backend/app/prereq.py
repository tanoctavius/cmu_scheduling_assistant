"""Three-state prerequisite classifier — the correctness-critical front gate.

Every candidate course is classified into exactly one of three states, following
the model in the project context (§3):

- ``eligible``    — every prerequisite is satisfied by the confirmed completed set.
- ``blocked``     — a prerequisite is *confirmed unmet* with no alternative.
- ``unconfirmed`` — status is unknown: not confirmed satisfied, not ruled out.

The design turns on **three-valued (Kleene) logic** over the prereq tree. A leaf
course is TRUE if completed, FALSE if explicitly ruled out, and UNKNOWN
otherwise. AND/OR combine these three-valued, and an unparsed requirement is
UNKNOWN by construction. The classification is then just: TRUE → eligible,
FALSE → blocked, UNKNOWN → unconfirmed.

Non-negotiable safety rule
--------------------------
When prerequisite data is missing or unparseable, the course defaults to
``unconfirmed`` — **never** ``blocked``. A course is only ``blocked`` when a
prerequisite is *positively* known to be unmet (present in ``ruled_out``) with no
satisfiable alternative. The failure mode must always be an extra question, never
a hidden course.

Why ``ruled_out``
-----------------
``blocked`` requires knowing a prerequisite is unmet, which a completed-set alone
can never establish (a course you haven't confirmed might still have been taken).
That knowledge comes from the confirmation loop: a "No, I haven't taken X" answer
puts X in ``ruled_out``. It is optional and defaults to empty, so the documented
call ``classify(course, completed_courses)`` behaves correctly — with no ruled-out
information, an unsatisfied prerequisite is ``unconfirmed``, not ``blocked``.
"""

from __future__ import annotations

from typing import Iterable, Literal, Optional

from app.models import (
    Course,
    PrereqAnd,
    PrereqCourse,
    PrereqNode,
    PrereqOr,
    PrereqUnparsed,
)

Classification = Literal["eligible", "unconfirmed", "blocked"]

# Three-valued truth: True (satisfied), False (unmet), None (unknown).
_Truth = Optional[bool]


def _evaluate(
    node: PrereqNode,
    completed: frozenset[str],
    ruled_out: frozenset[str],
) -> _Truth:
    """Evaluate a prereq node to three-valued truth (True / False / None-unknown)."""
    if isinstance(node, PrereqUnparsed):
        # We had prereq text but couldn't parse it — unknown, never a hard False.
        return None

    if isinstance(node, PrereqCourse):
        if node.course_num in completed:
            return True
        if node.course_num in ruled_out:
            return False
        return None  # unknown: not confirmed, not ruled out

    if isinstance(node, PrereqAnd):
        results = [_evaluate(op, completed, ruled_out) for op in node.operands]
        if any(r is False for r in results):
            return False  # one unmet conjunct sinks the whole AND
        if any(r is None for r in results):
            return None  # nothing unmet, but something still unknown
        return True  # empty AND is vacuously satisfied

    if isinstance(node, PrereqOr):
        results = [_evaluate(op, completed, ruled_out) for op in node.operands]
        if any(r is True for r in results):
            return True  # one satisfied disjunct carries the whole OR
        if any(r is None for r in results):
            return None  # no alternative satisfied yet, but one is still open
        return False  # every alternative ruled out (empty OR is unsatisfiable)

    # Unreachable while PrereqNode is exhaustively handled above; defensive default
    # keeps the safety rule (unknown, not blocked) if a new node type is added.
    return None  # pragma: no cover


def classify(
    course: Course,
    completed_courses: Iterable[str],
    *,
    ruled_out: Optional[Iterable[str]] = None,
) -> Classification:
    """Classify a course as ``eligible``, ``unconfirmed``, or ``blocked``.

    Args:
        course: The course to classify.
        completed_courses: Course numbers the student has confirmed completing.
        ruled_out: Course numbers the student has confirmed *not* taking (e.g. a
            "No" to a confirmation question). Optional; absence means "unknown",
            which keeps unsatisfied prereqs ``unconfirmed`` rather than ``blocked``.

    Returns:
        The three-state classification.
    """
    if course.prereqs is None:
        return "eligible"  # genuinely no prerequisites

    completed_set = frozenset(completed_courses)
    ruled_out_set = frozenset(ruled_out or ())

    truth = _evaluate(course.prereqs, completed_set, ruled_out_set)
    if truth is True:
        return "eligible"
    if truth is False:
        return "blocked"
    return "unconfirmed"


def _collect_missing(
    node: PrereqNode,
    completed: frozenset[str],
    ruled_out: frozenset[str],
    out: list[str],
) -> None:
    """Accumulate course numbers on unsatisfied branches, order-preserving."""
    if _evaluate(node, completed, ruled_out) is True:
        return  # already satisfied — nothing to ask about here

    if isinstance(node, PrereqCourse):
        if node.course_num not in out:
            out.append(node.course_num)
        return

    if isinstance(node, (PrereqAnd, PrereqOr)):
        for op in node.operands:
            _collect_missing(op, completed, ruled_out, out)
        return

    # PrereqUnparsed (or any leaf without a course number) contributes nothing
    # concrete to ask about.


def missing_prereqs(
    course: Course,
    completed_courses: Iterable[str],
    *,
    ruled_out: Optional[Iterable[str]] = None,
) -> list[str]:
    """Course numbers still needed to satisfy the prereqs, for confirmation questions.

    Returns the (de-duplicated, order-preserving) course numbers appearing on
    branches that are not yet satisfied. Satisfied disjuncts are pruned — once an
    OR alternative holds, its siblings are no longer "needed". Returns ``[]`` when
    the course is already eligible or has no prerequisites.
    """
    if course.prereqs is None:
        return []

    completed_set = frozenset(completed_courses)
    ruled_out_set = frozenset(ruled_out or ())

    out: list[str] = []
    _collect_missing(course.prereqs, completed_set, ruled_out_set, out)
    return out
