"""Tests for the provider abstraction — selection, the offline stub, and Groq.

Correctness-critical by association: the orchestrator's safety gate is only as
trustworthy as the guarantee that *every* provider goes through it, and that the
default provider needs no network. Nothing here touches a real network or a real
key — the Groq path is exercised entirely over a mocked HTTP call.
"""

import json
import socket

import httpx
import pytest
from app.llm_provider import (
    GROQ_DEFAULT_BASE_URL,
    GroqProvider,
    Message,
    ProviderError,
    StubProvider,
    embed_facts,
    extract_facts,
    select_provider,
)
from app.orchestrator import ChatTurn
from app.verifier import IncludesCourseClaim, NoClassOnClaim, TotalUnitsClaim


@pytest.fixture
def no_network(monkeypatch):
    """Make any attempt to open a socket a hard failure."""

    def _boom(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(httpx, "post", _boom)


def _facts_message(**overrides) -> list[Message]:
    facts = {
        "response_kind": "chat_turn",
        "message": "what's my workload?",
        "active_constraints": {},
        "history_turns": 0,
        "total_units": 22.0,
        "total_workload_hours": 31.0,
        "courses": ["15-122", "15-213"],
        "free_days": ["F"],
        "sections": [
            {
                "course_num": "15-122",
                "title": "Principles of Imperative Computation",
                "days": ["T", "R"],
                "begin": "09:30:00",
                "end": "10:50:00",
            },
            {
                "course_num": "15-213",
                "title": "Introduction to Computer Systems",
                "days": ["M", "W"],
                "begin": "14:00:00",
                "end": "15:20:00",
            },
        ],
        "requirements_advanced": ["Computer Science Core"],
    }
    facts.update(overrides)
    return [
        Message(role="system", content="You explain schedules."),
        Message(role="user", content=f"Schedule facts:\n{embed_facts(facts)}"),
    ]


# --- Selection ---------------------------------------------------------------


def test_select_provider_defaults_to_stub(monkeypatch):
    # Zero configuration -> the offline stub. This is what keeps CI cloud-free.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert select_provider().name == "stub"


def test_select_provider_ignores_case_and_whitespace(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "  STUB ")
    assert select_provider().name == "stub"


def test_select_provider_rejects_unknown_name(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    with pytest.raises(ProviderError, match="Unknown LLM_PROVIDER"):
        select_provider()


def test_select_provider_returns_groq_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    provider = select_provider()
    assert provider.name == "groq"
    assert isinstance(provider, GroqProvider)


def test_select_provider_constructs_fresh_instances(monkeypatch):
    # No cached client: nothing persists across requests or survives a restart.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert select_provider() is not select_provider()


# --- Facts payload round-trip ------------------------------------------------


def test_facts_round_trip():
    payload = {"total_units": 22.0, "courses": ["15-122"]}
    messages = [Message(role="user", content=f"x {embed_facts(payload)} y")]
    assert extract_facts(messages) == payload


def test_extract_facts_without_a_block_raises():
    with pytest.raises(ProviderError, match="No <facts> block"):
        extract_facts([Message(role="user", content="no facts here")])


# --- stub: offline, correct shape --------------------------------------------


def test_stub_needs_no_network_and_returns_correct_shape(no_network):
    # The whole point of the default: a valid, correctly-shaped response with no
    # key, no SDK, and no socket. `no_network` makes any network call an error.
    result = StubProvider().generate(_facts_message(), ChatTurn)

    assert isinstance(result, ChatTurn)
    assert result.kind == "question"
    assert result.reply  # non-empty prose

    # Claims are true of the facts it was given.
    units = next(c for c in result.claims if isinstance(c, TotalUnitsClaim))
    assert units.value == 22.0
    included = {c.course_num for c in result.claims if isinstance(c, IncludesCourseClaim)}
    assert included == {"15-122", "15-213"}
    assert [c.day for c in result.claims if isinstance(c, NoClassOnClaim)] == ["F"]


def test_stub_handles_a_schedule_with_no_free_days(no_network):
    result = StubProvider().generate(_facts_message(free_days=[]), ChatTurn)
    assert "meets every weekday" in result.reply
    assert not [c for c in result.claims if isinstance(c, NoClassOnClaim)]


def test_stub_modification_turn_needs_no_network(no_network):
    # The chat's change path must also work with no key and no socket.
    result = StubProvider().generate(
        _facts_message(message="swap the Friday class"), ChatTurn
    )
    assert result.kind == "modification"
    assert result.constraints.avoid_days == ["F"]
    assert result.claims == []  # asserts nothing about a schedule about to change


def test_stub_rejects_an_unknown_response_kind(no_network):
    with pytest.raises(ProviderError, match="cannot build"):
        StubProvider().generate(_facts_message(response_kind="something_else"), ChatTurn)


# --- stub: question intents ---------------------------------------------------
#
# Each common question intent gets a sensible, deterministic answer grounded in
# the facts block. The claims are the same true-by-construction set every time,
# so everything still passes the verifier downstream.


def test_stub_workload_question_leads_with_workload(no_network):
    result = StubProvider().generate(_facts_message(message="what's my workload?"), ChatTurn)
    assert result.kind == "question"
    assert "31 hours/week" in result.reply


def test_stub_units_question_quotes_the_real_total(no_network):
    result = StubProvider().generate(
        _facts_message(message="how many units am I taking?"), ChatTurn
    )
    assert result.kind == "question"
    assert "22 units" in result.reply


def test_stub_why_course_question_explains_the_meeting_pattern(no_network):
    result = StubProvider().generate(
        _facts_message(message="why is 15-213 on monday?"), ChatTurn
    )
    assert result.kind == "question"  # "why" wins over the day keyword
    assert "15-213" in result.reply
    assert "Monday/Wednesday" in result.reply
    assert "14:00–15:20" in result.reply


def test_stub_why_day_question_lists_that_days_sections(no_network):
    result = StubProvider().generate(
        _facts_message(message="why do I have class on tuesday?"), ChatTurn
    )
    assert result.kind == "question"
    assert "Tuesday" in result.reply and "15-122" in result.reply


def test_stub_why_free_day_question_says_it_is_free(no_network):
    result = StubProvider().generate(
        _facts_message(message="why is friday empty?"), ChatTurn
    )
    assert result.kind == "question"
    assert "no class on Friday" in result.reply


def test_stub_requirements_question_lists_advanced_groups(no_network):
    result = StubProvider().generate(
        _facts_message(message="which requirements does this cover?"), ChatTurn
    )
    assert result.kind == "question"
    assert "Computer Science Core" in result.reply


def test_stub_requirements_question_with_no_groups_is_honest(no_network):
    result = StubProvider().generate(
        _facts_message(
            message="which requirements does this cover?", requirements_advanced=[]
        ),
        ChatTurn,
    )
    assert "doesn't advance any" in result.reply


def test_stub_interest_question_points_at_a_matching_course(no_network):
    # "systems" appears in 15-213's title, so the stub can point at it truthfully.
    result = StubProvider().generate(
        _facts_message(message="something with systems please"), ChatTurn
    )
    assert result.kind == "question"
    assert "15-213" in result.reply


def test_stub_interest_question_without_a_match_stays_helpful(no_network):
    result = StubProvider().generate(
        _facts_message(message="something with graphics"), ChatTurn
    )
    assert result.kind == "question"
    assert "interests" in result.reply


# --- stub: modification intents ----------------------------------------------


def _constraints_for(message: str, **overrides):
    result = StubProvider().generate(_facts_message(message=message, **overrides), ChatTurn)
    assert result.kind == "modification", message
    assert result.claims == []  # a modification asserts nothing about the old schedule
    return result.constraints


def test_stub_make_it_lighter_lowers_the_units_cap(no_network):
    constraints = _constraints_for("make it lighter")
    assert constraints.max_units == 13.0  # 22 on screen, one 9-unit course lighter


def test_stub_avoid_fridays_maps_to_avoid_days(no_network):
    constraints = _constraints_for("avoid fridays")
    assert constraints.avoid_days == ["F"]


def test_stub_no_early_classes_maps_to_a_start_bound(no_network):
    constraints = _constraints_for("no early classes")
    assert constraints.no_class_before is not None
    assert constraints.no_class_before.hour == 10


def test_stub_prioritize_mornings_maps_to_an_end_bound(no_network):
    constraints = _constraints_for("prioritize morning classes")
    assert constraints.no_class_after is not None
    assert constraints.no_class_after.hour == 12


def test_stub_no_late_classes_maps_to_an_end_bound(no_network):
    constraints = _constraints_for("no late classes please")
    assert constraints.no_class_after is not None
    assert constraints.no_class_after.hour == 17


def test_stub_drop_course_by_number(no_network):
    # The typed course number is excluded even without naming it any other way.
    constraints = _constraints_for("drop 15-213")
    assert constraints.exclude_courses == ["15-213"]


def test_stub_lighter_topic_excludes_the_matching_course_not_the_cap(no_network):
    # "lighter theory load" drops the theory course rather than capping units.
    sections = [
        {
            "course_num": "15-251",
            "title": "Theory of Computation",
            "days": ["M", "W"],
            "begin": "10:00:00",
            "end": "11:20:00",
        },
        {
            "course_num": "15-213",
            "title": "Introduction to Computer Systems",
            "days": ["T", "R"],
            "begin": "14:00:00",
            "end": "15:20:00",
        },
    ]
    constraints = _constraints_for(
        "lighter theory load", sections=sections, courses=["15-251", "15-213"]
    )
    assert constraints.exclude_courses == ["15-251"]
    assert constraints.max_units is None  # topic match, so no blanket cap


def test_stub_is_deterministic(no_network):
    for message in ("what's my workload?", "make it lighter", "why is 15-213 on monday?"):
        a = StubProvider().generate(_facts_message(message=message), ChatTurn)
        b = StubProvider().generate(_facts_message(message=message), ChatTurn)
        assert a.model_dump() == b.model_dump(), message


# --- groq: mocked HTTP, no real key ------------------------------------------


def _ok_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        request=httpx.Request("POST", "https://example.invalid"),
    )


_VALID_PAYLOAD = {
    "kind": "question",
    "reply": "Two courses, Friday free.",
    "constraints": {},
    "claims": [{"type": "total_units", "value": 22.0}],
}


def test_groq_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    with pytest.raises(ProviderError, match="GROQ_API_KEY"):
        GroqProvider()


def test_groq_requires_model_name(monkeypatch):
    # The model is configuration, never hardcoded — so it must be demanded.
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ProviderError, match="LLM_MODEL"):
        GroqProvider()


