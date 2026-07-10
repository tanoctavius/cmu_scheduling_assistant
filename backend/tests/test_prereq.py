"""Tests for the three-state prerequisite classifier.

Correctness-critical. Covers all three states across leaf / AND / OR / nested /
unparsed prereqs, the non-negotiable safety default (missing data -> unconfirmed,
never blocked), the cascade (adding a course flips unconfirmed -> eligible), and
``missing_prereqs``.
"""

from app.models import (
    Course,
    PrereqAnd,
    PrereqCourse,
    PrereqOr,
    PrereqUnparsed,
)
from app.prereq import classify, missing_prereqs


def _course(prereqs) -> Course:
    """Build a minimal Course with the given prereq tree (no sections needed here)."""
    return Course(
        course_num="99-999",
        title="Test Course",
        units=9.0,
        prereqs=prereqs,
        description="",
        fce_workload_hours=0.0,
        fce_rating=0.0,
        sections=[],
    )


# --- No prerequisites --------------------------------------------------------


def test_no_prereqs_is_eligible():
    assert classify(_course(None), completed_courses=set()) == "eligible"
    assert missing_prereqs(_course(None), set()) == []


# --- Single leaf -------------------------------------------------------------


def test_leaf_satisfied_is_eligible():
    course = _course(PrereqCourse(course_num="15-112"))
    assert classify(course, {"15-112"}) == "eligible"
    assert missing_prereqs(course, {"15-112"}) == []


def test_leaf_unknown_is_unconfirmed_not_blocked():
    course = _course(PrereqCourse(course_num="15-112"))
    result = classify(course, completed_courses=set())
    assert result == "unconfirmed"
    assert result != "blocked"
    assert missing_prereqs(course, set()) == ["15-112"]


def test_leaf_ruled_out_is_blocked():
    course = _course(PrereqCourse(course_num="15-112"))
    assert classify(course, completed_courses=set(), ruled_out={"15-112"}) == "blocked"
    # Still reported as needed, for the "unlocks once you take X" hint.
    assert missing_prereqs(course, set(), ruled_out={"15-112"}) == ["15-112"]


# --- AND ---------------------------------------------------------------------


def test_and_all_satisfied_is_eligible():
    course = _course(
        PrereqAnd(operands=[PrereqCourse(course_num="A"), PrereqCourse(course_num="B")])
    )
    assert classify(course, {"A", "B"}) == "eligible"
    assert missing_prereqs(course, {"A", "B"}) == []


def test_and_one_unknown_is_unconfirmed():
    course = _course(
        PrereqAnd(operands=[PrereqCourse(course_num="A"), PrereqCourse(course_num="B")])
    )
    assert classify(course, {"A"}) == "unconfirmed"
    assert missing_prereqs(course, {"A"}) == ["B"]


def test_and_one_ruled_out_is_blocked():
    course = _course(
        PrereqAnd(operands=[PrereqCourse(course_num="A"), PrereqCourse(course_num="B")])
    )
    # B is confirmed unmet -> the whole conjunction is unsatisfiable.
    assert classify(course, {"A"}, ruled_out={"B"}) == "blocked"


def test_empty_and_is_vacuously_eligible():
    assert classify(_course(PrereqAnd(operands=[])), set()) == "eligible"


# --- OR ----------------------------------------------------------------------


def test_or_one_satisfied_is_eligible():
    course = _course(
        PrereqOr(operands=[PrereqCourse(course_num="A"), PrereqCourse(course_num="B")])
    )
    assert classify(course, {"A"}) == "eligible"
    # Satisfied disjunct prunes its sibling — nothing left to ask.
    assert missing_prereqs(course, {"A"}) == []


def test_or_none_known_is_unconfirmed():
    course = _course(
        PrereqOr(operands=[PrereqCourse(course_num="A"), PrereqCourse(course_num="B")])
    )
    assert classify(course, set()) == "unconfirmed"
    assert missing_prereqs(course, set()) == ["A", "B"]


