"""Tests for the LLM orchestrator and its verifier gate.

Correctness-critical: the orchestrator is the only place the LLM touches the
pipeline, and it must never let an unverified factual claim about a schedule
reach output. Runs entirely on the deterministic stub (no API key) plus mocked
providers that emit deliberately wrong claims.

The gate is provider-independent: see ``test_wrong_claim_is_stripped_for_every_provider``
for the same false claim being caught no matter which provider produced it.
"""

import json
from datetime import time

import httpx
from app.llm_provider import GroqProvider, StubProvider
from app.models import Schedule, Section, StudentProfile
from app.orchestrator import (
    ScheduleContext,
    _facts_block,
    build_confirmation_questions,
    build_messages,
    orchestrate,
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


def test_build_messages_names_prior_failures_on_regeneration():
    # The regeneration prompt must tell the provider what the verifier rejected.
    ctx = _context()
    result = verify([TotalUnitsClaim(value=99.0)], ctx.schedule)
    messages = build_messages(
        ctx, _profile(), fit_rank=1, prior_failures=result.failed_checks
    )
    user = next(m.content for m in messages if m.role == "user")
    assert "failed verification" in user
    assert "22" in user  # the corrected, true unit total is named


def test_confirmation_question_handles_no_missing_prereqs():
    # An unconfirmed course with an empty missing list still yields a question.
    ctx = _context()
    ctx.confirmation_targets["15-122"] = []
    (q,) = build_confirmation_questions(ctx)
    assert q.course_num == "15-122"
    assert q.missing_prereqs == []
    assert "prerequisites" in q.question.lower()


# --- Stub: valid shape, all claims verify ------------------------------------


def test_stub_output_all_claims_pass_verification():
    ctx = _context()
    result = orchestrate([ctx], _profile(), provider=StubProvider())

    assert result.backend == "stub"
    (exp,) = result.explanations
    assert exp.explanation  # non-empty prose
    assert exp.fit_rank == 1
    assert exp.stripped_claims == []  # nothing stripped — stub is truthful
    assert exp.verified_claims  # some claims survived

    # Independently re-verify every returned claim against the schedule.
    recheck = verify(exp.verified_claims, exp.schedule)
    assert recheck.all_passed

    # The unconfirmed course carries a confirmation question naming its gap.
    q = next(q for q in exp.confirmation_questions if q.course_num == "15-122")
    assert "15-112" in q.missing_prereqs


def test_stub_claims_reflect_the_schedule():
    ctx = _context()
    (exp,) = orchestrate([ctx], _profile(), provider=StubProvider()).explanations
    units = next(c for c in exp.verified_claims if isinstance(c, TotalUnitsClaim))
    assert units.value == 22.0
    included = {c.course_num for c in exp.verified_claims if isinstance(c, IncludesCourseClaim)}
    assert {"15-122", "15-213"} <= included
    # Friday is free on this schedule -> a valid no_class_on claim.
    assert any(
        isinstance(c, NoClassOnClaim) and c.day == "F" for c in exp.verified_claims
    )


# --- Mocked LLM emitting a WRONG claim: verifier must catch it ----------------


class _LyingLLM:
    """A provider that fabricates false claims (wrong unit total + a false day-off)."""

    name = "mock"

    def generate(self, messages, response_schema):
        return response_schema(
            explanation="This schedule is 99 units and you have Tuesdays off.",
            fit_rank=1,
            claims=[
                TotalUnitsClaim(value=99.0),  # FALSE: actual total is 22
                NoClassOnClaim(day="T"),  # FALSE: 15-122 meets on Tuesday
                IncludesCourseClaim(course_num="15-122"),  # true
            ],
            confirmation_questions=[],
        )


def test_wrong_llm_claim_is_stripped_and_never_returned():
    ctx = _context()
    result = orchestrate([ctx], _profile(), provider=_LyingLLM(), regenerate_attempts=0)

    (exp,) = result.explanations

    # The two false claims were caught and removed.
    assert len(exp.stripped_claims) == 2
    stripped_types = {type(c.claim).__name__ for c in exp.stripped_claims}
    assert stripped_types == {"TotalUnitsClaim", "NoClassOnClaim"}

    # No false claim survived into the returned, verified set.
    assert all(not isinstance(c, TotalUnitsClaim) for c in exp.verified_claims)
    assert all(not isinstance(c, NoClassOnClaim) for c in exp.verified_claims)
    # The one true claim did survive.
    assert any(
        isinstance(c, IncludesCourseClaim) and c.course_num == "15-122"
        for c in exp.verified_claims
    )

    # And everything that DID survive genuinely passes verification.
    assert verify(exp.verified_claims, exp.schedule).all_passed


# --- The gate is provider-independent ----------------------------------------


def _lying_groq_provider(monkeypatch):
    """A real GroqProvider whose HTTP call is mocked to return the same lie."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    body = json.dumps(
        {
            "explanation": "This schedule is 99 units and you have Tuesdays off.",
            "fit_rank": 1,
            "claims": [
                {"type": "total_units", "value": 99.0},  # FALSE
                {"type": "no_class_on", "day": "T"},  # FALSE
                {"type": "includes_course", "course_num": "15-122"},  # true
            ],
            "confirmation_questions": [],
        }
    )
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200,
            json={"choices": [{"message": {"content": body}}]},
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
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
        (exp,) = orchestrate([ctx], _profile(), provider=provider).explanations

        # Both false claims caught, regardless of who produced them.
        assert {type(c.claim).__name__ for c in exp.stripped_claims} == {
            "TotalUnitsClaim",
            "NoClassOnClaim",
        }, f"provider {provider.name} leaked a false claim"
        # Only the true claim survives, and it genuinely verifies.
        assert [type(c).__name__ for c in exp.verified_claims] == ["IncludesCourseClaim"]
        assert verify(exp.verified_claims, exp.schedule).all_passed


def test_regeneration_recovers_when_backend_corrects_itself():
    ctx = _context()

    class _SelfCorrectingLLM:
        name = "mock2"

        def __init__(self):
            self.calls = 0

        def generate(self, messages, response_schema):
            self.calls += 1
            if self.calls == 1:
                claims = [TotalUnitsClaim(value=99.0)]  # wrong first
            else:
                claims = [TotalUnitsClaim(value=22.0)]  # corrected on retry
            return response_schema(
                explanation="", fit_rank=1, claims=claims, confirmation_questions=[]
            )

    provider = _SelfCorrectingLLM()
    (exp,) = orchestrate(
        [ctx], _profile(), provider=provider, regenerate_attempts=1
    ).explanations

    assert provider.calls == 2  # regenerated once
    assert exp.stripped_claims == []
    assert any(
        isinstance(c, TotalUnitsClaim) and c.value == 22.0 for c in exp.verified_claims
    )
