"""Integration tests for the deterministic API endpoints (no LLM).

Hits /survey, /recommend, and /confirm against the sample catalog; asserts the
response shapes and the cascade: confirming a prerequisite flips a dependent
course from unconfirmed to eligible and drops its confirmation question.
"""

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


def test_survey_returns_foundation_courses():
    resp = client.post("/survey", json=_cs_profile())
    assert resp.status_code == 200
    body = resp.json()
    assert body["major"] == "Computer Science"

    nums = {c["course_num"] for c in body["foundation_courses"]}
    # Gateways (no prereqs) and building blocks (prereqs of others) in 15-/21-.
    assert "15-112" in nums  # gateway, no prereqs
    assert "15-122" in nums  # prereq of 15-150 / 15-213
    assert "21-127" in nums  # prereq of 15-150
    # 76-101 is outside the CS department prefixes -> excluded.
    assert "76-101" not in nums
    # Upper-division courses that nothing depends on are not "foundation".
    assert "15-213" not in nums


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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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


def test_ask_structured_route_returns_facts_without_prose(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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