def test_or_one_ruled_out_one_open_is_unconfirmed():
    course = _course(
        PrereqOr(operands=[PrereqCourse(course_num="A"), PrereqCourse(course_num="B")])
    )
    # A ruled out, B still open -> the OR could still be satisfied -> unconfirmed.
    assert classify(course, set(), ruled_out={"A"}) == "unconfirmed"
    assert missing_prereqs(course, set(), ruled_out={"A"}) == ["A", "B"]


def test_or_all_ruled_out_is_blocked():
    course = _course(
        PrereqOr(operands=[PrereqCourse(course_num="A"), PrereqCourse(course_num="B")])
    )
    assert classify(course, set(), ruled_out={"A", "B"}) == "blocked"


def test_empty_or_is_unsatisfiable_blocked():
    assert classify(_course(PrereqOr(operands=[])), set()) == "blocked"


# --- Nested AND/OR: "15-122 AND (21-127 OR 15-151)" --------------------------


def _nested_course() -> Course:
    return _course(
        PrereqAnd(
            operands=[
                PrereqCourse(course_num="15-122"),
                PrereqOr(
                    operands=[
                        PrereqCourse(course_num="21-127"),
                        PrereqCourse(course_num="15-151"),
                    ]
                ),
            ]
        )
    )


def test_nested_fully_satisfied_is_eligible():
    assert classify(_nested_course(), {"15-122", "21-127"}) == "eligible"


def test_nested_or_partially_satisfied_is_eligible():
    # AND-half done and one OR alternative met -> eligible.
    assert classify(_nested_course(), {"15-122", "15-151"}) == "eligible"


def test_nested_missing_lists_all_open_courses():
    assert missing_prereqs(_nested_course(), set()) == ["15-122", "21-127", "15-151"]


def test_nested_and_leaf_ruled_out_is_blocked():
    # 15-122 is required and confirmed unmet -> blocked regardless of the OR.
    assert classify(_nested_course(), {"21-127"}, ruled_out={"15-122"}) == "blocked"


# --- Safety rule: unparsed / missing data -> unconfirmed, NEVER blocked ------


def test_unparsed_prereq_is_unconfirmed_not_blocked():
    course = _course(PrereqUnparsed(raw="Prerequisite: consent of instructor"))
    assert classify(course, completed_courses=set()) == "unconfirmed"
    assert classify(course, set()) != "blocked"


def test_unparsed_stays_unconfirmed_even_with_ruled_out():
    # Even with ruled-out information present, unparsed data must not become blocked.
    course = _course(PrereqUnparsed(raw="see department"))
    assert classify(course, set(), ruled_out={"A", "B", "C"}) == "unconfirmed"


def test_unparsed_branch_in_and_keeps_it_unknown():
    # A satisfied conjunct plus an unparsed conjunct -> still unknown -> unconfirmed.
    course = _course(
        PrereqAnd(
            operands=[
                PrereqCourse(course_num="A"),
                PrereqUnparsed(raw="???"),
            ]
        )
    )
    assert classify(course, {"A"}) == "unconfirmed"
    # Unparsed contributes no concrete course number to ask about.
    assert missing_prereqs(course, {"A"}) == []


# --- Cascade: adding a course flips a dependent unconfirmed -> eligible ------


def test_cascade_completing_a_course_unlocks_dependent():
    dependent = _nested_course()  # needs 15-122 AND (21-127 OR 15-151)

    completed = {"15-122"}  # OR-half still open
    assert classify(dependent, completed) == "unconfirmed"
    assert missing_prereqs(dependent, completed) == ["21-127", "15-151"]

    # Student confirms 21-127 -> the OR is satisfied -> dependent becomes eligible.
    completed = completed | {"21-127"}
    assert classify(dependent, completed) == "eligible"
    assert missing_prereqs(dependent, completed) == []


def test_missing_prereqs_deduplicates_repeated_course():
    # Same course appearing in two unsatisfied branches is listed only once.
    course = _course(
        PrereqAnd(
            operands=[
                PrereqCourse(course_num="A"),
                PrereqOr(
                    operands=[
                        PrereqCourse(course_num="A"),
                        PrereqCourse(course_num="B"),
                    ]
                ),
            ]
        )
    )
    assert missing_prereqs(course, set()) == ["A", "B"]
