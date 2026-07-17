"""LLM orchestrator — the chat turn, and the translation from talk to constraints.

**Correctness-critical.** This is the only place a language model touches the
pipeline, and the project context (§2) is strict about what it may do: *the LLM
never originates or edits schedule data.* In this module it does exactly two
things, both of which are proposals, not actions:

1. **Classify intent** — is this turn a question about the current schedule, or a
   request to change it?
2. **Propose constraints** — turn "make it lighter" / "swap the Friday class" into
   a *structured* :class:`ScheduleConstraints`, drawn from a closed vocabulary.

Everything downstream of that is deterministic. The constraints are translated by
:func:`constraints_to_solver_inputs` into the solver's existing, already-tested
inputs (a units cap, commitment blocks, an exclusion set) and the **solver**
produces the actual new schedule. The model cannot place a section, invent a
course, or edit a calendar — it can only ask the solver a differently-shaped
question. If the model proposes nonsense, the worst case is a schedule the
student didn't want, never an invalid or fabricated one.

The safety gate is unchanged and provider-independent: any factual claim the
model makes about a schedule goes through :func:`app.verifier.verify` before it
can reach the student, and failed claims are stripped. See
:mod:`app.llm_provider` for the provider abstraction; nothing here knows or cares
which model answers.
"""

from __future__ import annotations

from datetime import time
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.llm_provider import LLMProvider, Message, embed_facts
from app.models import Day, Schedule, StudentProfile, TimeBlock
from app.prereq import Classification
from app.rationale import free_days
from app.verifier import Claim, ClaimCheck, verify

ALL_DAYS: list[Day] = ["M", "T", "W", "R", "F"]

# Sentinel bounds for the full-day / open-ended commitment blocks below.
_DAY_START = time(0, 0)
_DAY_END = time(23, 59)


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


class ScheduleContext(BaseModel):
    """Everything the LLM is *given* about one schedule — it invents nothing."""

    schedule: Schedule
    classifications: dict[str, Classification] = Field(default_factory=dict)
    # course_num -> still-missing prereqs, for the unconfirmed courses on this schedule.
    confirmation_targets: dict[str, list[str]] = Field(default_factory=dict)


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


# --- The chat vocabulary -----------------------------------------------------


class ScheduleConstraints(BaseModel):
    """A closed, structured vocabulary of schedule changes the student can ask for.

    Deliberately small and mechanically translatable: every field maps to an input
    the solver already supports and already has tests for (see
    :func:`constraints_to_solver_inputs`). The LLM may only fill these fields — it
    has no way to express "put 15-213 here", which is precisely the point.
    """

    # Weekdays the student wants kept clear ("swap the Friday class").
    avoid_days: list[Day] = Field(default_factory=list)
    # Upper bound on total units ("make it lighter").
    max_units: Optional[float] = None
    # Earliest a class may start ("nothing before 10").
    no_class_before: Optional[time] = None
    # Latest a class may run to ("prioritize morning classes").
    no_class_after: Optional[time] = None
    # Courses to keep off the schedule ("drop 76-101").
    exclude_courses: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.avoid_days
            or self.max_units is not None
            or self.no_class_before is not None
            or self.no_class_after is not None
            or self.exclude_courses
        )

    def describe(self) -> str:
        """Plain-language echo of what is currently constraining the solver."""
        parts: list[str] = []
        if self.avoid_days:
            parts.append(f"no class on {', '.join(self.avoid_days)}")
        if self.max_units is not None:
            parts.append(f"at most {self.max_units:g} units")
        if self.no_class_before is not None:
            parts.append(f"nothing before {self.no_class_before.strftime('%H:%M')}")
        if self.no_class_after is not None:
            parts.append(f"nothing after {self.no_class_after.strftime('%H:%M')}")
        if self.exclude_courses:
            parts.append(f"without {', '.join(self.exclude_courses)}")
        return "; ".join(parts) if parts else "no constraints"


class ChatMessage(BaseModel):
    """One conversation turn. The client echoes these back so follow-ups have context."""

    role: Literal["user", "assistant"]
    content: str


class ChatTurn(BaseModel):
    """What the LLM *proposes* for one turn — the response schema it must fill.

    ``constraints`` is the FULL constraint set that should hold after this turn,
    not a delta, so that follow-ups accumulate ("make it lighter" then "also no
    Fridays") without the client having to merge anything.
    """

    kind: Literal["question", "modification"]
    reply: str
    constraints: ScheduleConstraints = Field(default_factory=ScheduleConstraints)
    # Factual assertions about the CURRENT schedule. Every one is verified before
    # it can reach the student; failures are stripped.
    claims: list[Claim] = Field(default_factory=list)


# --- Chat -> solver translation (deterministic) ------------------------------


