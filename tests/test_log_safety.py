import hashlib
import logging

import pytest

from app.config import Settings
from app.errors import AppError
from app.groq import GroqResult
from app.schemas import StorySuggestion
from app.service import GenerateService
from app.supabase import Session
from tests.test_generate import ORG_ID, REQUESTS, post


class SecretGateway:
    async def validate_session(self, token):
        return Session(user_id="secret@example.com", token=token)

    async def read_board(self, session, org_id):
        return {
            "project": {"name": "SECRET_BOARD_TEXT", "dod": []},
            "items": [
                {
                    "id": "story-1",
                    "title": "SECRET_BOARD_TEXT",
                    "description": "SECRET_BOARD_TEXT",
                    "acceptance": [],
                    "type": "feature",
                    "priority": "medium",
                    "estimateDays": 1,
                }
            ],
            "tasks": [],
        }

    async def consume_quota(self, session, org_id):
        return {"allowed": True}


class SecretGroq:
    async def generate(self, model, system_prompt, context, output_type):
        return GroqResult(
            value=StorySuggestion(
                description="SECRET_BOARD_TEXT",
                acceptance=["SECRET_BOARD_TEXT"],
                tasks=[],
                estimate_days=1,
                estimate_rationale="SECRET_BOARD_TEXT",
            ),
            prompt_tokens=21,
            completion_tokens=13,
            retries=1,
        )


class ProviderFailureGroq:
    async def generate(self, model, system_prompt, context, output_type):
        assert "SECRET_BOARD_TEXT" in str(context)
        raise AppError(
            503,
            "provider_unavailable",
            "The AI provider is unavailable.",
            retries=1,
        )


class RejectedGateway(SecretGateway):
    async def validate_session(self, token):
        raise AppError(401, "authentication_required", "Authentication required.")


@pytest.mark.asyncio
async def test_completion_log_contains_only_safe_structured_metadata(caplog):
    generation_service = GenerateService(
        Settings(),
        SecretGateway(),
        SecretGroq(),
    )

    with caplog.at_level(logging.INFO, logger="app.ai"):
        response = await post(
            generation_service,
            REQUESTS["story_assistant"],
            token="secret-token",
        )

    assert response.status_code == 200
    text = caplog.text
    assert "SECRET_BOARD_TEXT" not in text
    assert "secret@example.com" not in text
    assert "Bearer secret-token" not in text
    assert "secret-token" not in text
    assert ORG_ID not in text
    assert response.json()["request_id"] in text
    assert "kind=story_assistant" in text
    assert "model=openai/gpt-oss-20b" in text
    assert "outcome=success" in text
    assert "latency_ms=" in text
    assert "retries=1" in text
    assert "prompt_tokens=21" in text
    assert "completion_tokens=13" in text
    assert hashlib.sha256(b"secret@example.com").hexdigest()[:12] in text
    assert hashlib.sha256(ORG_ID.encode()).hexdigest()[:12] in text


@pytest.mark.asyncio
async def test_failure_log_is_content_free_and_has_safe_metadata(caplog):
    generation_service = GenerateService(
        Settings(),
        RejectedGateway(),
        SecretGroq(),
    )

    with caplog.at_level(logging.INFO, logger="app.ai"):
        response = await post(
            generation_service,
            REQUESTS["story_assistant"],
            token="secret-token",
        )

    assert response.status_code == 401
    text = caplog.text
    assert "secret-token" not in text
    assert ORG_ID not in text
    assert "kind=story_assistant" in text
    assert "model=openai/gpt-oss-20b" in text
    assert "outcome=authentication_required" in text
    assert "latency_ms=" in text
    assert "retries=-" in text
    assert "prompt_tokens=-" in text
    assert "completion_tokens=-" in text


@pytest.mark.asyncio
async def test_provider_failure_after_board_load_does_not_log_content_or_identifiers(
    caplog,
):
    generation_service = GenerateService(
        Settings(),
        SecretGateway(),
        ProviderFailureGroq(),
    )

    with caplog.at_level(logging.INFO, logger="app.ai"):
        response = await post(
            generation_service,
            REQUESTS["story_assistant"],
            token="secret-token",
        )

    assert response.status_code == 503
    text = caplog.text
    assert "SECRET_BOARD_TEXT" not in text
    assert "secret@example.com" not in text
    assert "secret-token" not in text
    assert ORG_ID not in text
    assert "outcome=provider_unavailable" in text
    assert "retries=1" in text
    assert hashlib.sha256(b"secret@example.com").hexdigest()[:12] in text
    assert hashlib.sha256(ORG_ID.encode()).hexdigest()[:12] in text
