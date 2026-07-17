"""Integration tests for the deterministic API endpoints (no LLM).

Hits /survey, /recommend, and /confirm against the sample catalog; asserts the
response shapes and the cascade: confirming a prerequisite flips a dependent
course from unconfirmed to eligible and drops its confirmation question.
"""

import json

import httpx
from app.main import DEFAULT_UNITS_CAP, app
from fastapi.testclient import TestClient

client = TestClient(app)


def _cs_profile(**overrides) -> dict:
    profile = {
        "major": "Computer Science",
        "expected_grad": "2027",
        "completed_courses": [],
        "commitments": [],
        "interests": [],
        "career_goals": [],
    }
    profile.update(overrides)
    return profile


# --- /survey -----------------------------------------------------------------


def test_survey_returns_grouped_checklist():
    resp = client.post("/survey", json=_cs_profile())
    assert resp.status_code == 200
    body = resp.json()
    assert body["major"] == "Computer Science"

    groups = body["checklist"]
    assert isinstance(groups, list) and groups
    headers = {g["header"] for g in groups}
    assert "Common prerequisites" in headers  # prereq section present

    nums = {c["course_num"] for g in groups for c in g["courses"]}
    # (a) core courses (from all-rule groups) appear...
    assert "15-122" in nums  # cs_core
    assert "15-213" in nums  # cs_core (now included; was excluded by old foundation)
    assert "21-120" in nums  # math_core
    # (b) a known prerequisite appears...
    assert "15-112" in nums  # prereq of 15-122
    # ...but a course that is neither core nor a prerequisite does not.
    assert "76-101" not in nums
    # Each course appears exactly once across all groups.
    all_nums = [c["course_num"] for g in groups for c in g["courses"]]
    assert len(all_nums) == len(set(all_nums))
    # Focused list, not the whole catalog/requirements dump.
    assert len(all_nums) <= 20


# --- /recommend --------------------------------------------------------------


def test_recommend_shape():
    resp = client.post("/recommend", json=_cs_profile())
    assert resp.status_code == 200
    body = resp.json()

    assert isinstance(body["schedules"], list)
    assert 1 <= len(body["schedules"]) <= 5
    for sched in body["schedules"]:
        assert sched["total_units"] <= DEFAULT_UNITS_CAP
        assert set(sched["classifications"].values()) <= {"eligible", "unconfirmed"}
        # Every scheduled course has a classification entry.
        for section in sched["sections"]:
            assert section["course_num"] in sched["classifications"]

    for q in body["confirmation_questions"]:
        assert q["course_num"]
        assert isinstance(q["missing_prereqs"], list)
        assert q["question"]


def test_recommend_confirmation_questions_target_unconfirmed_courses():
    resp = client.post("/recommend", json=_cs_profile())
    body = resp.json()

    # Any course carrying a confirmation question must actually be unconfirmed in
    # at least one returned schedule.
    unconfirmed_in_schedules = {
        num
        for sched in body["schedules"]
        for num, state in sched["classifications"].items()
        if state == "unconfirmed"
    }
    for q in body["confirmation_questions"]:
        assert q["course_num"] in unconfirmed_in_schedules


# --- /confirm : the cascade --------------------------------------------------


def _schedule_state_for(body: dict, course_num: str):
    """Return the classification of course_num if it appears in any schedule."""
    for sched in body["schedules"]:
        if course_num in sched["classifications"]:
            return sched["classifications"][course_num]
    return None


