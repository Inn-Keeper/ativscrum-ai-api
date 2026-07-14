import hashlib
import logging
import time
from typing import Any
from uuid import UUID

from app.config import Settings
from app.context import build_context
from app.errors import AppError
from app.prompts import model_for, prompt_for
from app.schemas import (
    AiRequest,
    CoachSuggestion,
    ScrumCoachResponse,
    SprintSummaryResponse,
    SprintSummarySuggestion,
    StandupDraftResponse,
    StandupSuggestion,
    StoryAssistantResponse,
    StorySuggestion,
)


logger = logging.getLogger("app.ai")

_OUTPUTS = {
    "sprint_summary": SprintSummarySuggestion,
    "story_assistant": StorySuggestion,
    "standup_draft": StandupSuggestion,
    "scrum_coach": CoachSuggestion,
}

_RESPONSES = {
    "sprint_summary": SprintSummaryResponse,
    "story_assistant": StoryAssistantResponse,
    "standup_draft": StandupDraftResponse,
    "scrum_coach": ScrumCoachResponse,
}


def _hash(value: str | UUID | None) -> str:
    if value is None:
        return "-"
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(401, "authentication_required", "Authentication required.")
    return token.strip()


class GenerateService:
    def __init__(self, settings: Settings, gateway: Any, groq: Any) -> None:
        self.settings = settings
        self.gateway = gateway
        self.groq = groq

    async def generate(
        self,
        payload: AiRequest,
        authorization: str | None,
        request_id: str,
    ):
        started = time.perf_counter()
        model = model_for(payload.kind, self.settings)
        user_id = None
        metadata = {"retries": "-", "prompt_tokens": "-", "completion_tokens": "-"}
        try:
            token = _bearer_token(authorization)
            session = await self.gateway.validate_session(token)
            user_id = session.user_id
            board = await self.gateway.read_board(session, payload.org_id)
            context = build_context(board, payload, self.settings.ai_context_max_chars)
            await self.gateway.consume_quota(session, payload.org_id)
            result = await self.groq.generate(
                model,
                prompt_for(payload.kind),
                context,
                _OUTPUTS[payload.kind],
            )
            metadata = {
                "retries": result.retries,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }
            if payload.kind == "scrum_coach":
                self._validate_evidence(result.value, context)
            response_type = _RESPONSES[payload.kind]
            response = response_type(
                kind=payload.kind,
                request_id=UUID(request_id),
                model=model,
                suggestion=result.value,
            )
        except AppError as exc:
            if exc.retries is not None:
                metadata["retries"] = exc.retries
            self._log(
                request_id,
                payload.kind,
                model,
                exc.code,
                started,
                user_id,
                payload.org_id,
                **metadata,
            )
            raise
        except Exception:
            self._log(
                request_id,
                payload.kind,
                model,
                "internal_error",
                started,
                user_id,
                payload.org_id,
                **metadata,
            )
            raise

        self._log(
            request_id,
            payload.kind,
            model,
            "success",
            started,
            user_id,
            payload.org_id,
            **metadata,
        )
        return response

    @staticmethod
    def _validate_evidence(suggestion: CoachSuggestion, context: dict) -> None:
        valid = {
            "sprint": {context.get("sprint", {}).get("id")},
            "story": {item.get("id") for item in context.get("stories", [])},
            "task": {item.get("id") for item in context.get("tasks", [])},
            "metric": set(context.get("metrics", {})),
        }
        if any(
            evidence.id not in valid[evidence.kind]
            for observation in suggestion.observations
            for evidence in observation.evidence
        ):
            raise AppError(
                502,
                "invalid_model_response",
                "The AI provider returned an invalid response.",
            )

    @staticmethod
    def _log(
        request_id: str,
        kind: str,
        model: str,
        outcome: str,
        started: float,
        user_id: str | None,
        org_id: UUID,
        *,
        retries: int | str,
        prompt_tokens: int | str | None,
        completion_tokens: int | str | None,
    ) -> None:
        logger.info(
            "ai_generation request_id=%s kind=%s model=%s outcome=%s "
            "latency_ms=%d retries=%s prompt_tokens=%s completion_tokens=%s "
            "user_hash=%s org_hash=%s",
            request_id,
            kind,
            model,
            outcome,
            int((time.perf_counter() - started) * 1000),
            retries,
            prompt_tokens if prompt_tokens is not None else "-",
            completion_tokens if completion_tokens is not None else "-",
            _hash(user_id),
            _hash(org_id),
        )
