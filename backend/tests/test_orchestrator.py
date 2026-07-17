"""Tests for the chat orchestrator, its verifier gate, and the chat->solver translation.

Correctness-critical. Two guarantees are load-bearing here:

1. **The gate holds, for every provider.** An unverified factual claim about a
   schedule must never reach output, no matter which provider produced it.
2. **The model can only propose.** A chat "modification" is translated into the
   solver's ordinary inputs (units cap, commitment blocks, exclusions) — there is
   no path by which a model edits a calendar directly.

Runs entirely on the deterministic stub plus mocked providers.
"""

import json
from datetime import time

import httpx
from app.llm_provider import GroqProvider, StubProvider
from app.models import Schedule, Section, StudentProfile, TimeBlock
from app.orchestrator import (
    ALL_DAYS,
    ChatMessage,
    ScheduleConstraints,
    ScheduleContext,
    _facts_block,
    build_chat_messages,
    build_confirmation_questions,
    constraints_to_solver_inputs,
    orchestrate_chat_turn,
)
from app.verifier import (
    IncludesCourseClaim,
    NoClassOnClaim,
    TotalUnitsClaim,
    verify,
)


def _section(course_num, days, begin, end, units) -> Section:
    return Section(
        course_num=course_num,
        title=f"Course {course_num}",
        units=units,
        section_id="A",
        days=days,
        begin=time(*begin),
        end=time(*end),
        location="X",
    )


def _context() -> ScheduleContext:
    schedule = Schedule(
        sections=[
            _section("15-122", ["T", "R"], (9, 30), (10, 50), 10.0),
            _section("15-213", ["M", "W"], (14, 0), (15, 20), 12.0),
        ],
        total_units=22.0,
        total_workload_hours=31.0,
        score=1.5,
    )
    return ScheduleContext(
        schedule=schedule,
        classifications={"15-122": "unconfirmed", "15-213": "eligible"},
        confirmation_targets={"15-122": ["15-112"]},
    )


def _profile() -> StudentProfile:
    return StudentProfile(major="CS", expected_grad="2027", interests=["systems"])


# --- Deterministic helpers ---------------------------------------------------


def test_facts_block_lists_only_given_facts():
    facts = _facts_block(_context())
    assert "total_units: 22" in facts
    assert "15-122" in facts and "15-213" in facts
    assert "free_days: F" in facts
    assert "unconfirmed 15-122: needs 15-112" in facts


def test_confirmation_question_handles_no_missing_prereqs():
    # An unconfirmed course with an empty missing list still yields a question.
    ctx = _context()
    ctx.confirmation_targets["15-122"] = []
    (q,) = build_confirmation_questions(ctx)
    assert q.course_num == "15-122"
    assert q.missing_prereqs == []
    assert "prerequisites" in q.question.lower()


def test_chat_prompt_carries_conversation_and_active_constraints():
    # Follow-ups can only build on prior turns if the prompt actually says what
    # was already asked and what is already in effect.
    history = [
        ChatMessage(role="user", content="swap the Friday class"),
        ChatMessage(role="assistant", content="Done."),
    ]
    messages = build_chat_messages(
        _context(),
        _profile(),
        message="now make it lighter",
        history=history,
        constraints=ScheduleConstraints(avoid_days=["F"]),
    )
    user = next(m.content for m in messages if m.role == "user")
    assert "swap the Friday class" in user  # prior turn present
    assert "no class on F" in user  # active constraints echoed
    assert "now make it lighter" in user  # this turn


# --- chat -> solver translation ----------------------------------------------


def test_constraints_translate_to_solver_inputs():
    constraints = ScheduleConstraints(
        avoid_days=["F"],
        max_units=36.0,
        no_class_before=time(10, 0),
        no_class_after=time(16, 0),
        exclude_courses=["76-101"],
    )
    cap, blocks, excluded = constraints_to_solver_inputs(
        constraints, base_commitments=[], default_units_cap=54.0
    )

    assert cap == 36.0
    assert excluded == {"76-101"}
    # Friday is blocked for the whole day.
    friday = next(b for b in blocks if b.days == ["F"])
    assert friday.begin == time(0, 0) and friday.end == time(23, 59)
    # Early/late windows are blocked across every weekday.
    early = next(b for b in blocks if b.label == "no early classes")
    assert early.days == ALL_DAYS and early.end == time(10, 0)
    late = next(b for b in blocks if b.label == "no late classes")
    assert late.days == ALL_DAYS and late.begin == time(16, 0)


def test_empty_constraints_preserve_prior_solver_behavior():
    # No constraints must mean exactly the old inputs — the chat is additive.
    base = [TimeBlock(label="job", days=["M"], begin=time(9, 0), end=time(11, 0))]
    cap, blocks, excluded = constraints_to_solver_inputs(
        ScheduleConstraints(), base_commitments=base, default_units_cap=54.0
    )
    assert cap == 54.0
    assert blocks == base
    assert excluded == set()


def test_constraints_can_never_raise_the_units_cap():
    # A student may ask for a lighter load, never for an overload past the ceiling.
    cap, _, _ = constraints_to_solver_inputs(
        ScheduleConstraints(max_units=999.0), base_commitments=[], default_units_cap=54.0
    )
    assert cap == 54.0


def test_base_commitments_are_never_dropped():
    # A chat constraint must not be able to schedule over the student's real life.
    base = [TimeBlock(label="job", days=["W"], begin=time(9, 0), end=time(11, 0))]
    _, blocks, _ = constraints_to_solver_inputs(
        ScheduleConstraints(avoid_days=["F"]), base_commitments=base, default_units_cap=54.0
    )
    assert base[0] in blocks


