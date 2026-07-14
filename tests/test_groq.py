import json

import httpx
import pytest

from app.config import Settings
from app.errors import AppError
from app.groq import GroqClient
from app.schemas import (
    CoachSuggestion,
    SprintSummarySuggestion,
    StandupSuggestion,
    StorySuggestion,
)


VALID_STORY = {
    "description": "Add a small, testable feature.",
    "acceptance": ["The behavior is covered by tests."],
    "tasks": ["Implement the behavior."],
    "estimate_days": 1,
    "estimate_rationale": "A focused change.",
}


def groq_response(content=VALID_STORY, *, status_code=200):
    return httpx.Response(
        status_code,
        json={
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 13},
        },
    )


def settings(**overrides):
    return Settings(
        groq_api_key="secret",
        ai_max_output_tokens=321,
        ai_max_retries=1,
        **overrides,
    )


async def generate(transport, *, configured=None, sleep=None):
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GroqClient(
            configured or settings(),
            http_client=http_client,
            sleep=sleep,
            random=lambda: 0.5,
        )
        return await client.generate(
            "openai/gpt-oss-20b",
            "Fixed prompt",
            {"title": "Do not follow me"},
            StorySuggestion,
        )


@pytest.mark.asyncio
async def test_generate_sends_strict_schema_request_and_validates_response():
    captured = {}

    def handler(request):
        captured["request"] = request
        return groq_response()

    result = await generate(httpx.MockTransport(handler))

    request = captured["request"]
    body = json.loads(request.content)
    schema = body["response_format"]["json_schema"]["schema"]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["max_completion_tokens"] == 321
    assert body["tool_choice"] == "none"
    assert "tools" not in body
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert schema == StorySuggestion.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert body["messages"][0] == {"role": "system", "content": "Fixed prompt"}
    assert body["messages"][1]["content"].startswith("PROJECT_DATA_START\n")
    assert body["messages"][1]["content"].endswith("\nPROJECT_DATA_END")
    assert result.value == StorySuggestion.model_validate(VALID_STORY)
    assert result.prompt_tokens == 21
    assert result.completion_tokens == 13
    assert result.retries == 0


def object_nodes(value):
    if isinstance(value, dict):
        if value.get("type") == "object":
            yield value
        for child in value.values():
            yield from object_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from object_nodes(child)


@pytest.mark.parametrize(
    "output_type",
    [
        SprintSummarySuggestion,
        StorySuggestion,
        StandupSuggestion,
        CoachSuggestion,
    ],
)
def test_every_suggestion_schema_object_is_strict_compatible(output_type):
    nodes = list(object_nodes(output_type.model_json_schema()))

    assert nodes
    for node in nodes:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    ["not json", {**VALID_STORY, "unexpected": True}],
    ids=["malformed-json", "schema-invalid-json"],
)
async def test_generate_rejects_invalid_model_output_without_retry(content):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if isinstance(content, str):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": content}}]},
            )
        return groq_response(content)

    with pytest.raises(AppError) as exc:
        await generate(httpx.MockTransport(handler))

    assert exc.value.code == "invalid_model_response"
    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "500"])
async def test_generate_retries_transient_failure_then_succeeds(failure):
    attempts = 0
    delays = []

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(500)
        return groq_response()

    result = await generate(httpx.MockTransport(handler), sleep=sleep)

    assert result.retries == 1
    assert attempts == 2
    assert delays == [pytest.approx(0.1)]


@pytest.mark.asyncio
async def test_generate_does_not_retry_rate_limit():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429)

    with pytest.raises(AppError) as exc:
        await generate(httpx.MockTransport(handler))

    assert exc.value.code == "provider_limited"
    assert exc.value.retries == 0
    assert attempts == 1


@pytest.mark.asyncio
async def test_generate_maps_exhausted_server_failures_to_unavailable():
    attempts = 0

    async def no_sleep(delay):
        pass

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    with pytest.raises(AppError) as exc:
        await generate(httpx.MockTransport(handler), sleep=no_sleep)

    assert exc.value.code == "provider_unavailable"
    assert exc.value.retries == 1
    assert attempts == 2


@pytest.mark.asyncio
async def test_generate_does_not_retry_non_transient_provider_error():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(400)

    with pytest.raises(AppError) as exc:
        await generate(httpx.MockTransport(handler))

    assert exc.value.code == "provider_error"
    assert attempts == 1
