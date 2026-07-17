"""LLM orchestrator — the explain-and-rank layer, guarded by the verifier.

This is the one place a language model touches the pipeline, and the project
context (§2) is strict about what it may do: **the LLM never originates schedule
data.** It receives schedules the deterministic solver already produced and, per
schedule, emits a natural-language explanation, a fit ranking, and a *structured*
list of factual claims plus prereq confirmation questions. Every factual claim is
then re-checked by the Stage 4 verifier before anything is returned — failed
claims are stripped (and optionally regenerated). An unverified factual claim
about a schedule never reaches output.

Provider-agnostic
-----------------
This module knows nothing about *which* model or vendor answers. It builds
messages, hands them to an :class:`~app.llm_provider.LLMProvider` along with the
response schema, and gates whatever comes back. Swapping providers is an env var
(``LLM_PROVIDER``), never a code change here — and, critically, **the verifier
gate is downstream of every provider**, so the safety guarantee is identical no
matter who generated the claims. See :mod:`app.llm_provider`.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.llm_provider import LLMProvider, Message, embed_facts, select_provider
from app.models import Schedule, StudentProfile
from app.prereq import Classification
from app.verifier import Claim, ClaimCheck, verify

_DAY_ORDER = ["M", "T", "W", "R", "F"]


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


# --- Prompt construction -----------------------------------------------------


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


def build_messages(
    ctx: ScheduleContext,
    profile: StudentProfile,
    *,
    fit_rank: int,
    question: Optional[str] = None,
    retrieved_context: Optional[str] = None,
    prior_failures: Optional[list[ClaimCheck]] = None,
) -> list[Message]:
    """Build the provider-neutral prompt for one schedule.

    The same messages go to every provider. They carry only facts the solver
    already produced — the model is asked to explain and rank, never to originate
    schedule data. An embedded ``<facts>`` JSON block grounds real providers and
    lets the offline stub reconstruct a truthful answer.
    """
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
    facts_payload = {
        "fit_rank": fit_rank,
        "total_units": ctx.schedule.total_units,
        "total_workload_hours": ctx.schedule.total_workload_hours,
        "courses": ctx.schedule.course_nums,
        "free_days": _free_days(ctx.schedule),
        "confirmation_questions": [
            q.model_dump() for q in build_confirmation_questions(ctx)
        ],
    }
    user = (
        f"Student interests: {', '.join(profile.interests) or 'none stated'}.\n"
        f"{'Question: ' + question if question else ''}\n"
        f"{'Context: ' + retrieved_context if retrieved_context else ''}\n\n"
        f"Schedule facts:\n{_facts_block(ctx)}\n\n"
        f"{embed_facts(facts_payload)}\n\n"
        f"Write a short plain-language explanation, a fit_rank of {fit_rank}, "
        "structured claims, and a confirmation question for each unconfirmed "
        f"course.{correction}"
    )
    return [Message(role="system", content=system), Message(role="user", content=user)]


# --- Orchestration -----------------------------------------------------------


def orchestrate(
    contexts: list[ScheduleContext],
    profile: StudentProfile,
    *,
    question: Optional[str] = None,
    retrieved_context: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
    regenerate_attempts: int = 0,
) -> OrchestrationResult:
    """Explain and rank each schedule, then gate every claim through the verifier.

    For each schedule the selected provider produces an explanation + claims; the
    claims are verified; failures are stripped, and — up to
    ``regenerate_attempts`` times — the provider is re-asked with the failures
    named. Only claims that pass verification are returned.

    Which provider answers is irrelevant to this function and to the gate below:
    every claim from every provider goes through the same :func:`verify`.
    """
    provider = provider or select_provider()

    explanations: list[VerifiedExplanation] = []
    for rank, ctx in enumerate(contexts, start=1):
        raw = provider.generate(
            build_messages(
                ctx,
                profile,
                fit_rank=rank,
                question=question,
                retrieved_context=retrieved_context,
            ),
            ScheduleExplanation,
        )
        result = verify(raw.claims, ctx.schedule)

        attempts = 0
        while result.failed_checks and attempts < regenerate_attempts:
            attempts += 1
            raw = provider.generate(
                build_messages(
                    ctx,
                    profile,
                    fit_rank=rank,
                    question=question,
                    retrieved_context=retrieved_context,
                    prior_failures=result.failed_checks,
                ),
                ScheduleExplanation,
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

    return OrchestrationResult(backend=provider.name, explanations=explanations)
