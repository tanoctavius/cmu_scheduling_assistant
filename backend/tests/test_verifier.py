"""Tests for the deterministic claim verifier.

Correctness-critical: this is the gate that stops a wrong LLM claim from reaching
the student. Covers true claims passing, and each falsifiable claim type failing
with the correct corrected value.
"""

from datetime import time

from app.models import Schedule, Section
from app.verifier import (
    IncludesCourseClaim,
    NoClassOnClaim,
    NoConflictsClaim,
    TotalUnitsClaim,
    verify,
)


def _section(course_num, section_id, days, begin, end, units) -> Section:
    return Section(
        course_num=course_num,
        title=course_num,
        units=units,
        section_id=section_id,
        days=days,
        begin=time(*begin),
        end=time(*end),
        location="X",
    )


def _friday_schedule() -> Schedule:
    """21-259 meets M/W/F; 15-122 meets T/R. All weekdays busy; 19 units."""
    return Schedule(
        sections=[
            _section("21-259", "A", ["M", "W", "F"], (9, 0), (9, 50), 9.0),
            _section("15-122", "A", ["T", "R"], (9, 30), (10, 50), 10.0),
        ],
        total_units=19.0,
        total_workload_hours=24.0,
        score=1.0,
    )


def _friday_free_schedule() -> Schedule:
    """15-122 T/R; 15-213 M/W. Friday is free; 22 units."""
    return Schedule(
        sections=[
            _section("15-122", "A", ["T", "R"], (9, 30), (10, 50), 10.0),
            _section("15-213", "A", ["M", "W"], (14, 0), (15, 20), 12.0),
        ],
        total_units=22.0,
        total_workload_hours=31.0,
        score=1.0,
    )


# --- True claims pass --------------------------------------------------------


def test_true_claims_all_pass():
    schedule = _friday_free_schedule()
    result = verify(
        [
            NoClassOnClaim(day="F"),  # Friday genuinely free
            TotalUnitsClaim(value=22.0),  # correct total
            IncludesCourseClaim(course_num="15-122"),  # present
            NoConflictsClaim(),  # no overlaps
        ],
        schedule,
    )
    assert result.all_passed
    assert result.failed_checks == []
    assert len(result.passed_claims) == 4


# --- False "Fridays off" ------------------------------------------------------


def test_false_fridays_off_fails_with_correction():
    schedule = _friday_schedule()  # has a Friday class (21-259)
    result = verify([NoClassOnClaim(day="F")], schedule)

    assert not result.all_passed
    (check,) = result.checks
    assert check.ok is False
    # Correction reports the actual free days — F is not among them.
    assert "F" not in check.corrected_value
    assert "F" in check.message


def test_no_class_on_free_day_passes():
    schedule = _friday_free_schedule()
    result = verify([NoClassOnClaim(day="F")], schedule)
    assert result.all_passed


# --- Wrong unit total --------------------------------------------------------


def test_wrong_unit_total_fails_with_correction():
    schedule = _friday_schedule()  # 19 units
    result = verify([TotalUnitsClaim(value=45.0)], schedule)

    (check,) = result.checks
    assert check.ok is False
    assert check.corrected_value == 19.0


def test_correct_unit_total_passes():
    schedule = _friday_schedule()
    result = verify([TotalUnitsClaim(value=19.0)], schedule)
    assert result.all_passed


# --- Course not in schedule --------------------------------------------------


def test_includes_absent_course_fails():
    schedule = _friday_schedule()  # 21-259, 15-122
    result = verify([IncludesCourseClaim(course_num="15-213")], schedule)

    (check,) = result.checks
    assert check.ok is False
    assert check.corrected_value == ["15-122", "21-259"]
    assert "15-213" in check.message


# --- Conflict detection ------------------------------------------------------


def test_no_conflicts_claim_fails_on_overlapping_schedule():
    # A manually-built schedule the solver would never produce: two sections
    # overlap on Monday. The verifier must catch the false "no conflicts" claim.
    schedule = Schedule(
        sections=[
            _section("11-111", "A", ["M"], (9, 0), (9, 50), 9.0),
            _section("22-222", "A", ["M"], (9, 30), (10, 20), 9.0),
        ],
        total_units=18.0,
    )
    result = verify([NoConflictsClaim()], schedule)

    (check,) = result.checks
    assert check.ok is False
    assert check.corrected_value == [["11-111", "22-222"]]


# --- Mixed batch + raw dict form (as the LLM emits) --------------------------


def test_mixed_batch_separates_passed_and_failed():
    schedule = _friday_schedule()
    result = verify(
        [
            TotalUnitsClaim(value=19.0),  # pass
            NoClassOnClaim(day="F"),  # fail
            IncludesCourseClaim(course_num="21-259"),  # pass
        ],
        schedule,
    )
    assert len(result.passed_claims) == 2
    assert len(result.failed_checks) == 1
    assert isinstance(result.failed_checks[0].claim, NoClassOnClaim)


def test_accepts_raw_dict_claims_from_llm():
    schedule = _friday_schedule()
    result = verify(
        [
            {"type": "total_units", "value": 19.0},  # pass
            {"type": "total_units", "value": 45.0},  # fail
        ],
        schedule,
    )
    assert result.checks[0].ok is True
    assert result.checks[1].ok is False
    assert result.checks[1].corrected_value == 19.0
