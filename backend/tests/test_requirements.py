"""Tests for degree-requirement loading and evaluation.

Correctness-relevant: a wrong "requirement satisfied" result misleads a student's
graduation planning. Covers every rule type (including a partially-filled
pick_min_units and a sequence_alternatives case), the requirement ranking signal,
and the completed-course regression.
"""

import pytest
from app.models import Course, Section, StudentProfile
from app.ranking import course_value
from app.requirements import (
    UNSTARTED_MULTIPLIER,
    W_REQUIREMENT,
    RequirementGroup,
    groups_advanced_by_courses,
    remaining_requirements,
    requirement_bonus,
)
from app.requirements_loader import load_requirements
from pydantic import ValidationError

REQUIREMENTS = load_requirements()

# Explicit units so unit-based rules are deterministic (no default fallback).
UNITS = {
    "15-410": 9.0,
    "15-411": 9.0,
    "15-281": 9.0,
    "16-384": 9.0,
    "15-455": 6.0,  # deliberately under 9
    "15-351": 9.0,  # excluded from the SCS pool
    "15-122": 10.0,
    "11-411": 6.0,  # a sub-9 AI elective (starts but doesn't satisfy the group)
}


def _profile(completed) -> StudentProfile:
    return StudentProfile(major="CS", expected_grad="2027", completed_courses=set(completed))


def _status_by_id(completed):
    status = remaining_requirements(_profile(completed), REQUIREMENTS, UNITS)
    return {g.id: g for g in status.groups}, status


# --- Loading & validation ----------------------------------------------------


def test_load_requirements_validates():
    assert REQUIREMENTS.major.startswith("Computer Science")
    assert REQUIREMENTS.disclaimer  # non-empty; not an official audit
    assert len(REQUIREMENTS.requirement_groups) == 15


def test_rule_missing_field_is_rejected():
    with pytest.raises(ValidationError):
        RequirementGroup(id="a", name="a", rule="all")  # empty courses
    with pytest.raises(ValidationError):
        RequirementGroup(id="x", name="x", rule="pick_n")  # missing n
    with pytest.raises(ValidationError):
        RequirementGroup(id="y", name="y", rule="pick_min_units")  # missing min_units
    with pytest.raises(ValidationError):
        RequirementGroup(id="z", name="z", rule="pick_n_min_units_each", n=2)  # no min_units_each
    with pytest.raises(ValidationError):
        RequirementGroup(id="u", name="u", rule="units")  # missing units_required


def test_unparseable_course_number_does_not_qualify_scs_pool():
    # A malformed course number can't be a 200-level SCS elective (defensive).
    _, status = _status_by_id(set())
    assert requirement_bonus("bogus", 12.0, REQUIREMENTS, status) == 0.0


# --- rule: all ---------------------------------------------------------------


def test_all_rule_satisfied_and_unsatisfied():
    by_id, _ = _status_by_id(set())
    core = by_id["cs_core"]
    assert core.satisfied is False
    assert core.started is False
    assert set(core.remaining_courses) == set(REQUIREMENTS.requirement_groups[0].courses)

    all_core = REQUIREMENTS.requirement_groups[0].courses
    by_id, _ = _status_by_id(set(all_core))
    assert by_id["cs_core"].satisfied is True
    assert by_id["cs_core"].remaining_courses == []


# --- rule: pick_n ------------------------------------------------------------


def test_pick_n_rule():
    by_id, _ = _status_by_id({"21-241"})  # one of the linear-algebra options
    assert by_id["math_linear_algebra"].satisfied is True

    by_id, _ = _status_by_id(set())
    la = by_id["math_linear_algebra"]
    assert la.satisfied is False
    assert la.courses_still_needed == 1


# --- rule: pick_min_units (satisfied + partially filled) ---------------------


def test_pick_min_units_satisfied():
    by_id, _ = _status_by_id({"15-281"})  # a 9-unit AI elective; min is 9
    assert by_id["cs_ai_elective"].satisfied is True


def test_pick_min_units_partially_filled():
    # Software Systems needs 12 units; one 9-unit course leaves 3 short.
    by_id, _ = _status_by_id({"15-410"})
    ss = by_id["cs_software_systems_elective"]
    assert ss.satisfied is False
    assert ss.started is True
    assert ss.units_still_needed == pytest.approx(3.0)
    assert "15-410" in ss.completed_from_group


def test_pick_min_units_defaults_units_when_unknown():
    # No units_lookup entry -> DEFAULT_COURSE_UNITS (9) -> satisfies min 9.
    status = remaining_requirements(_profile({"15-386"}), REQUIREMENTS, units_lookup=None)
    ai = next(g for g in status.groups if g.id == "cs_ai_elective")
    assert ai.satisfied is True


# --- rule: pick_n_min_units_each (open SCS pool + exclusions) ----------------


