"""LLM orchestrator — the explain-and-rank layer, guarded by the verifier.

This is the one place a language model touches the pipeline, and the project
context (§2) is strict about what it may do: **the LLM never originates schedule
data.** It receives schedules the deterministic solver already produced and, per
schedule, emits a natural-language explanation, a fit ranking, and a *structured*
list of factual claims plus prereq confirmation questions. Every factual claim is
then re-checked by the Stage 4 verifier before anything is returned — failed
claims are stripped (and optionally regenerated). An unverified factual claim
about a schedule never reaches output.

Backends
--------
- :class:`AnthropicLLM` calls the Anthropic API (model ``claude-opus-4-8``),
  reading the key from ``ANTHROPIC_API_KEY``. ``anthropic`` is an optional
  dependency, imported lazily.
- :class:`StubLLM` is a deterministic fallback that builds a correctly-shaped,
  all-true response from the schedule itself. It requires no API key, so the app
  and the full test suite run without secrets (project context §7).

:func:`select_backend` picks the real backend when a key (and the SDK) are
present, else the stub.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

from pydantic import BaseModel, Field

from app.models import Schedule, StudentProfile
from app.prereq import Classification
from app.verifier import (
    Claim,
    ClaimCheck,
    IncludesCourseClaim,
    NoClassOnClaim,
    NoConflictsClaim,
    TotalUnitsClaim,
    verify,
)

_DAY_ORDER = ["M", "T", "W", "R", "F"]
_MODEL = "claude-opus-4-8"


# --- Shared confirmation-question type --------------------------------------


class ConfirmationQuestion(BaseModel):
    """A prereq question attached to an unconfirmed course (project context §3)."""

    course_num: str
    title: str = ""
    missing_prereqs: list[str] = Field(default_factory=list)
    question: str


def _question_text(course_num: str, title: str, missing: list[str]) -> str:
    if not missing:
        return f"Have you met the prerequisites for {course_num} {title}?"
    joined = " and ".join(missing)
    pronoun = "it" if len(missing) == 1 else "them"
    label = f"{title} ({course_num})" if title else course_num
    return (
        f"{label} looks like a strong fit — it requires {joined}. "
        f"Have you taken {pronoun}?"
    )


# --- Inputs / outputs --------------------------------------------------------


class ScheduleContext(BaseModel):
    """Everything the LLM is *given* about one schedule — it invents nothing."""

    schedule: Schedule
    classifications: dict[str, Classification] = Field(default_factory=dict)
    # course_num -> still-missing prereqs, for the unconfirmed courses on this schedule.
    confirmation_targets: dict[str, list[str]] = Field(default_factory=dict)


class ScheduleExplanation(BaseModel):
    """The raw, *unverified* LLM output for one schedule (also the parse schema)."""

    explanation: str
    fit_rank: int
    claims: list[Claim] = Field(default_factory=list)
    confirmation_questions: list[ConfirmationQuestion] = Field(default_factory=list)


class VerifiedExplanation(BaseModel):
    """An explanation after the verifier gate: only passed claims survive."""

    schedule: Schedule
    classifications: dict[str, Classification] = Field(default_factory=dict)
    fit_rank: int
    explanation: str
    verified_claims: list[Claim] = Field(default_factory=list)
    stripped_claims: list[ClaimCheck] = Field(default_factory=list)
    confirmation_questions: list[ConfirmationQuestion] = Field(default_factory=list)


class OrchestrationResult(BaseModel):
    backend: str
    explanations: list[VerifiedExplanation] = Field(default_factory=list)


# --- Helpers over a schedule -------------------------------------------------


def _free_days(schedule: Schedule) -> list[str]:
    busy: set[str] = set()
    for section in schedule.sections:
        busy.update(section.days)
    return [d for d in _DAY_ORDER if d not in busy]


def build_confirmation_questions(ctx: ScheduleContext) -> list[ConfirmationQuestion]:
    """Deterministic confirmation questions for a context's unconfirmed courses."""
    titles = {s.course_num: s.title for s in ctx.schedule.sections}
    questions = []
    for course_num, missing in ctx.confirmation_targets.items():
        title = titles.get(course_num, "")
        questions.append(
            ConfirmationQuestion(
                course_num=course_num,
                title=title,
                missing_prereqs=missing,
                question=_question_text(course_num, title, missing),
            )
        )
    return questions


# --- Backends ----------------------------------------------------------------


class LLMBackend(Protocol):
    name: str

    def explain_schedule(
        self,
        ctx: ScheduleContext,
        profile: StudentProfile,
        *,
        fit_rank: int,
        question: Optional[str],
        retrieved_context: Optional[str],
        prior_failures: Optional[list[ClaimCheck]],
    ) -> ScheduleExplanation: ...


class StubLLM:
    """Deterministic, all-true explanation built from the schedule facts.

    Emits exactly the claim types the verifier checks, every one true by
    construction — so with no API key the pipeline runs end to end and all
    returned claims pass verification.
    """

    name = "stub"

    def explain_schedule(
        self,
        ctx: ScheduleContext,
        profile: StudentProfile,
        *,
        fit_rank: int,
        question: Optional[str] = None,
        retrieved_context: Optional[str] = None,
        prior_failures: Optional[list[ClaimCheck]] = None,
    ) -> ScheduleExplanation:
        schedule = ctx.schedule
        course_nums = schedule.course_nums
        free = _free_days(schedule)

        free_phrase = (
            f" It keeps {', '.join(free)} free." if free else " It meets every weekday."
        )
        explanation = (
            f"This schedule carries {schedule.total_units:g} units across "
            f"{len(course_nums)} course(s): {', '.join(course_nums)}."
            f"{free_phrase} There are no time conflicts, and the estimated workload "
            f"is about {schedule.total_workload_hours:g} hours/week."
        )

        claims: list[Claim] = [
            TotalUnitsClaim(value=schedule.total_units),
            NoConflictsClaim(),
        ]
        claims.extend(IncludesCourseClaim(course_num=num) for num in course_nums)
        claims.extend(NoClassOnClaim(day=day) for day in free)

        return ScheduleExplanation(
            explanation=explanation,
            fit_rank=fit_rank,
            claims=claims,
            confirmation_questions=build_confirmation_questions(ctx),
        )


