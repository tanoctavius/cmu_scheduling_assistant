"""Provider-agnostic LLM access — one interface, swappable implementations.

The orchestrator talks to exactly one abstraction, :class:`LLMProvider`, with a
single method::

    generate(messages, response_schema) -> response_schema instance

It does **not** know (or ask) which provider is behind that call. Provider choice
is runtime configuration, never code: :func:`select_provider` reads ``LLM_PROVIDER``
and constructs the implementation. Keys, base URLs, and model names are read from
the environment — no secrets and no model IDs are baked in here.

Implementations
---------------
- ``stub`` (**default**) — :class:`StubProvider`, deterministic and offline. It
  needs no key, no SDK, and no network, so tests and CI run with zero cloud
  dependency. This is what makes the default path safe in a Learner Lab session.
- ``groq`` — :class:`GroqProvider`, a plain HTTPS call to Groq's OpenAI-compatible
  Chat Completions API. It touches neither AWS Bedrock nor AWS IAM, so it works
  inside AWS Academy Learner Lab (no role creation, no region constraints).

Adding another provider (Anthropic direct, Bedrock, OpenAI, …) later means writing
one class with a ``generate`` method and adding it to :data:`_PROVIDERS` — no
orchestrator or verifier change. The verifier gate sits *downstream* of every
provider, so the deterministic safety guarantee is provider-independent.

Environment variables
---------------------
- ``LLM_PROVIDER``  — ``stub`` (default) | ``groq``
- ``LLM_MODEL``     — model name, required by ``groq`` (e.g. ``llama-3.3-70b-versatile``)
- ``GROQ_API_KEY``  — required by ``groq``
- ``GROQ_BASE_URL`` — optional override (default ``https://api.groq.com/openai/v1``)
- ``LLM_TIMEOUT_SECONDS`` — optional request timeout (default ``30``)

Statelessness: providers hold no cross-request state and are constructed per call,
so the app starts cleanly from cold and is safe against the session timer.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.verifier import (
    Claim,
    IncludesCourseClaim,
    NoClassOnClaim,
    NoConflictsClaim,
    TotalUnitsClaim,
)

T = TypeVar("T", bound=BaseModel)

DEFAULT_PROVIDER = "stub"
GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0


class ProviderError(RuntimeError):
    """Provider misconfiguration, transport failure, or unusable response."""


# --- The interface -----------------------------------------------------------


class Message(BaseModel):
    """One chat message. Deliberately provider-neutral (OpenAI-shaped roles)."""

    role: str  # "system" | "user" | "assistant"
    content: str


class LLMProvider(Protocol):
    """The only LLM abstraction the orchestrator knows about."""

    name: str

    def generate(self, messages: list[Message], response_schema: type[T]) -> T:
        """Return an instance of ``response_schema`` built from ``messages``."""
        ...


# --- Grounding payload -------------------------------------------------------
#
# The orchestrator embeds the solver's facts as a machine-readable JSON block
# inside the prompt. Real providers read it as grounding context like any other
# prompt text; the offline stub parses it back out to build a truthful response.
# One message shape therefore serves every provider.

_FACTS_RE = re.compile(r"<facts>\s*(\{.*?\})\s*</facts>", re.DOTALL)


def embed_facts(payload: dict) -> str:
    """Render the solver's facts as a prompt-embeddable, parseable block."""
    return f"<facts>\n{json.dumps(payload, sort_keys=True)}\n</facts>"


def extract_facts(messages: list[Message]) -> dict:
    """Pull the facts block back out of a prompt (last one wins)."""
    for message in reversed(messages):
        match = _FACTS_RE.search(message.content)
        if match:
            return json.loads(match.group(1))
    raise ProviderError("No <facts> block found in messages.")


# --- stub: deterministic, offline, no key ------------------------------------


# Keyword tables for the stub's tiny, deterministic stand-in for language
# understanding. A real provider does this semantically; the stub only has to be
# good enough that the app is demoable and testable with no key.
_MODIFY_WORDS = (
    "swap", "change", "move", "drop", "remove", "without", "avoid", "lighter",
    "heavier", "easier", "harder", "prioritize", "prefer", "instead", "add ",
    "free up", "make it", "fewer", "less ", "more ", "reschedule", "no class",
)
_DAY_WORDS = {
    "monday": "M", "mon": "M", "tuesday": "T", "tues": "T", "wednesday": "W",
    "wed": "W", "thursday": "R", "thurs": "R", "friday": "F", "fri": "F",
}
_LIGHTER_WORDS = ("lighter", "less work", "easier", "fewer units", "fewer courses", "reduce")