def test_pick_n_min_units_each_counts_qualifying_only():
    # Two qualifying SCS electives (>= 9 units, not excluded) -> satisfied.
    by_id, _ = _status_by_id({"15-410", "16-384"})
    assert by_id["cs_scs_electives"].satisfied is True

    # An excluded course does not count.
    by_id, _ = _status_by_id({"15-351"})
    assert by_id["cs_scs_electives"].satisfied is False
    assert by_id["cs_scs_electives"].completed_from_group == []

    # A sub-9-unit course does not count.
    by_id, _ = _status_by_id({"15-455"})
    assert by_id["cs_scs_electives"].satisfied is False


# --- sequence_alternatives ---------------------------------------------------


def test_sequence_alternatives():
    # The 36-225 & 36-226 sequence satisfies probability on its own.
    by_id, _ = _status_by_id({"36-225", "36-226"})
    assert by_id["math_probability"].satisfied is True

    # A single enumerated option also satisfies it (pick_n path).
    by_id, _ = _status_by_id({"36-218"})
    assert by_id["math_probability"].satisfied is True

    # A partial sequence is started but not satisfied.
    by_id, _ = _status_by_id({"36-225"})
    prob = by_id["math_probability"]
    assert prob.satisfied is False
    assert prob.started is True

    by_id, _ = _status_by_id(set())
    assert by_id["math_probability"].started is False


# --- rule: units (open, not enumerated) --------------------------------------


def test_units_rule_is_open_and_not_credited():
    by_id, _ = _status_by_id(set())
    sci = by_id["science_engineering"]
    assert sci.satisfied is False
    assert sci.open_ended is True
    assert sci.units_still_needed == pytest.approx(36.0)


# --- Ranking signal ----------------------------------------------------------


def test_requirement_bonus_zero_for_non_requirement_course():
    _, status = _status_by_id(set())
    assert requirement_bonus("99-999", 9.0, REQUIREMENTS, status) == 0.0


def test_requirement_bonus_positive_for_advancing_course():
    _, status = _status_by_id(set())
    # 15-451 is in cs_core (an unmet, unstarted 'all' group).
    bonus = requirement_bonus("15-451", 12.0, REQUIREMENTS, status)
    assert bonus == pytest.approx(W_REQUIREMENT * UNSTARTED_MULTIPLIER)


def test_unstarted_group_outweighs_started_group():
    # 07-280 advances only the AI elective (dept 07 isn't in the SCS pool), so its
    # bonus tracks that one group's started-ness. Completing a sub-9 AI course
    # (11-411 @ 6u) starts the group without satisfying it.
    _, unstarted = _status_by_id(set())
    _, started = _status_by_id({"11-411"})
    assert requirement_bonus("07-280", 9.0, REQUIREMENTS, unstarted) > requirement_bonus(
        "07-280", 9.0, REQUIREMENTS, started
    )


def _course(num: str) -> Course:
    # Identical FCE/interest profile so course_value is equal across course numbers.
    return Course(
        course_num=num,
        title="Elective",
        units=9.0,
        prereqs=None,
        description="an elective",
        fce_workload_hours=10.0,
        fce_rating=4.0,
        sections=[
            Section(
                course_num=num, title="Elective", units=9.0, section_id="A",
                days=["M"], begin="10:00", end="10:50", location="X",
            )
        ],
    )


def test_requirement_course_ranks_above_equivalent_non_requirement_course():
    profile = _profile(set())
    _, status = _status_by_id(set())
    advancing = _course("15-451")  # in cs_core
    plain = _course("99-999")  # in no group

    # Same base score...
    assert course_value(advancing, profile) == course_value(plain, profile)
    # ...but the requirement bonus lifts the advancing course above the elective.
    adv_score = course_value(advancing, profile) + requirement_bonus(
        "15-451", 9.0, REQUIREMENTS, status
    )
    plain_score = course_value(plain, profile) + requirement_bonus(
        "99-999", 9.0, REQUIREMENTS, status
    )
    assert adv_score > plain_score


def test_groups_advanced_by_courses_names_the_group():
    _, status = _status_by_id(set())
    advanced = groups_advanced_by_courses(["15-451"], UNITS, REQUIREMENTS, status)
    assert any(g.id == "cs_core" for g in advanced)
    # A non-requirement course advances nothing.
    assert groups_advanced_by_courses(["99-999"], UNITS, REQUIREMENTS, status) == []


# --- Regression: a completed course still counts toward its group ------------


def test_completed_course_counts_toward_its_group():
    # 15-122 is a cs_core course; completing it must register as progress there.
    by_id, _ = _status_by_id({"15-122"})
    assert "15-122" in by_id["cs_core"].completed_from_group
    assert by_id["cs_core"].started is True