def test_constraints_describe_is_human_readable():
    assert ScheduleConstraints().describe() == "no constraints"
    described = ScheduleConstraints(avoid_days=["F"], max_units=36.0).describe()
    assert "no class on F" in described and "36 units" in described


# --- Stub: question turns are grounded and verified ---------------------------


def test_stub_question_turn_claims_all_pass_verification():
    ctx = _context()
    turn = orchestrate_chat_turn(
        StubProvider(),
        _profile(),
        message="what's my workload?",
        history=[],
        constraints=ScheduleConstraints(),
        ctx=ctx,
    )

    assert turn.kind == "question"
    assert turn.backend == "stub"
    assert turn.reply
    assert turn.stripped_claims == []  # the stub is truthful
    assert turn.verified_claims

    # Independently re-verify every returned claim against the schedule.
    assert verify(turn.verified_claims, ctx.schedule).all_passed

    units = next(c for c in turn.verified_claims if isinstance(c, TotalUnitsClaim))
    assert units.value == 22.0
    included = {
        c.course_num for c in turn.verified_claims if isinstance(c, IncludesCourseClaim)
    }
    assert {"15-122", "15-213"} <= included
    # Friday is genuinely free on this schedule.
    assert any(isinstance(c, NoClassOnClaim) and c.day == "F" for c in turn.verified_claims)


def test_stub_question_turn_leaves_constraints_untouched():
    # A question must not silently re-solve the calendar.
    active = ScheduleConstraints(avoid_days=["F"])
    turn = orchestrate_chat_turn(
        StubProvider(),
        _profile(),
        message="what's my workload?",
        history=[],
        constraints=active,
        ctx=_context(),
    )
    assert turn.kind == "question"
    assert turn.constraints.avoid_days == ["F"]


def test_stub_modification_turn_accumulates_onto_prior_constraints():
    # "now make it lighter" must not forget the earlier "no Fridays".
    turn = orchestrate_chat_turn(
        StubProvider(),
        _profile(),
        message="now make it lighter",
        history=[ChatMessage(role="user", content="swap the Friday class")],
        constraints=ScheduleConstraints(avoid_days=["F"]),
        ctx=_context(),
    )
    assert turn.kind == "modification"
    assert turn.constraints.avoid_days == ["F"]  # retained
    assert turn.constraints.max_units == 13.0  # 22 units on screen, one course lighter
    # A modification asserts nothing about the old schedule.
    assert turn.verified_claims == []


def test_stub_modification_turn_maps_morning_to_a_time_window():
    turn = orchestrate_chat_turn(
        StubProvider(),
        _profile(),
        message="prioritize morning classes",
        history=[],
        constraints=ScheduleConstraints(),
        ctx=_context(),
    )
    assert turn.kind == "modification"
    assert turn.constraints.no_class_after == time(12, 0)


# --- The gate is provider-independent ----------------------------------------


class _LyingLLM:
    """A provider that fabricates false claims (wrong unit total + a false day-off)."""

    name = "mock"

    def generate(self, messages, response_schema):
        return response_schema(
            kind="question",
            reply="This schedule is 99 units and you have Tuesdays off.",
            constraints=ScheduleConstraints(),
            claims=[
                TotalUnitsClaim(value=99.0),  # FALSE: actual total is 22
                NoClassOnClaim(day="T"),  # FALSE: 15-122 meets on Tuesday
                IncludesCourseClaim(course_num="15-122"),  # true
            ],
        )


def _lying_groq_provider(monkeypatch):
    """A real GroqProvider whose HTTP call is mocked to return the same lie."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    body = json.dumps(
        {
            "kind": "question",
            "reply": "This schedule is 99 units and you have Tuesdays off.",
            "constraints": {},
            "claims": [
                {"type": "total_units", "value": 99.0},  # FALSE
                {"type": "no_class_on", "day": "T"},  # FALSE
                {"type": "includes_course", "course_num": "15-122"},  # true
            ],
        }
    )
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200,
            json={"choices": [{"message": {"content": body}}]},
            request=httpx.Request("POST", "https://example.invalid"),
        ),
    )
    return GroqProvider()


def test_wrong_claim_is_stripped_for_every_provider(monkeypatch):
    # Same false claims, two different providers (a plain mock and a real
    # GroqProvider over mocked HTTP). The verifier gate sits downstream of the
    # provider abstraction, so the outcome must be identical for both.
    providers = [_LyingLLM(), _lying_groq_provider(monkeypatch)]

    for provider in providers:
        ctx = _context()
        turn = orchestrate_chat_turn(
            provider,
            _profile(),
            message="tell me about my schedule",
            history=[],
            constraints=ScheduleConstraints(),
            ctx=ctx,
        )

        # Both false claims caught, regardless of who produced them.
        assert {type(c.claim).__name__ for c in turn.stripped_claims} == {
            "TotalUnitsClaim",
            "NoClassOnClaim",
        }, f"provider {provider.name} leaked a false claim"
        # Only the true claim survives, and it genuinely verifies.
        assert [type(c).__name__ for c in turn.verified_claims] == ["IncludesCourseClaim"]
        assert verify(turn.verified_claims, ctx.schedule).all_passed


def test_claims_are_not_verified_against_a_missing_schedule():
    # With no schedule on screen there is nothing to check a claim against, so no
    # claim may be presented as verified.
    turn = orchestrate_chat_turn(
        _LyingLLM(),
        _profile(),
        message="anything?",
        history=[],
        constraints=ScheduleConstraints(),
        ctx=None,
    )
    assert turn.verified_claims == []
