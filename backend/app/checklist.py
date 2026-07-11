"""The upfront prereq tick-off checklist.

The survey shows this list so a student can confirm their history in one place,
seeding ``completed_courses`` and cutting down on later per-recommendation
confirmation questions. Scope is deliberately **focused** — a 40-item checklist is
worse UX than a scannable one — so it is limited to:

(a) the required **core** courses from the major's requirements (the ``all``-rule
    groups, e.g. CS Core and Math Core), and
(b) any course that is a **prerequisite** of at least one other course in the
    catalog, computed from the parsed prerequisite graph (not a hardcoded list, so
    it stays correct as data changes).

Everything is a single function, :func:`checklist_courses`, so the scope is easy to
adjust later (e.g. collapse less-common prerequisites behind a "show more" toggle).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.models import Course, PrereqAnd, PrereqCourse, PrereqNode, PrereqOr
from app.requirements import Requirements

# Header used for prerequisite courses that aren't already listed under a core group.
_COMMON_PREREQS_HEADER = "Common prerequisites"


class ChecklistItem(BaseModel):
    course_num: str
    title: str
    units: Optional[float] = None  # None when the course isn't in our catalog yet


class ChecklistGroup(BaseModel):
    header: str
    courses: list[ChecklistItem] = Field(default_factory=list)


def _collect_referenced(node: Optional[PrereqNode], out: set[str]) -> None:
    """Accumulate every course number that appears as a prerequisite leaf."""
    if isinstance(node, PrereqCourse):
        out.add(node.course_num)
    elif isinstance(node, (PrereqAnd, PrereqOr)):
        for operand in node.operands:
            _collect_referenced(operand, out)
    # None / PrereqUnparsed reference no concrete course.


def prerequisite_courses(catalog: list[Course]) -> set[str]:
    """Course numbers that are a prerequisite of at least one catalog course.

    Derived from the parsed prerequisite graph, so it stays correct as the catalog
    changes — no hardcoded list.
    """
    referenced: set[str] = set()
    for course in catalog:
        _collect_referenced(course.prereqs, referenced)
    return referenced


def checklist_courses(
    major: str,
    catalog: list[Course],
    requirements: Requirements,
) -> list[ChecklistGroup]:
    """Build the focused, grouped prereq checklist for a major.

    Args:
        major: The student's major. Retained so scope can vary per major later;
            v1 uses the single provided ``requirements`` document.
        catalog: The course catalog (source of the prerequisite graph and of
            titles/units for display).
        requirements: The major's curated requirements.

    Returns:
        Grouped checklist sections: one per ``all``-rule requirement group (using
        the group's name as the header), followed by a "Common prerequisites"
        section for prerequisite courses not already listed under a core group.
        Each course appears exactly once.
    """
    by_num = {c.course_num: c for c in catalog}

    def item(course_num: str) -> ChecklistItem:
        course = by_num.get(course_num)
        return ChecklistItem(
            course_num=course_num,
            title=course.title if course else course_num,
            units=course.units if course else None,
        )

    groups: list[ChecklistGroup] = []
    listed: set[str] = set()

    # (a) One section per all-rule group, in file order.
    for group in requirements.requirement_groups:
        if group.rule != "all":
            continue
        section = [item(num) for num in group.courses if num not in listed]
        for it in section:
            listed.add(it.course_num)
        if section:
            groups.append(ChecklistGroup(header=group.name, courses=section))

    # (b) Prerequisite courses not already surfaced under a core group.
    extra = sorted(n for n in prerequisite_courses(catalog) if n not in listed)
    if extra:
        groups.append(
            ChecklistGroup(
                header=_COMMON_PREREQS_HEADER, courses=[item(n) for n in extra]
            )
        )

    return groups
