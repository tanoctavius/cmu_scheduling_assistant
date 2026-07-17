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


# --- /chat : question vs modification, both deterministic underneath ----------


def _chat(message: str, **kwargs) -> dict:
    payload = {"profile": _cs_profile(interests=["machine learning"]), "message": message}
    payload.update(kwargs)
    resp = client.post("/chat", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _courses_of(body: dict, index: int = 0) -> list[str]:
    return [s["course_num"] for s in body["schedules"][index]["sections"]]


def _days_used(body: dict, index: int = 0) -> set[str]:
    return {d for s in body["schedules"][index]["sections"] for d in s["days"]}


def test_chat_question_returns_verified_info_without_changing_the_schedule(monkeypatch):
    # A question is answered from the verified schedule data and must leave the
    # calendar exactly as it was — no silent re-solve.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)  # default provider = offline stub
    before = client.post("/recommend", json=_cs_profile(interests=["machine learning"])).json()

    body = _chat("what's my workload?")

    assert body["kind"] == "question"
    assert body["llm_backend"] == "stub"
    assert body["reply"]
    # The schedule is untouched.
    assert _courses_of(body) == [s["course_num"] for s in before["schedules"][0]["sections"]]
    assert body["constraints_relaxed"] is False

    # The answer is grounded: every claim shown passed the verifier, and the unit
    # figure it quotes is the schedule's real one.
    assert body["stripped_claim_count"] == 0
    assert body["verified_claims"]
    units = [c for c in body["verified_claims"] if c["type"] == "total_units"]
    assert units and units[0]["value"] == body["schedules"][0]["total_units"]


def test_chat_modification_produces_a_different_verified_conflict_free_schedule(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    before = _chat("what's my workload?")
    assert "F" in _days_used(before)  # a Friday class exists to swap away

    after = _chat("swap the Friday class")

    assert after["kind"] == "modification"
    # Genuinely different, and the request was actually honoured.
    assert _courses_of(after) != _courses_of(before)
    assert "F" not in _days_used(after)
    assert after["constraints"]["avoid_days"] == ["F"]
    assert after["constraints_relaxed"] is False

    # Still a real, solver-built schedule: conflict-free, capped, verified.
    for sched in after["schedules"]:
        assert sched["total_units"] <= DEFAULT_UNITS_CAP
        assert sched["rationale"]["stripped_claim_count"] == 0
        assert any(c["type"] == "no_conflicts" for c in sched["rationale"]["verified_claims"])
        # Independently confirm no two sections overlap on a shared day.
        intervals = [
            (d, s["begin"], s["end"]) for s in sched["sections"] for d in s["days"]
        ]
        for i, (d1, b1, e1) in enumerate(intervals):
            for d2, b2, e2 in intervals[i + 1 :]:
                assert not (d1 == d2 and b1 < e2 and b2 < e1), "overlap in chat result"


def test_chat_retains_context_across_turns(monkeypatch):
    # "now make it lighter" must build on the earlier "no Fridays", not reset it.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    first = _chat("swap the Friday class")
    assert first["constraints"]["avoid_days"] == ["F"]

    second = _chat(
        "now make it lighter",
        history=first["history"],
        constraints=first["constraints"],
    )

    # Both constraints now hold together.
    assert second["constraints"]["avoid_days"] == ["F"]  # retained from turn 1
    assert second["constraints"]["max_units"] is not None  # added by turn 2
    assert "F" not in _days_used(second)
    assert second["schedules"][0]["total_units"] < first["schedules"][0]["total_units"]

    # The transcript grows by both sides of each turn.
    assert len(first["history"]) == 2
    assert len(second["history"]) == 4
    assert second["history"][0]["content"] == "swap the Friday class"


def test_chat_surfaces_confirmation_questions_for_unconfirmed_prereqs(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    body = _chat("what's my workload?", profile=_cs_profile(interests=["Imperative Computation"]))
    # 15-122 rides along as unconfirmed, so its prereq gap becomes a panel control.
    q = next(q for q in body["confirmation_questions"] if q["course_num"] == "15-122")
    assert "15-112" in q["missing_prereqs"]


def test_chat_completed_course_never_recommended(monkeypatch):
    # The two roles of completed_courses still hold on the chat path (shared _solve_for).
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    body = _chat(
        "what's my workload?",
        profile=_cs_profile(completed_courses=["15-112"], interests=["machine learning"]),
    )
    for sched in body["schedules"]:
        assert "15-112" not in {s["course_num"] for s in sched["sections"]}


def test_chat_uses_the_provider_named_by_env_and_still_verifies(monkeypatch):
    # Provider choice is runtime config: with LLM_PROVIDER=groq the chat routes
    # through Groq (HTTP mocked — no real key). The gate is unchanged: the false
    # claim this "model" emits is still stripped before display.
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    content = json.dumps(
        {
            "kind": "question",
            "reply": "A fine schedule.",
            "constraints": {},
            "claims": [{"type": "total_units", "value": 999.0}],  # FALSE
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

    body = _chat("which schedule best fits my interests?")
    assert body["llm_backend"] == "groq"  # the selected provider answered
    assert body["verified_claims"] == []  # the bogus unit total never reaches the student
    assert body["stripped_claim_count"] == 1


def test_chat_keeps_the_calendar_when_a_request_is_unsatisfiable(monkeypatch):
    # Asking for the impossible must not hand back an empty week.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    body = _chat("drop every class on monday tuesday wednesday thursday friday")
    assert body["constraints_relaxed"] is True
    assert any(s["sections"] for s in body["schedules"])
    assert "kept the previous one" in body["reply"]


# --- The rationale is a verifier output, on every path ------------------------


def test_every_schedule_carries_a_verified_rationale():
    body = client.post("/recommend", json=_cs_profile()).json()
    for sched in body["schedules"]:
        rationale = sched["rationale"]
        assert rationale["summary"]
        # Derived from the schedule, so nothing should ever fail its own check.
        assert rationale["stripped_claim_count"] == 0
        for claim in rationale["verified_claims"]:
            assert claim["type"] in {
                "no_class_on", "total_units", "includes_course", "no_conflicts"
            }
        if sched["sections"]:
            units = [c for c in rationale["verified_claims"] if c["type"] == "total_units"]
            assert units and units[0]["value"] == sched["total_units"]
