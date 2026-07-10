"""Tests that the sample fixture loads, validates, and parses AND/OR prereqs."""

from datetime import time

from app.data_loader import load_courses
from app.models import Course, PrereqAnd, PrereqCourse, PrereqOr


def _by_num(courses: list[Course]) -> dict[str, Course]:
    return {c.course_num: c for c in courses}


def test_sample_data_loads_and_validates():
    courses = load_courses()
    assert len(courses) == 8
    assert all(isinstance(c, Course) for c in courses)
    # Every course has at least one section, and section times parse to time objects.
    for course in courses:
        assert course.sections
        for section in course.sections:
            assert isinstance(section.begin, time)
            assert isinstance(section.end, time)
            assert section.begin < section.end
            assert set(section.days) <= {"M", "T", "W", "R", "F"}


def test_course_with_no_prereqs_is_none():
    courses = _by_num(load_courses())
    assert courses["15-112"].prereqs is None
    assert courses["21-127"].prereqs is None


def test_simple_course_prereq_parses():
    courses = _by_num(load_courses())
    prereq = courses["15-122"].prereqs
    assert isinstance(prereq, PrereqCourse)
    assert prereq.course_num == "15-112"


def test_and_or_prereq_parses():
    # 15-150 requires: 15-122 AND (21-127 OR 15-151)
    courses = _by_num(load_courses())
    prereq = courses["15-150"].prereqs

    assert isinstance(prereq, PrereqAnd)
    assert len(prereq.operands) == 2

    leaf, disjunction = prereq.operands
    assert isinstance(leaf, PrereqCourse)
    assert leaf.course_num == "15-122"

    assert isinstance(disjunction, PrereqOr)
    or_nums = {op.course_num for op in disjunction.operands}
    assert or_nums == {"21-127", "15-151"}
    assert all(isinstance(op, PrereqCourse) for op in disjunction.operands)