def test_groq_calls_openai_compatible_endpoint_with_env_config(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)

    seen: dict = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _ok_response(_VALID_PAYLOAD)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = GroqProvider().generate(_facts_message(), ChatTurn)

    # Parsed into the requested schema.
    assert isinstance(result, ChatTurn)
    assert result.reply == "Two courses, Friday free."

    # Hit Groq's OpenAI-compatible route with the env-configured model and key.
    assert seen["url"] == f"{GROQ_DEFAULT_BASE_URL}/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert seen["json"]["model"] == "llama-3.3-70b-versatile"
    assert seen["json"]["response_format"] == {"type": "json_object"}
    # The response schema is handed to the model, and the facts survive the trip.
    system = next(m for m in seen["json"]["messages"] if m["role"] == "system")
    assert "JSON Schema" in system["content"]
    assert "<facts>" in seen["json"]["messages"][-1]["content"]


def test_groq_honours_base_url_override(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("GROQ_BASE_URL", "https://proxy.example.invalid/v1/")

    seen: dict = {}
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kw: (seen.update({"url": url}), _ok_response(_VALID_PAYLOAD))[1],
    )
    GroqProvider().generate(_facts_message(), ChatTurn)
    assert seen["url"] == "https://proxy.example.invalid/v1/chat/completions"


def test_groq_transport_failure_becomes_provider_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    def boom(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(ProviderError, match="Groq request failed"):
        GroqProvider().generate(_facts_message(), ChatTurn)


def test_groq_unparseable_output_becomes_provider_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not json at all"}}]},
            request=httpx.Request("POST", "https://example.invalid"),
        ),
    )
    with pytest.raises(ProviderError, match="unparseable"):
        GroqProvider().generate(_facts_message(), ChatTurn)