def test_confirm_cascade_unlocks_dependent():
    # Interest keyword pins 15-122 into the top schedule so the cascade is
    # deterministic: 15-122 needs 15-112, which we then confirm.
    profile = _cs_profile(interests=["Imperative Computation"])

    before = client.post("/recommend", json=profile).json()
    assert _schedule_state_for(before, "15-122") == "unconfirmed"
    q_courses_before = {q["course_num"] for q in before["confirmation_questions"]}
    assert "15-122" in q_courses_before
    q_122 = next(q for q in before["confirmation_questions"] if q["course_num"] == "15-122")
    assert "15-112" in q_122["missing_prereqs"]

    # Student confirms they've taken 15-112.
    confirm_resp = client.post(
        "/confirm", json={"profile": profile, "answers": {"15-112": True}}
    )
    assert confirm_resp.status_code == 200
    after = confirm_resp.json()

    # 15-122's prereq is now satisfied: eligible, and no longer questioned.
    assert _schedule_state_for(after, "15-122") == "eligible"
    q_courses_after = {q["course_num"] for q in after["confirmation_questions"]}
    assert "15-122" not in q_courses_after


def _scheduled_course_nums(body: dict) -> set[str]:
    """Every course that actually appears on a returned schedule's calendar."""
    return {
        section["course_num"]
        for sched in body["schedules"]
        for section in sched["sections"]
    }


def test_confirm_answer_updates_returned_schedule():
    # The interactive confirmation panel answers one prereq at a time and re-solves
    # via /confirm; the calendar must change in place. Here, answering "no" to a
    # prereq rules out its dependent, so that course leaves every returned schedule.
    profile = _cs_profile(interests=["Imperative Computation"])

    before = client.post("/recommend", json=profile).json()
    # 15-122 is scheduled (as unconfirmed) before any answer, and it appears on a
    # calendar, so removing it is an observable change to the returned schedule.
    assert "15-122" in _scheduled_course_nums(before)
    assert _schedule_state_for(before, "15-122") == "unconfirmed"

    # Student answers "No" to 15-112 (a control on the panel). 15-122's only prereq
    # is now ruled out -> blocked -> it drops off the schedule entirely.
    after = client.post(
        "/confirm", json={"profile": profile, "answers": {"15-112": False}}
    ).json()

    assert "15-122" not in _scheduled_course_nums(after)
    # The returned schedule genuinely changed as a result of the answer.
    assert _scheduled_course_nums(after) != _scheduled_course_nums(before)


def test_completed_course_excluded_but_still_satisfies_prereqs():
    # Two roles of completed_courses: (2) a completed course must never be
    # recommended back, and (1) it must still satisfy prereqs for other courses.
    # 15-112 is completed; the interest keyword pins its dependent 15-122 in.
    profile = _cs_profile(
        completed_courses=["15-112"], interests=["Imperative Computation"]
    )
    body = client.post("/recommend", json=profile).json()

    # Role 2: 15-112 never appears in any returned schedule.
    for sched in body["schedules"]:
        assert "15-112" not in {s["course_num"] for s in sched["sections"]}
        assert "15-112" not in sched["classifications"]

    # Role 1: 15-112 still satisfies 15-122's prereq, so 15-122 is now eligible.
    assert _schedule_state_for(body, "15-122") == "eligible"


def test_recommend_surfaces_requirements_and_disclaimer():
    resp = client.post("/recommend", json=_cs_profile())
    assert resp.status_code == 200
    body = resp.json()
    # Disclaimer is surfaced so the UI can mark this as not an official audit.
    assert body["disclaimer"]
    assert "audit" in body["disclaimer"].lower()
    # Each schedule reports which requirement groups its courses advance.
    for sched in body["schedules"]:
        assert isinstance(sched["requirements_advanced"], list)
        for grp in sched["requirements_advanced"]:
            assert grp["id"] and grp["name"]


def test_completed_requirement_course_never_recommended():
    # Regression (earlier bug): a completed course must never appear in a schedule,
    # even though it still counts toward requirements. 15-122 is a cs_core course.
    profile = _cs_profile(completed_courses=["15-122"])
    body = client.post("/recommend", json=profile).json()
    for sched in body["schedules"]:
        assert "15-122" not in {s["course_num"] for s in sched["sections"]}
    # cs_core should no longer be advanced *by 15-122* (it's already done), but the
    # response is still well-formed with the disclaimer present.
    assert body["disclaimer"]