class AnthropicLLM:
    """Real backend: Anthropic API (``claude-opus-4-8``), structured output.

    The prompt hands the model only the solver's facts and constrains it to emit
    claims in the verifier's schema. Its output is still run through the verifier
    — the model is never trusted, only checked.
    """

    name = "anthropic"

    def explain_schedule(
        self,
        ctx: ScheduleContext,
        profile: StudentProfile,
        *,
        fit_rank: int,
        question: Optional[str] = None,
        retrieved_context: Optional[str] = None,
        prior_failures: Optional[list[ClaimCheck]] = None,
    ) -> ScheduleExplanation:
        import anthropic  # lazy: optional dependency, only needed on the real path

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

        facts = _facts_block(ctx)
        correction = ""
        if prior_failures:
            issues = "; ".join(c.message for c in prior_failures)
            correction = (
                "\n\nYour previous claims failed verification and were rejected: "
                f"{issues}. Emit only claims that are true of the schedule above."
            )

        system = (
            "You explain course schedules a deterministic solver already produced. "
            "You must NOT invent courses, sections, times, or units — use only the "
            "facts given. Emit factual assertions ONLY as structured claims drawn "
            "from the allowed claim types; every claim must be true of the schedule."
        )
        user = (
            f"Student interests: {', '.join(profile.interests) or 'none stated'}.\n"
            f"{'Question: ' + question if question else ''}\n"
            f"{'Context: ' + retrieved_context if retrieved_context else ''}\n\n"
            f"Schedule facts:\n{facts}\n\n"
            f"Write a short plain-language explanation, a fit_rank of {fit_rank}, "
            "structured claims, and a confirmation question for each unconfirmed "
            f"course.{correction}"
        )

        response = client.messages.parse(
            model=_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=ScheduleExplanation,
        )
        parsed = response.parsed_output
        if parsed is None:  # pragma: no cover - defensive; the verifier still gates output
            return ScheduleExplanation(
                explanation="", fit_rank=fit_rank, claims=[], confirmation_questions=[]
            )
        return parsed


def _facts_block(ctx: ScheduleContext) -> str:
    schedule = ctx.schedule
    lines = [
        f"- total_units: {schedule.total_units:g}",
        f"- total_workload_hours: {schedule.total_workload_hours:g}",
        f"- courses: {', '.join(schedule.course_nums) or 'none'}",
        f"- free_days: {', '.join(_free_days(schedule)) or 'none'}",
    ]
    for section in schedule.sections:
        state = ctx.classifications.get(section.course_num, "eligible")
        lines.append(
            f"- section {section.course_num} {section.section_id}: "
            f"{''.join(section.days)} {section.begin}-{section.end} ({state})"
        )
    for course_num, missing in ctx.confirmation_targets.items():
        lines.append(f"- unconfirmed {course_num}: needs {', '.join(missing)}")
    return "\n".join(lines)


def select_backend() -> LLMBackend:
    """Real backend if a key and the SDK are available, else the deterministic stub."""
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401

            return AnthropicLLM()
        except Exception:  # pragma: no cover - SDK missing despite a key present
            pass
    return StubLLM()


# --- Orchestration -----------------------------------------------------------


def orchestrate(
    contexts: list[ScheduleContext],
    profile: StudentProfile,
    *,
    question: Optional[str] = None,
    retrieved_context: Optional[str] = None,
    backend: Optional[LLMBackend] = None,
    regenerate_attempts: int = 0,
) -> OrchestrationResult:
    """Explain and rank each schedule, then gate every claim through the verifier.

    For each schedule the chosen backend produces an explanation + claims; the
    claims are verified; failures are stripped, and — up to
    ``regenerate_attempts`` times — the backend is re-asked with the failures
    named. Only claims that pass verification are returned.
    """
    backend = backend or select_backend()

    explanations: list[VerifiedExplanation] = []
    for rank, ctx in enumerate(contexts, start=1):
        raw = backend.explain_schedule(
            ctx,
            profile,
            fit_rank=rank,
            question=question,
            retrieved_context=retrieved_context,
            prior_failures=None,
        )
        result = verify(raw.claims, ctx.schedule)

        attempts = 0
        while result.failed_checks and attempts < regenerate_attempts:
            attempts += 1
            raw = backend.explain_schedule(
                ctx,
                profile,
                fit_rank=rank,
                question=question,
                retrieved_context=retrieved_context,
                prior_failures=result.failed_checks,
            )
            result = verify(raw.claims, ctx.schedule)

        explanations.append(
            VerifiedExplanation(
                schedule=ctx.schedule,
                classifications=ctx.classifications,
                fit_rank=raw.fit_rank,
                explanation=raw.explanation,
                verified_claims=result.passed_claims,
                stripped_claims=result.failed_checks,
                confirmation_questions=raw.confirmation_questions,
            )
        )

    return OrchestrationResult(backend=backend.name, explanations=explanations)