def constraints_to_solver_inputs(
    constraints: ScheduleConstraints,
    *,
    base_commitments: list[TimeBlock],
    default_units_cap: float,
) -> tuple[float, list[TimeBlock], set[str]]:
    """Turn proposed constraints into the solver's existing inputs.

    This is the whole of the chat's power over the calendar, and it is pure,
    total, and deterministic. Time-based wishes become ordinary **commitment
    blocks** — the same mechanism a student's job or practice already uses — so
    the solver needs no new code path and its tested invariants (no conflicts,
    commitments respected, units cap honored) apply unchanged.

    Returns ``(units_cap, commitments, excluded_course_nums)``.
    """
    cap = default_units_cap
    if constraints.max_units is not None:
        # Never *raise* the cap above the institutional ceiling — a student can ask
        # for a lighter load, not for an overload.
        cap = min(default_units_cap, max(0.0, constraints.max_units))

    blocks = list(base_commitments)
    for day in constraints.avoid_days:
        blocks.append(
            TimeBlock(label=f"keep {day} free", days=[day], begin=_DAY_START, end=_DAY_END)
        )
    if constraints.no_class_before is not None:
        blocks.append(
            TimeBlock(
                label="no early classes",
                days=list(ALL_DAYS),
                begin=_DAY_START,
                end=constraints.no_class_before,
            )
        )
    if constraints.no_class_after is not None:
        blocks.append(
            TimeBlock(
                label="no late classes",
                days=list(ALL_DAYS),
                begin=constraints.no_class_after,
                end=_DAY_END,
            )
        )

    return cap, blocks, set(constraints.exclude_courses)


# --- Prompt construction -----------------------------------------------------


def _facts_block(ctx: ScheduleContext) -> str:
    schedule = ctx.schedule
    lines = [
        f"- total_units: {schedule.total_units:g}",
        f"- total_workload_hours: {schedule.total_workload_hours:g}",
        f"- courses: {', '.join(schedule.course_nums) or 'none'}",
        f"- free_days: {', '.join(free_days(schedule)) or 'none'}",
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


_SYSTEM = (
    "You are a scheduling assistant. A deterministic solver owns the calendar: you "
    "NEVER place, move, or invent a course, section, or time. You do exactly two "
    "things.\n"
    "1. Decide `kind`: 'question' if the student is asking about the current "
    "schedule, 'modification' if they want it changed.\n"
    "2. If it is a modification, fill `constraints` with the FULL set of "
    "constraints that should hold afterwards (carry over the ones already in "
    "effect, shown below, unless the student is undoing them). The solver will "
    "rebuild the calendar from those constraints.\n"
    "Write `reply` in plain language. Put every factual assertion about the "
    "CURRENT schedule in `claims` using the allowed claim types — each is checked "
    "against the real schedule and dropped if untrue. Use only the facts given."
)


def build_chat_messages(
    ctx: Optional[ScheduleContext],
    profile: StudentProfile,
    *,
    message: str,
    history: list[ChatMessage],
    constraints: ScheduleConstraints,
) -> list[Message]:
    """Build the provider-neutral prompt for one chat turn.

    Carries the conversation so far, the constraints already in effect, and the
    facts of the schedule on screen — nothing else. Identical for every provider.
    """
    transcript = (
        "\n".join(f"{m.role}: {m.content}" for m in history) or "(no prior turns)"
    )
    facts_payload: dict = {
        "response_kind": "chat_turn",
        "message": message,
        "active_constraints": constraints.model_dump(mode="json"),
        "history_turns": len(history),
    }
    if ctx is not None:
        facts_payload.update(
            {
                "total_units": ctx.schedule.total_units,
                "total_workload_hours": ctx.schedule.total_workload_hours,
                "courses": ctx.schedule.course_nums,
                "free_days": free_days(ctx.schedule),
            }
        )

    user = (
        f"Student interests: {', '.join(profile.interests) or 'none stated'}.\n\n"
        f"Conversation so far:\n{transcript}\n\n"
        f"Constraints currently in effect: {constraints.describe()}\n\n"
        f"Current schedule facts:\n"
        f"{_facts_block(ctx) if ctx is not None else '- (no schedule yet)'}\n\n"
        f"{embed_facts(facts_payload)}\n\n"
        f"Student says: {message}"
    )
    return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]


# --- The gated turn ----------------------------------------------------------


class GatedTurn(BaseModel):
    """A chat turn after the verifier gate: only passed claims survive."""

    kind: Literal["question", "modification"]
    reply: str
    constraints: ScheduleConstraints
    verified_claims: list[Claim] = Field(default_factory=list)
    stripped_claims: list[ClaimCheck] = Field(default_factory=list)
    backend: str = "stub"


def orchestrate_chat_turn(
    provider: LLMProvider,
    profile: StudentProfile,
    *,
    message: str,
    history: list[ChatMessage],
    constraints: ScheduleConstraints,
    ctx: Optional[ScheduleContext],
) -> GatedTurn:
    """Ask the provider for one turn, then gate every claim it made.

    The provider proposes; the verifier disposes. Claims are checked against the
    schedule the student is actually looking at, so a model that says "you have
    Tuesdays off" when a Tuesday section exists gets that claim stripped — no
    matter which provider it is.
    """
    turn = provider.generate(
        build_chat_messages(
            ctx, profile, message=message, history=history, constraints=constraints
        ),
        ChatTurn,
    )

    verified: list[Claim] = []
    stripped: list[ClaimCheck] = []
    if ctx is not None and turn.claims:
        result = verify(turn.claims, ctx.schedule)
        verified, stripped = result.passed_claims, result.failed_checks

    return GatedTurn(
        kind=turn.kind,
        reply=turn.reply,
        constraints=turn.constraints,
        verified_claims=verified,
        stripped_claims=stripped,
        backend=provider.name,
    )
