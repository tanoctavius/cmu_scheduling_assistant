"""Tests for the upfront prereq tick-off checklist source.

Asserts the checklist scope: (1) all core courses (from all-rule requirement
groups) appear, (2) a known prerequisite course appears, and (3) a course that is
neither core nor a prerequisite for anything does NOT appear. The scope is a
single function so it's easy to adjust later.
"""

from app.checklist import checklist_courses
from app.data_loader import load_courses
from app.requirements_loader import load_requirements

CATALOG = load_courses()
REQUIREMENTS = load_requirements()


def _checklist():
    return checklist_courses("Computer Science", CATALOG, REQUIREMENTS)


def _all_nums(groups) -> list[str]:
    return [item.course_num for g in groups for item in g.courses]


def _core_course_nums() -> set[str]:
    return {
        num
        for g in REQUIREMENTS.requirement_groups
        if g.rule == "all"
        for num in g.courses
    }


def test_all_core_courses_appear():
    nums = set(_all_nums(_checklist()))
    core = _core_course_nums()
    assert core, "expected some all-rule core courses in the requirements file"
    assert core <= nums  # every core course is present


def test_known_prerequisite_appears():
    # 15-112 is a prerequisite of 15-122 in the catalog -> must be in the checklist,
    # even though it isn't itself a core course.
    nums = set(_all_nums(_checklist()))
    assert "15-112" in nums


def test_non_core_non_prereq_course_is_excluded():
    # 76-101 is in the catalog but is neither a core course nor a prerequisite of
    # anything -> it must NOT appear.
    nums = set(_all_nums(_checklist()))
    assert "76-101" not in nums
    # Same for upper-division courses that nothing depends on and aren't core.
    assert "21-259" not in nums
    assert "21-241" not in nums


def test_grouped_under_headers_and_no_duplicates():
    groups = _checklist()
    headers = [g.header for g in groups]
    assert "Common prerequisites" in headers
    # Core groups use their requirement-group names as headers (data-driven).
    assert any("Core" in h for h in headers)

    all_nums = _all_nums(groups)
    assert len(all_nums) == len(set(all_nums))  # each course exactly once


def test_common_prerequisites_excludes_courses_already_in_core():
    # 15-122 is both a core course and a prerequisite; it should appear once, under
    # its core group, not duplicated in "Common prerequisites".
    groups = _checklist()
    common = next(g for g in groups if g.header == "Common prerequisites")
    common_nums = {i.course_num for i in common.courses}
    assert "15-122" not in common_nums


def test_focused_size():
    # A focused list, not the entire catalog or requirements file.
    assert len(_all_nums(_checklist())) <= 20


def test_catalog_courses_carry_title_and_units():
    # Items present in the catalog show a real title/units; others fall back to the
    # course number with no units.
    items = {i.course_num: i for g in _checklist() for i in g.courses}
    c112 = items["15-112"]
    assert c112.title != "15-112"  # real catalog title
    assert c112.units == 12.0
    # A core course not in the sample catalog falls back gracefully.
    c210 = items["15-210"]
    assert c210.title == "15-210"
    assert c210.units is None
