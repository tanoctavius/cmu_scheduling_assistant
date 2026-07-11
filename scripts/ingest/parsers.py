"""Parsers for the official CMU sources — written and owned by us.

These parse our *own* normalized structures out of CMU's HTML/CSV. They are
written against the current page shapes (captured in ``data/fixtures/``), on the
explicit assumption that the 2019 ``cmu_course_api`` selectors are stale. When a
CMU page changes, the fix lives here — under our control — not in an external
package.

Three parsers:
- :func:`parse_schedule_of_classes` — sections, days/times, units (from the SOC).
- :func:`parse_course_catalog` — descriptions and prerequisite trees (from the
  Course Catalog). Prerequisite *text* is turned into the models' AND/OR tree by
  :func:`parse_prereqs`; text we cannot model becomes ``PrereqUnparsed`` so the
  classifier defaults the course to ``unconfirmed``, never ``blocked``.
- :func:`parse_fce_csv` — workload hours and ratings from a manual FCE export.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import time
from typing import Optional

from bs4 import BeautifulSoup

from app.models import (
    PrereqAnd,
    PrereqCourse,
    PrereqNode,
    PrereqOr,
    PrereqUnparsed,
)

_COURSE_NUM = r"\d{2}-\d{3}"


# --- Small field parsers -----------------------------------------------------


def _parse_days(text: str) -> list[str]:
    """"MWF" / "TR" -> ["M","W","F"] / ["T","R"] (R is Thursday)."""
    return [ch for ch in text.strip().upper() if ch in "MTWRF"]


def _parse_time(text: str) -> time:
    """Parse "10:00AM" / "01:30PM" / "13:00" into a ``time``."""
    cleaned = text.strip().upper().replace(" ", "")
    m = re.match(r"^(\d{1,2}):(\d{2})(AM|PM)?$", cleaned)
    if not m:
        raise ValueError(f"unrecognized time: {text!r}")
    hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3)
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    return time(hour, minute)


# --- Prerequisite text -> AND/OR tree ----------------------------------------

_TOKEN_RE = re.compile(rf"({_COURSE_NUM})|(\band\b)|(\bor\b)|([()])", re.IGNORECASE)


def parse_prereqs(text: Optional[str]) -> Optional[PrereqNode]:
    """Parse prerequisite text into a prereq tree, ``None``, or ``PrereqUnparsed``.

    - Empty / "None" / "N/A" -> ``None`` (genuinely no prerequisites).
    - A clean boolean of course numbers (e.g. "15-122 and (21-127 or 15-151)")
      -> a :class:`PrereqAnd`/:class:`PrereqOr`/:class:`PrereqCourse` tree.
    - Anything with prose we can't model (e.g. "Grade of C or better in 21-120")
      -> :class:`PrereqUnparsed`, preserving the original text. This is the
      safety default: unmodelable data becomes *unconfirmed* downstream, never a
      silently hidden (blocked) course.
    """
    if text is None:
        return None
    raw = text.strip()
    body = re.sub(r"^\s*prerequisite[s]?\s*:?\s*", "", raw, flags=re.IGNORECASE).strip()
    if not body or body.lower() in {"none", "n/a"}:
        return None

    # If anything other than course codes / and / or / parens / separators
    # remains, it's prose we cannot faithfully model -> unparsed.
    leftover = _TOKEN_RE.sub(" ", body)
    leftover = re.sub(r"[\s,;.]+", " ", leftover).strip()
    if leftover:
        return PrereqUnparsed(raw=raw)

    tokens: list[tuple] = []
    for m in _TOKEN_RE.finditer(body):
        if m.group(1):
            tokens.append(("course", m.group(1)))
        elif m.group(2):
            tokens.append(("and",))
        elif m.group(3):
            tokens.append(("or",))
        else:
            tokens.append((m.group(4),))  # "(" or ")"

    try:
        node, pos = _parse_or(tokens, 0)
        if pos != len(tokens):
            raise ValueError("trailing tokens")
    except (ValueError, IndexError):
        return PrereqUnparsed(raw=raw)
    return node


def _parse_or(tokens: list[tuple], i: int) -> tuple[PrereqNode, int]:
    node, i = _parse_and(tokens, i)
    operands = [node]
    while i < len(tokens) and tokens[i][0] == "or":
        rhs, i = _parse_and(tokens, i + 1)
        operands.append(rhs)
    if len(operands) == 1:
        return operands[0], i
    return PrereqOr(operands=operands), i


def _parse_and(tokens: list[tuple], i: int) -> tuple[PrereqNode, int]:
    node, i = _parse_factor(tokens, i)
    operands = [node]
    while i < len(tokens) and tokens[i][0] == "and":
        rhs, i = _parse_factor(tokens, i + 1)
        operands.append(rhs)
    if len(operands) == 1:
        return operands[0], i
    return PrereqAnd(operands=operands), i


def _parse_factor(tokens: list[tuple], i: int) -> tuple[PrereqNode, int]:
    if i >= len(tokens):
        raise ValueError("expected a course or '('")
    token = tokens[i]
    if token[0] == "course":
        return PrereqCourse(course_num=token[1]), i + 1
    if token[0] == "(":
        node, i = _parse_or(tokens, i + 1)
        if i >= len(tokens) or tokens[i][0] != ")":
            raise ValueError("unbalanced parentheses")
        return node, i + 1
    raise ValueError(f"unexpected token: {token}")


# --- Source parsers ----------------------------------------------------------


def parse_schedule_of_classes(html: str) -> dict[str, dict]:
    """Parse SOC HTML into ``{course_num: {title, units, sections}}``.

    Each section is a dict with ``section_id``, ``days``, ``begin``, ``end``,
    ``location`` (typed: ``days`` is a list, ``begin``/``end`` are ``time``).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, dict] = {}
    for div in soup.select("div.course"):
        course_num = (div.get("data-course") or "").strip()
        if not course_num:
            continue
        units = float(div.get("data-units", "0") or "0")
        title_el = div.select_one("h3.course-title")
        title = title_el.get_text(strip=True) if title_el else course_num
        title = re.sub(rf"^{_COURSE_NUM}\s*", "", title).strip()

        sections = []
        for row in div.select("tr.section"):
            sections.append(
                {
                    "section_id": row.select_one(".sec").get_text(strip=True),
                    "days": _parse_days(row.select_one(".days").get_text()),
                    "begin": _parse_time(row.select_one(".begin").get_text()),
                    "end": _parse_time(row.select_one(".end").get_text()),
                    "location": row.select_one(".loc").get_text(strip=True),
                }
            )
        out[course_num] = {"title": title, "units": units, "sections": sections}
    return out


def parse_course_catalog(html: str) -> dict[str, dict]:
    """Parse catalog HTML into ``{course_num: {description, prereqs}}``.

    ``prereqs`` is a prereq tree, ``None``, or ``PrereqUnparsed`` per
    :func:`parse_prereqs`.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, dict] = {}
    for div in soup.select("div.course-detail"):
        course_num = (div.get("data-course") or "").strip()
        if not course_num:
            continue
        desc_el = div.select_one(".desc")
        prereq_el = div.select_one(".prereqs")
        out[course_num] = {
            "description": desc_el.get_text(strip=True) if desc_el else "",
            "prereqs": parse_prereqs(prereq_el.get_text(strip=True) if prereq_el else None),
        }
    return out


def parse_fce_csv(text: str) -> dict[str, dict]:
    """Parse a manual FCE CSV export into ``{course_num: {workload, rating}}``.

    Expected header: ``course_num,workload_hours,rating``. FCE data is a manual
    export because the FCE portal is auth-gated (project context §4, §8).
    """
    out: dict[str, dict] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        course_num = (row.get("course_num") or "").strip()
        if not course_num:
            continue
        out[course_num] = {
            "workload": float(row["workload_hours"]),
            "rating": float(row["rating"]),
        }
    return out
