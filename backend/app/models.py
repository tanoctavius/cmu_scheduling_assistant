"""Core data models for cmu-scheduler.

These Pydantic models are the normalized shape of everything downstream of
ingestion. Whether a course came from a live scrape or a committed sample
fixture, it conforms to these models — nothing below the catalog store cares
which.

Prerequisite structure
----------------------
Prerequisites are expressed as a small **recursive AND/OR tree**, not a flat
list, because real CMU prereqs nest (e.g. "21-127 AND (15-112 OR 15-122)").

A ``PrereqNode`` is one of three shapes, distinguished by a ``type`` tag:

- ``{"type": "course", "course_num": "21-127"}`` — a leaf: one required course.
- ``{"type": "and", "operands": [ ...nodes... ]}`` — all operands must hold.
- ``{"type": "or",  "operands": [ ...nodes... ]}`` — at least one must hold.
- ``{"type": "unparsed", "raw": "..."}`` — ingestion found prerequisite text but
  could not parse it into the tree above. This is **not** "no prereqs"; it means
  "unknown requirement". The classifier treats it as unknown and defaults the
  course to ``unconfirmed`` (never ``blocked``) — the non-negotiable safety rule.

Three distinct situations, three distinct representations — keep them separate:

- ``prereqs = None``  → the course genuinely has **no** prerequisites → eligible.
- ``prereqs`` = a tree → a real, parsed requirement → evaluated normally.
- ``PrereqUnparsed``  → we had prereq text but **could not parse it** → unconfirmed.

Example — "21-127 AND (15-112 OR 15-122)"::

    {
        "type": "and",
        "operands": [
            {"type": "course", "course_num": "21-127"},
            {
                "type": "or",
                "operands": [
                    {"type": "course", "course_num": "15-112"},
                    {"type": "course", "course_num": "15-122"}
                ]
            }
        ]
    }

Note: these models describe *shape and validity only*. Evaluating a prereq tree
against a student's completed set (the eligible/unconfirmed/blocked
classification) is the job of the deterministic classifier in a later stage —
not of the models here.
"""

from __future__ import annotations

from datetime import time
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

# A single meeting day. CMU uses R for Thursday to disambiguate from Tuesday.
Day = Literal["M", "T", "W", "R", "F"]


# --- Prerequisite tree -------------------------------------------------------


class PrereqCourse(BaseModel):
    """Leaf node: a single required course, by course number (e.g. "15-122")."""

    type: Literal["course"] = "course"
    course_num: str


class PrereqAnd(BaseModel):
    """Conjunction: every operand must be satisfied."""

    type: Literal["and"] = "and"
    operands: list[PrereqNode]


class PrereqOr(BaseModel):
    """Disjunction: at least one operand must be satisfied."""

    type: Literal["or"] = "or"
    operands: list[PrereqNode]


class PrereqUnparsed(BaseModel):
    """Prerequisite text ingestion could not parse into an AND/OR tree.

    Carries the original ``raw`` text for display/debugging. Semantically it is
    an *unknown* requirement: the classifier defaults such a course to
    ``unconfirmed`` (never ``blocked``) so the failure mode is an extra
    confirmation question, never a silently hidden course.
    """

    type: Literal["unparsed"] = "unparsed"
    raw: str


# Discriminated union: Pydantic picks the variant by the "type" tag.
PrereqNode = Annotated[
    Union[PrereqCourse, PrereqAnd, PrereqOr, PrereqUnparsed],
    Field(discriminator="type"),
]


# --- Sections & courses ------------------------------------------------------


class Section(BaseModel):
    """One scheduled meeting of a course (a lecture/recitation section)."""

    course_num: str
    title: str
    units: float
    section_id: str
    days: list[Day]
    begin: time
    end: time
    location: str


class Course(BaseModel):
    """A course and its offered sections, plus catalog and FCE metadata."""

    course_num: str
    title: str
    units: float
    # None means "no prerequisites"; see the module docstring for the tree shape.
    prereqs: Optional[PrereqNode] = None
    description: str
    fce_workload_hours: float
    fce_rating: float
    sections: list[Section]


# --- Student input -----------------------------------------------------------


class TimeBlock(BaseModel):
    """A recurring block of time the student is unavailable (a commitment)."""

    label: Optional[str] = None
    days: list[Day]
    begin: time
    end: time


class StudentProfile(BaseModel):
    """The survey inputs that drive scheduling and recommendation."""

    major: str
    expected_grad: str
    completed_courses: set[str] = Field(default_factory=set)
    commitments: list[TimeBlock] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    career_goals: list[str] = Field(default_factory=list)


# Resolve the forward references used in the recursive prereq operands.
PrereqAnd.model_rebuild()
PrereqOr.model_rebuild()