def test_completed_course_excluded_from_ask_schedules(monkeypatch):
    # The same exclusion holds on the /ask path (shared _solve_for).
    monkeypatch.delenv("LLM_PROVIDER", raising=False)  # default provider = offline stub
    profile = _cs_profile(completed_courses=["15-112"], interests=["machine learning"])
    body = client.post(
        "/ask", json={"profile": profile, "question": "What's the best fit for me?"}
    ).json()
    for result in body["results"]:
        assert "15-112" not in {s["course_num"] for s in result["sections"]}


def test_confirm_no_answer_ruled_out_does_not_crash_and_excludes_blocked():
    # Answering "no" to a prereq rules it out; a course whose only prereq is ruled
    # out becomes blocked and must not appear in any schedule.
    profile = _cs_profile(interests=["Imperative Computation"])
    resp = client.post(
        "/confirm", json={"profile": profile, "answers": {"15-112": False}}
    )
    assert resp.status_code == 200
    after = resp.json()
    # 15-122 requires 15-112 (now ruled out) -> blocked -> excluded everywhere.
    assert _schedule_state_for(after, "15-122") is None


# --- /ask : LLM orchestrator (stub, no key) ----------------------------------


def test_ask_semantic_uses_stub_and_all_claims_verify(monkeypatch):
    # No API key -> deterministic stub backend; every returned claim must verify.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)  # default provider = offline stub
    resp = client.post(
        "/ask",
        json={
            "profile": _cs_profile(interests=["machine learning"]),
            "question": "Which of these schedules best fits my interests?",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["route"] == "semantic"
    assert body["llm_backend"] == "stub"
    assert body["results"]

    for result in body["results"]:
        assert result["explanation"]  # prose present on the semantic route
        assert result["stripped_claim_count"] == 0  # stub is truthful
        # Every returned claim is a real, schema-valid claim about the schedule.
        for claim in result["verified_claims"]:
            assert claim["type"] in {
                "no_class_on", "total_units", "includes_course", "no_conflicts"
            }
        units_claims = [c for c in result["verified_claims"] if c["type"] == "total_units"]
        assert units_claims and units_claims[0]["value"] == result["total_units"]


def test_ask_uses_the_provider_named_by_env_and_still_verifies(monkeypatch):
    # Provider choice is runtime config: with LLM_PROVIDER=groq the same /ask path
    # routes through Groq (HTTP mocked — no real key) and reports it. The verifier
    # gate is unchanged: the false claim this "model" emits is still stripped.
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    content = json.dumps(
        {
            "explanation": "A fine schedule.",
            "fit_rank": 1,
            "claims": [{"type": "total_units", "value": 999.0}],  # FALSE
            "confirmation_questions": [],
        }
    )
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
            request=httpx.Request("POST", "https://example.invalid"),
        ),
    )

    body = client.post(
        "/ask",
        json={
            "profile": _cs_profile(interests=["machine learning"]),
            "question": "Which schedule best fits my interests?",
        },
    ).json()

    assert body["route"] == "semantic"
    assert body["llm_backend"] == "groq"  # the selected provider answered
    for result in body["results"]:
        # The bogus unit total never reaches the student, exactly as with the stub.
        assert result["verified_claims"] == []
        assert result["stripped_claim_count"] == 1


def test_ask_structured_route_returns_facts_without_prose(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)  # default provider = offline stub
    resp = client.post(
        "/ask",
        json={
            "profile": _cs_profile(),
            "question": "How many units is each schedule and are there any conflicts?",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["route"] == "structured"
    assert body["llm_backend"] == "none"
    for result in body["results"]:
        assert result["explanation"] is None  # no LLM prose on the structured route
        assert result["verified_claims"] == []
        assert result["total_units"] <= DEFAULT_UNITS_CAP