class StubProvider:
    """Deterministic chat turn built from the embedded facts.

    Reads the ``<facts>`` block the orchestrator embedded, classifies the turn
    with simple keyword rules, and emits claims that are true by construction — so
    with no key the whole pipeline runs end to end and every claim passes the
    gate. Makes no network call of any kind.

    Its "understanding" is deliberately shallow. That is safe here precisely
    because it has no authority: like every provider, it can only *propose*
    constraints, and the deterministic solver builds the actual schedule.
    """

    name = "stub"

    def generate(self, messages: list[Message], response_schema: type[T]) -> T:
        facts = extract_facts(messages)
        kind = facts.get("response_kind", "chat_turn")
        if kind != "chat_turn":  # pragma: no cover - guards a future schema
            raise ProviderError(f"StubProvider cannot build a {kind!r} response.")

        message: str = str(facts.get("message", "")).lower()
        courses: list[str] = list(facts.get("courses", []))
        free: list[str] = list(facts.get("free_days", []))
        total_units = float(facts.get("total_units", 0.0))
        workload = float(facts.get("total_workload_hours", 0.0))
        active = dict(facts.get("active_constraints") or {})

        is_modification = any(word in message for word in _MODIFY_WORDS)

        if not is_modification:
            # Question: answer from the facts, and assert only true things.
            free_phrase = (
                f" It keeps {', '.join(free)} free." if free else " It meets every weekday."
            )
            reply = (
                f"Your schedule carries {total_units:g} units across "
                f"{len(courses)} course(s): {', '.join(courses) or 'none'}."
                f"{free_phrase} There are no time conflicts, and the estimated "
                f"workload is about {workload:g} hours/week."
            )
            claims: list[Claim] = [
                TotalUnitsClaim(value=total_units),
                NoConflictsClaim(),
            ]
            claims.extend(IncludesCourseClaim(course_num=num) for num in courses)
            claims.extend(NoClassOnClaim(day=day) for day in free)
            return response_schema.model_validate(
                {
                    "kind": "question",
                    "reply": reply,
                    "constraints": active,
                    "claims": claims,
                }
            )

        # Modification: accumulate onto the constraints already in effect, so
        # follow-ups build on prior turns rather than resetting them.
        constraints = _stub_constraints(message, active, courses, total_units)
        return response_schema.model_validate(
            {
                "kind": "modification",
                "reply": (
                    "Updated your constraints and rebuilt the schedule with the "
                    "solver."
                ),
                "constraints": constraints,
                # The schedule is about to be re-solved, so any claim about the
                # current one would be stale. Assert nothing.
                "claims": [],
            }
        )


def _stub_constraints(
    message: str, active: dict, courses: list[str], total_units: float
) -> dict:
    """Deterministic keyword -> constraint mapping, accumulated onto `active`."""
    out = dict(active)

    days = list(out.get("avoid_days") or [])
    for word, day in _DAY_WORDS.items():
        if word in message and day not in days:
            days.append(day)
    if days:
        out["avoid_days"] = days

    if any(word in message for word in _LIGHTER_WORDS):
        # One course lighter than what's on screen, floored so it stays solvable.
        current_cap = out.get("max_units") or total_units
        out["max_units"] = max(9.0, float(current_cap) - 9.0)

    if "morning" in message:
        out["no_class_after"] = "12:00:00"
    elif "afternoon" in message:
        out["no_class_before"] = "12:00:00"

    excluded = list(out.get("exclude_courses") or [])
    if any(word in message for word in ("drop", "remove", "without")):
        for course in courses:
            if course.lower() in message and course not in excluded:
                excluded.append(course)
    if excluded:
        out["exclude_courses"] = excluded

    return out


# --- groq: OpenAI-compatible HTTPS, no AWS involvement ------------------------


def _with_schema_instruction(messages: list[Message], schema: dict) -> list[Message]:
    """Append the response JSON Schema to the system turn (portable across models)."""
    instruction = (
        "Respond with a single JSON object and nothing else. It must validate "
        "against this JSON Schema:\n" + json.dumps(schema)
    )
    out = list(messages)
    for i, message in enumerate(out):
        if message.role == "system":
            out[i] = Message(
                role="system", content=f"{message.content}\n\n{instruction}"
            )
            return out
    return [Message(role="system", content=instruction), *out]


class GroqProvider:
    """Groq via its OpenAI-compatible Chat Completions endpoint.

    A direct HTTPS call (``httpx``, already a dependency) rather than the OpenAI
    SDK — same wire format, one less dependency. Model name and key come from the
    environment; nothing about the model is hardcoded. No AWS Bedrock, no IAM.
    """

    name = "groq"

    def __init__(self) -> None:
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ProviderError("LLM_PROVIDER=groq requires GROQ_API_KEY to be set.")
        self.model = os.getenv("LLM_MODEL")
        if not self.model:
            raise ProviderError(
                "LLM_PROVIDER=groq requires LLM_MODEL to be set "
                "(e.g. llama-3.3-70b-versatile)."
            )
        self.base_url = os.getenv("GROQ_BASE_URL", GROQ_DEFAULT_BASE_URL).rstrip("/")
        self.timeout = float(
            os.getenv("LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )

    def generate(self, messages: list[Message], response_schema: type[T]) -> T:
        import httpx  # already a core dependency; imported here to keep import cheap

        prompt = _with_schema_instruction(messages, response_schema.model_json_schema())
        body = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in prompt],
            # OpenAI-compatible JSON mode: broadly supported across Groq models,
            # unlike per-model json_schema support.
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"Groq request failed: {exc}") from exc

        try:
            return response_schema.model_validate_json(content)
        except ValidationError as exc:
            # Malformed model output is a provider problem, surfaced as one. Any
            # *well-formed but false* claim still gets caught downstream by the
            # verifier — that gate is independent of this parse.
            raise ProviderError(f"Groq returned unparseable output: {exc}") from exc


# --- Selection ---------------------------------------------------------------

# name -> zero-arg factory. Add a provider by adding a class and one entry here.
_PROVIDERS: dict[str, type] = {
    StubProvider.name: StubProvider,
    GroqProvider.name: GroqProvider,
}


def select_provider(name: Optional[str] = None) -> LLMProvider:
    """Construct the provider named by ``LLM_PROVIDER`` (default ``stub``).

    Constructed fresh per call — no client is cached across requests, so nothing
    survives a restart and cold start is always clean.
    """
    key = (name or os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    factory = _PROVIDERS.get(key)
    if factory is None:
        raise ProviderError(
            f"Unknown LLM_PROVIDER {key!r}. Known providers: {sorted(_PROVIDERS)}."
        )
    return factory()
