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
from app.orchestrator import ScheduleExplanation
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
        "fit_rank": 2,
        "total_units": 22.0,
        "total_workload_hours": 31.0,
        "courses": ["15-122", "15-213"],
        "free_days": ["F"],
        "confirmation_questions": [
            {
                "course_num": "15-122",
                "title": "Imperative Computation",
                "missing_prereqs": ["15-112"],
                "question": "Have you taken 15-112?",
            }
        ],
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
    result = StubProvider().generate(_facts_message(), ScheduleExplanation)

    assert isinstance(result, ScheduleExplanation)
    assert result.explanation  # non-empty prose
    assert result.fit_rank == 2  # taken from the facts, not invented

    # Claims are true of the facts it was given.
    units = next(c for c in result.claims if isinstance(c, TotalUnitsClaim))
    assert units.value == 22.0
    included = {c.course_num for c in result.claims if isinstance(c, IncludesCourseClaim)}
    assert included == {"15-122", "15-213"}
    assert [c.day for c in result.claims if isinstance(c, NoClassOnClaim)] == ["F"]

    # Confirmation questions are passed through, never authored by the provider.
    (q,) = result.confirmation_questions
    assert q.course_num == "15-122"
    assert q.missing_prereqs == ["15-112"]


def test_stub_handles_a_schedule_with_no_free_days(no_network):
    result = StubProvider().generate(
        _facts_message(free_days=[]), ScheduleExplanation
    )
    assert "meets every weekday" in result.explanation
    assert not [c for c in result.claims if isinstance(c, NoClassOnClaim)]


# --- groq: mocked HTTP, no real key ------------------------------------------


def _ok_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        request=httpx.Request("POST", "https://example.invalid"),
    )


_VALID_PAYLOAD = {
    "explanation": "Two courses, Friday free.",
    "fit_rank": 1,
    "claims": [{"type": "total_units", "value": 22.0}],
    "confirmation_questions": [],
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
    result = GroqProvider().generate(_facts_message(), ScheduleExplanation)

    # Parsed into the requested schema.
    assert isinstance(result, ScheduleExplanation)
    assert result.explanation == "Two courses, Friday free."

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
    GroqProvider().generate(_facts_message(), ScheduleExplanation)
    assert seen["url"] == "https://proxy.example.invalid/v1/chat/completions"


def test_groq_transport_failure_becomes_provider_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    def boom(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(ProviderError, match="Groq request failed"):
        GroqProvider().generate(_facts_message(), ScheduleExplanation)


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
        GroqProvider().generate(_facts_message(), ScheduleExplanation)
