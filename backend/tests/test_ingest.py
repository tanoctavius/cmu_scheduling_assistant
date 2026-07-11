"""Tests for self-owned ingestion, run against committed fixtures (no network).

Proves the dry-run pipeline parses the fixtures into valid models, round-trips
through the same JSON shape as ``data/samples/courses.json``, and exercises the
prereq-text parser — including the unparseable -> ``PrereqUnparsed`` safety path.
"""

from datetime import time

from app.data_loader import load_courses
from app.models import Course, PrereqAnd, PrereqCourse, PrereqUnparsed

from ingest.ingest import run
from ingest.parsers import parse_prereqs


def _by_num(courses):
    return {c.course_num: c for c in courses}


def test_dry_run_ingest_produces_valid_models(tmp_path):
    out = tmp_path / "courses.json"
    courses = run(dry_run=True, out_path=out)

    assert courses, "expected courses from the fixtures"
    assert all(isinstance(c, Course) for c in courses)

    # The written JSON reloads through the app's own loader -> shape matches samples.
    reloaded = load_courses(out)
    assert len(reloaded) == len(courses)


def test_sections_and_units_parsed_from_soc():
    by = _by_num(run(dry_run=True))

    c112 = by["15-112"]
    assert c112.units == 12.0
    assert c112.title == "Fundamentals of Programming and Computer Science"
    assert len(c112.sections) == 2
    sec_a = c112.sections[0]
    assert sec_a.section_id == "A"
    assert sec_a.days == ["M", "W", "F"]
    assert sec_a.begin == time(10, 0)
    assert sec_a.end == time(10, 50)
    assert sec_a.location == "DH 2210"
    # 01:00PM must parse to 13:00.
    assert c112.sections[1].begin == time(13, 0)


def test_prereqs_from_catalog():
    by = _by_num(run(dry_run=True))

    # No prereqs.
    assert by["15-112"].prereqs is None
    # Simple single-course prereq.
    assert isinstance(by["15-122"].prereqs, PrereqCourse)
    assert by["15-122"].prereqs.course_num == "15-112"
    # Nested AND/OR: 15-122 and (21-127 or 15-151).
    assert isinstance(by["15-150"].prereqs, PrereqAnd)
    # Unparseable prose -> PrereqUnparsed (safety path), never blocked.
    assert isinstance(by["21-241"].prereqs, PrereqUnparsed)


def test_fce_defaults_when_absent():
    by = _by_num(run(dry_run=True))
    # 15-112 is in the FCE CSV.
    assert by["15-112"].fce_rating == 4.5
    assert by["15-112"].fce_workload_hours == 12.5
    # 21-241 is intentionally absent from the FCE export -> defaults to 0.0.
    assert by["21-241"].fce_rating == 0.0
    assert by["21-241"].fce_workload_hours == 0.0


def test_prereq_text_parser_variants():
    assert parse_prereqs(None) is None
    assert parse_prereqs("None") is None
    assert parse_prereqs("Prerequisites: 15-112").course_num == "15-112"

    nested = parse_prereqs("15-122 and (21-127 or 15-151)")
    assert isinstance(nested, PrereqAnd)
    assert len(nested.operands) == 2

    # Prose we can't model must degrade to unparsed, not silently drop or block.
    assert isinstance(parse_prereqs("Grade of C or better in 21-120"), PrereqUnparsed)
    # Unbalanced parens -> unparsed rather than crashing.
    assert isinstance(parse_prereqs("(15-112 or 15-122"), PrereqUnparsed)
