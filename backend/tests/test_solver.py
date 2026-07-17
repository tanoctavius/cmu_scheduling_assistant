"""Tests for the fused solve-and-rank engine.

Correctness-critical. Property-style tests generate many random scenarios and
assert the schedule invariants hold on *every* returned schedule: no time
conflict, commitments respected, units cap honored, one section per course,
blocked courses excluded, and at most K results. Plus targeted ranking checks.
"""

import random
from datetime import time

from app.models import Course, Section, StudentProfile, TimeBlock
from app.ranking import W_RATING, W_WORKLOAD, course_value, schedule_score
from app.solver import schedule_key, solve

DAYS = ["M", "T", "W", "R", "F"]


# --- Independent invariant checkers (not importing the solver's own helpers) --


def _intervals(days, begin: time, end: time):
    b = begin.hour * 60 + begin.minute
    e = end.hour * 60 + end.minute
    return [(d, b, e) for d in days]


def _overlap(a, b) -> bool:
    for ad, ab, ae in a:
        for bd, bb, be in b:
            if ad == bd and ab < be and bb < ae:
                return True
    return False


# --- Random scenario generation ----------------------------------------------


def _rand_section(rng, course_num, title, units) -> Section:
    begin_h = rng.randint(8, 18)
    begin = time(begin_h, rng.choice([0, 30]))
    duration = rng.choice([50, 80])
    total = begin.hour * 60 + begin.minute + duration
    end = time(total // 60, total % 60)
    num_days = rng.choice([1, 2, 3])
    days = sorted(rng.sample(DAYS, num_days), key=DAYS.index)
    return Section(
        course_num=course_num,
        title=title,
        units=units,
        section_id=f"S{rng.randint(1, 99)}",
        days=days,
        begin=begin,
        end=end,
        location="TBD",
    )


def _rand_course(rng, i) -> Course:
    course_num = f"10-{100 + i}"
    title = f"Course {i}"
    units = float(rng.choice([6, 9, 10, 12]))
    n_sections = rng.randint(1, 3)
    sections = [_rand_section(rng, course_num, title, units) for _ in range(n_sections)]
    return Course(
        course_num=course_num,
        title=title,
        units=units,
        prereqs=None,
        description=f"Description of course {i}.",
        fce_workload_hours=float(rng.randint(4, 20)),
        fce_rating=round(rng.uniform(2.5, 4.9), 1),
        sections=sections,
    )


def _rand_scenario(rng):
    n_courses = rng.randint(1, 7)
    courses = [_rand_course(rng, i) for i in range(n_courses)]
    n_commit = rng.randint(0, 2)
    commitments = []
    for _ in range(n_commit):
        h = rng.randint(8, 17)
        commitments.append(
            TimeBlock(
                label="busy",
                days=sorted(rng.sample(DAYS, rng.randint(1, 2)), key=DAYS.index),
                begin=time(h, 0),
                end=time(h + 1, 0),
            )
        )
    profile = StudentProfile(
        major="CS",
        expected_grad="2027",
        interests=rng.sample(["Course 1", "Course 3", "systems", "theory"], k=1),
        commitments=commitments,
    )
    units_cap = float(rng.choice([18, 27, 36, 45]))
    return courses, profile, commitments, units_cap


# --- Property tests ----------------------------------------------------------


def test_no_returned_schedule_has_a_time_conflict():
    rng = random.Random(1)
    for _ in range(300):
        courses, profile, commitments, cap = _rand_scenario(rng)
        for sched in solve(courses, profile, units_cap=cap, k=5):
            ivs = [_intervals(s.days, s.begin, s.end) for s in sched.sections]
            for a in range(len(ivs)):
                for b in range(a + 1, len(ivs)):
                    assert not _overlap(ivs[a], ivs[b]), "two sections overlap"


def test_commitments_always_respected():
    rng = random.Random(2)
    for _ in range(300):
        courses, profile, commitments, cap = _rand_scenario(rng)
        busy = []
        for c in commitments:
            busy += _intervals(c.days, c.begin, c.end)
        for sched in solve(courses, profile, units_cap=cap, k=5):
            for s in sched.sections:
                sec = _intervals(s.days, s.begin, s.end)
                assert not _overlap(sec, busy), "section overlaps a commitment"


def test_units_cap_never_exceeded():
    rng = random.Random(3)
    for _ in range(300):
        courses, profile, commitments, cap = _rand_scenario(rng)
        for sched in solve(courses, profile, units_cap=cap, k=5):
            total = sum(s.units for s in sched.sections)
            assert total <= cap
            assert sched.total_units <= cap
            # Cached total matches the sections it reports.
            assert abs(sched.total_units - total) < 1e-9


def test_at_most_one_section_per_course():
    rng = random.Random(4)
    for _ in range(300):
        courses, profile, commitments, cap = _rand_scenario(rng)
        for sched in solve(courses, profile, units_cap=cap, k=5):
            nums = sched.course_nums
            assert len(nums) == len(set(nums)), "a course appears twice"


def test_no_two_returned_schedules_are_identical():
    # Regression: the DFS reaches the same section set by many paths (every
    # "skip this course" step re-offers the identical `chosen` list), which used
    # to fill the top-K heap with copies — the student saw K indistinguishable
    # "options". Every returned option must be materially distinct.
    rng = random.Random(11)
    for _ in range(200):
        courses, profile, commitments, units_cap = _rand_scenario(rng)
        schedules = solve(
            courses, profile, units_cap=units_cap, commitments=commitments, k=5
        )
        keys = [schedule_key(s.sections) for s in schedules]
        assert len(keys) == len(set(keys)), "duplicate schedule returned"


def _course_at(num, day, hour) -> Course:
    """A one-section course at a non-overlapping time, so combinations are feasible."""
    return Course(
        course_num=num,
        title=f"Course {num}",
        units=9.0,
        prereqs=None,
        description="x",
        fce_workload_hours=8.0,
        fce_rating=4.0,
        sections=[
            Section(
                course_num=num, title=f"Course {num}", units=9.0, section_id="A",
                days=[day], begin=time(hour, 0), end=time(hour, 50), location="X",
            )
        ],
    )


def test_every_returned_option_is_a_distinct_section_set():
    # Three mutually compatible courses: the DFS reaches each subset by several
    # routes (skip-vs-take orderings). Deduping at the source means the K slots
    # hold K genuinely different section sets — all 8 subsets — rather than being
    # wasted on copies of the best one.
    courses = [
        _course_at("10-101", "M", 9),
        _course_at("10-102", "T", 11),
        _course_at("10-103", "W", 14),
    ]
    profile = StudentProfile(major="CS", expected_grad="2027")
    schedules = solve(courses, profile, units_cap=100.0, k=8)

    keys = [schedule_key(s.sections) for s in schedules]
    assert len(keys) == len(set(keys))
    # 2^3 subsets of three non-conflicting courses, each a distinct option.
    assert len(keys) == 8


def test_dedup_keys_on_times_not_just_course_numbers():
    # Same course, two sections at different times = two *distinct* options, per
    # "the same set of course sections at the same times".
    course = Course(
        course_num="10-200",
        title="Two Sections",
        units=9.0,
        prereqs=None,
        description="x",
        fce_workload_hours=8.0,
        fce_rating=4.0,
        sections=[
            Section(
                course_num="10-200", title="Two Sections", units=9.0, section_id="A",
                days=["M"], begin=time(9, 0), end=time(9, 50), location="X",
            ),
            Section(
                course_num="10-200", title="Two Sections", units=9.0, section_id="B",
                days=["M"], begin=time(14, 0), end=time(14, 50), location="X",
            ),
        ],
    )
    profile = StudentProfile(major="CS", expected_grad="2027")
    schedules = solve([course], profile, units_cap=100.0, k=5)

    keys = [schedule_key(s.sections) for s in schedules]
    assert len(keys) == len(set(keys))
    # Empty + section A + section B: the two sections are not collapsed together.
    assert len(schedules) == 3


def test_non_positive_k_returns_empty():
    profile = StudentProfile(major="CS", expected_grad="2027")
    good = _fixed_course("11-785", "DL", "ml", rating=4.8, workload=8.0)
    assert solve([good], profile, units_cap=18.0, k=0) == []


def test_interest_match_neutral_without_interests():
    profile = StudentProfile(major="CS", expected_grad="2027")  # no interests
    good = _fixed_course("11-785", "DL", "machine learning", rating=4.8, workload=8.0)
    assert course_value(good, profile) == W_RATING * (4.8 / 5.0) - W_WORKLOAD * (8.0 / 20.0)


def test_returns_at_most_k():
    rng = random.Random(5)
    for k in (1, 3, 5, 8):
        for _ in range(60):
            courses, profile, commitments, cap = _rand_scenario(rng)
            result = solve(courses, profile, units_cap=cap, k=k)
            assert len(result) <= k


def test_results_sorted_by_descending_score():
    rng = random.Random(6)
    for _ in range(200):
        courses, profile, commitments, cap = _rand_scenario(rng)
        result = solve(courses, profile, units_cap=cap, k=5)
        scores = [s.score for s in result]
        assert scores == sorted(scores, reverse=True)


# --- Blocked exclusion -------------------------------------------------------


def test_blocked_courses_never_appear():
    rng = random.Random(7)
    for _ in range(300):
        courses, profile, commitments, cap = _rand_scenario(rng)
        classifications = {}
        blocked = set()
        for c in courses:
            state = rng.choice(["eligible", "unconfirmed", "blocked"])
            classifications[c.course_num] = state
            if state == "blocked":
                blocked.add(c.course_num)
        for sched in solve(
            courses, profile, units_cap=cap, classifications=classifications, k=5
        ):
            assert blocked.isdisjoint(sched.course_nums), "blocked course scheduled"


# --- Ranking correctness -----------------------------------------------------


def _fixed_course(num, title, desc, rating, workload) -> Course:
    return Course(
        course_num=num,
        title=title,
        units=9.0,
        prereqs=None,
        description=desc,
        fce_workload_hours=workload,
        fce_rating=rating,
        sections=[
            Section(
                course_num=num,
                title=title,
                units=9.0,
                section_id="A",
                days=["M", "W"],
                begin=time(9, 0),
                end=time(9, 50),
                location="X",
            )
        ],
    )


def test_better_course_outranks_worse():
    profile = StudentProfile(
        major="CS", expected_grad="2027", interests=["machine learning"]
    )
    good = _fixed_course(
        "11-785", "Deep Learning", "A course on machine learning.", rating=4.8, workload=8.0
    )
    bad = _fixed_course(
        "99-100", "Tedium", "An unrelated slog.", rating=2.6, workload=19.0
    )
    # The per-course signal agrees: good is worth more than bad.
    assert course_value(good, profile) > course_value(bad, profile)
    # And a schedule built on good outranks one built on bad.
    assert schedule_score([good], profile) > schedule_score([bad], profile)


def test_top_schedule_includes_the_strong_course():
    # Two non-conflicting courses; the strong one must be in the best schedule.
    profile = StudentProfile(
        major="CS", expected_grad="2027", interests=["machine learning"]
    )
    good = _fixed_course(
        "11-785", "Deep Learning", "A course on machine learning.", rating=4.8, workload=8.0
    )
    # Give them different meeting times so both can co-exist.
    bad = _fixed_course(
        "99-100", "Tedium", "An unrelated slog.", rating=2.6, workload=19.0
    )
    bad.sections[0].begin = time(13, 0)
    bad.sections[0].end = time(13, 50)

    result = solve([good, bad], profile, units_cap=18.0, k=5)
    assert result, "expected at least one schedule"
    assert "11-785" in result[0].course_nums
