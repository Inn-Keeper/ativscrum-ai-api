from uuid import UUID

import httpx
import pytest

from app.config import Settings
from app.errors import AppError
from app.groq import GroqResult
from app.main import create_app
from app.schemas import (
    CoachSuggestion,
    SprintSummarySuggestion,
    StandupSuggestion,
    StorySuggestion,
)
from app.service import GenerateService
from app.supabase import Session


ORG_ID = "11111111-1111-1111-1111-111111111111"


def board() -> dict:
    return {
        "project": {"name": "Example", "dod": []},
        "sprints": [
            {
                "id": "sprint-1",
                "name": "Sprint 1",
                "goal": "Ship",
                "startDate": "2026-07-01",
                "endDate": "2026-07-14",
                "state": "active",
            }
        ],
        "items": [
            {
                "id": "story-1",
                "title": "Story",
                "description": "Description",
                "acceptance": [],
                "type": "feature",
                "priority": "medium",
                "estimateDays": 1,
                "sprintId": "sprint-1",
            }
        ],
        "tasks": [
            {
                "id": "task-1",
                "backlogItemId": "story-1",
                "title": "Task",
                "assigneeId": "person-1",
                "status": "done",
                "completedAt": "2026-07-10",
            }
        ],
        "people": [{"id": "person-1", "name": "Person"}],
        "transitions": [],
        "reviewCards": [],
        "retroCards": [],
        "wipLimits": {"inprogress": 2},
        "metrics": {"cycleTimeDays": 2},
    }


SUGGESTIONS = {
    "sprint_summary": SprintSummarySuggestion(
        headline="On track",
        narrative="The sprint completed its work.",
        completed=["Story"],
        carry_over=[],
        blockers=[],
        next_focus=["Release"],
    ),
    "story_assistant": StorySuggestion(
        description="A useful story.",
        acceptance=["It works."],
        tasks=["Build it."],
        estimate_days=1,
        estimate_rationale="Small scope.",
    ),
    "standup_draft": StandupSuggestion(
        members=[
            {
                "member_id": "person-1",
                "member_name": "Person",
                "completed": ["Task"],
                "current": [],
                "blockers": [],
            }
        ]
    ),
    "scrum_coach": CoachSuggestion(
        observations=[
            {
                "severity": "info",
                "claim": "Cycle time is stable.",
                "suggestion": "Keep the current limit.",
                "evidence": [{"kind": "metric", "id": "cycleTimeDays"}],
            }
        ]
    ),
}

REQUESTS = {
    "sprint_summary": {
        "kind": "sprint_summary",
        "org_id": ORG_ID,
        "sprint_id": "sprint-1",
    },
    "story_assistant": {
        "kind": "story_assistant",
        "org_id": ORG_ID,
        "item_id": "story-1",
    },
    "standup_draft": {
        "kind": "standup_draft",
        "org_id": ORG_ID,
        "sprint_id": "sprint-1",
    },
    "scrum_coach": {
        "kind": "scrum_coach",
        "org_id": ORG_ID,
        "sprint_id": "sprint-1",
    },
}


class FakeGateway:
    def __init__(self, events, *, failure: str | None = None, board_data=None):
        self.events = events
        self.failure = failure
        self.board_data = board_data if board_data is not None else board()

    async def validate_session(self, token):
        self.events.append("validate_session")
        if self.failure == "auth":
            raise AppError(401, "authentication_required", "Authentication required.")
        return Session(user_id="user-1", token=token)

    async def read_board(self, session, org_id):
        self.events.append("read_board")
        if self.failure == "forbidden":
            raise AppError(403, "organization_forbidden", "Forbidden.")
        return self.board_data

    async def consume_quota(self, session, org_id):
        self.events.append("consume_quota")
        return {"allowed": True}


class FakeGroq:
    def __init__(self, events, *, failure=False):
        self.events = events
        self.failure = failure

    async def generate(self, model, system_prompt, context, output_type):
        self.events.append("groq")
        if self.failure:
            raise AppError(503, "provider_unavailable", "Provider unavailable.")
        return GroqResult(
            value=SUGGESTIONS[context["kind"]],
            prompt_tokens=20,
            completion_tokens=10,
            retries=0,
        )


def service(events, *, gateway_failure=None, groq_failure=False, board_data=None):
    configured = Settings(
        supabase_url="https://test.supabase.co",
        supabase_anon_key="anon",
        groq_api_key="secret",
    )
    return GenerateService(
        configured,
        FakeGateway(events, failure=gateway_failure, board_data=board_data),
        FakeGroq(events, failure=groq_failure),
    )


async def post(
    generation_service,
    body,
    *,
    token="caller-token",
    authorization: str | None = None,
):
    app = create_app(Settings(), generation_service=generation_service)
    transport = httpx.ASGITransport(app=app)
    if authorization is not None:
        headers = {"Authorization": authorization}
    else:
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/ai/generate", json=body, headers=headers)


@pytest.mark.asyncio
async def test_generation_calls_security_boundaries_in_exact_order():
    events = []

    response = await post(service(events), REQUESTS["story_assistant"])

    assert response.status_code == 200
    assert events == ["validate_session", "read_board", "consume_quota", "groq"]


@pytest.mark.asyncio
async def test_lifespan_shares_and_closes_one_http_client(monkeypatch):
    clients = []

    class CapturingSupabase:
        def __init__(self, settings, *, http_client):
            clients.append(http_client)

    class CapturingGroq:
        def __init__(self, settings, *, http_client):
            clients.append(http_client)

    monkeypatch.setattr("app.main.SupabaseGateway", CapturingSupabase)
    monkeypatch.setattr("app.main.GroqClient", CapturingGroq)

    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        assert len(clients) == 2
        assert clients[0] is clients[1]
        assert clients[0].is_closed is False

    assert clients[0].is_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "token", "gateway_failure", "expected_status"),
    [
        ({"kind": "story_assistant", "org_id": ORG_ID}, "token", None, 422),
        (REQUESTS["story_assistant"], None, None, 401),
        (REQUESTS["story_assistant"], "token", "auth", 401),
        (REQUESTS["story_assistant"], "token", "forbidden", 403),
        (
            {**REQUESTS["story_assistant"], "item_id": "missing"},
            "token",
            None,
            404,
        ),
    ],
)
async def test_failures_before_context_validation_never_consume_quota(
    body, token, gateway_failure, expected_status
):
    events = []

    response = await post(
        service(events, gateway_failure=gateway_failure), body, token=token
    )

    assert response.status_code == expected_status
    assert "consume_quota" not in events
    assert "groq" not in events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization",
    ["Bearer token extra", "Bearer token\tpart", "Basic token"],
)
async def test_malformed_bearer_credentials_are_rejected_before_session_validation(
    authorization,
):
    events = []

    response = await post(
        service(events),
        REQUESTS["story_assistant"],
        authorization=authorization,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert events == []


@pytest.mark.asyncio
async def test_oversized_context_never_consumes_quota():
    events = []
    configured = Settings(ai_context_max_chars=50)
    generation_service = GenerateService(
        configured, FakeGateway(events), FakeGroq(events)
    )

    response = await post(generation_service, REQUESTS["story_assistant"])

    assert response.status_code == 422
    assert events == ["validate_session", "read_board"]


@pytest.mark.asyncio
async def test_provider_failure_occurs_after_exactly_one_quota_reservation():
    events = []

    response = await post(
        service(events, groq_failure=True), REQUESTS["story_assistant"]
    )

    assert response.status_code == 503
    assert events == ["validate_session", "read_board", "consume_quota", "groq"]
    assert events.count("consume_quota") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(REQUESTS))
async def test_all_generation_kinds_return_the_typed_contract(kind):
    events = []

    response = await post(service(events), REQUESTS[kind])

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == kind
    assert UUID(payload["request_id"])
    assert payload["model"] in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}
    assert payload["suggestion"] == SUGGESTIONS[kind].model_dump(mode="json")


def test_openapi_exposes_only_discriminated_request_union_and_bearer_security():
    app = create_app(Settings(), generation_service=service([]))
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/ai/generate"]["post"]

    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    expected_variants = {
        "SprintSummaryRequest",
        "StoryAssistantRequest",
        "StandupDraftRequest",
        "ScrumCoachRequest",
    }
    assert request_schema["discriminator"]["propertyName"] == "kind"
    assert {
        reference["$ref"].rsplit("/", 1)[-1] for reference in request_schema["oneOf"]
    } == expected_variants
    assert {
        reference.rsplit("/", 1)[-1]
        for reference in request_schema["discriminator"]["mapping"].values()
    } == expected_variants

    def referenced_schemas(node):
        if isinstance(node, dict):
            reference = node.get("$ref")
            if reference:
                component = schema["components"]["schemas"][
                    reference.rsplit("/", 1)[-1]
                ]
                yield component
                yield from referenced_schemas(component)
            for key, value in node.items():
                if key != "$ref":
                    yield from referenced_schemas(value)
        elif isinstance(node, list):
            for value in node:
                yield from referenced_schemas(value)

    resolved_request_schemas = [request_schema, *referenced_schemas(request_schema)]
    assert "prompt" not in {
        property_name
        for component in resolved_request_schemas
        for property_name in component.get("properties", {})
    }
    assert operation["security"] == [{"HTTPBearer": []}]
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }


@pytest.mark.asyncio
async def test_coach_rejects_evidence_absent_from_minimized_context():
    events = []
    bad_groq = FakeGroq(events)
    board_data = board()
    board_data["items"].append(
        {
            "id": "story-outside-sprint",
            "title": "Outside story",
            "type": "feature",
            "priority": "medium",
            "estimateDays": 1,
            "sprintId": "different-sprint",
        }
    )
    board_data["tasks"].append(
        {
            "id": "task-outside-sprint",
            "backlogItemId": "story-outside-sprint",
            "title": "Outside task",
            "assigneeId": None,
            "status": "todo",
            "completedAt": None,
        }
    )

    async def generate(*args, **kwargs):
        events.append("groq")
        return GroqResult(
            value=CoachSuggestion(
                observations=[
                    {
                        "severity": "warning",
                        "claim": "Unsupported claim.",
                        "suggestion": "Unsupported action.",
                        "evidence": [{"kind": "task", "id": "task-outside-sprint"}],
                    }
                ]
            ),
            prompt_tokens=2,
            completion_tokens=3,
            retries=0,
        )

    bad_groq.generate = generate
    generation_service = GenerateService(
        Settings(), FakeGateway(events, board_data=board_data), bad_groq
    )

    response = await post(generation_service, REQUESTS["scrum_coach"])

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_model_response"
    assert events == ["validate_session", "read_board", "consume_quota", "groq"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "members",
    [
        [
            {
                "member_id": "invented-person",
                "member_name": "Invented Person",
                "completed": [],
                "current": [],
                "blockers": [],
            }
        ],
        [
            {
                "member_id": "person-1",
                "member_name": "Wrong Name",
                "completed": [],
                "current": [],
                "blockers": [],
            }
        ],
        [
            {
                "member_id": "person-1",
                "member_name": "Person",
                "completed": [],
                "current": [],
                "blockers": [],
            },
            {
                "member_id": "person-1",
                "member_name": "Person",
                "completed": [],
                "current": [],
                "blockers": [],
            },
        ],
    ],
    ids=["invented-member", "mismatched-name", "duplicate-member"],
)
async def test_standup_rejects_members_not_matching_minimized_context(members):
    events = []
    bad_groq = FakeGroq(events)

    async def generate(*args, **kwargs):
        events.append("groq")
        return GroqResult(
            value=StandupSuggestion(members=members),
            prompt_tokens=2,
            completion_tokens=3,
            retries=0,
        )

    bad_groq.generate = generate
    generation_service = GenerateService(Settings(), FakeGateway(events), bad_groq)

    response = await post(generation_service, REQUESTS["standup_draft"])

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_model_response"
    assert events == ["validate_session", "read_board", "consume_quota", "groq"]


@pytest.mark.asyncio
async def test_member_standup_rejects_other_real_member_outside_requested_scope():
    events = []
    board_data = board()
    board_data["people"].append({"id": "person-2", "name": "Other Person"})
    board_data["tasks"].append(
        {
            "id": "task-2",
            "backlogItemId": "story-1",
            "title": "Other task",
            "assigneeId": "person-2",
            "status": "todo",
            "completedAt": None,
        }
    )
    bad_groq = FakeGroq(events)

    async def generate(*args, **kwargs):
        events.append("groq")
        return GroqResult(
            value=StandupSuggestion(
                members=[
                    {
                        "member_id": "person-2",
                        "member_name": "Other Person",
                        "completed": [],
                        "current": ["Other task"],
                        "blockers": [],
                    }
                ]
            ),
            prompt_tokens=2,
            completion_tokens=3,
            retries=0,
        )

    bad_groq.generate = generate
    generation_service = GenerateService(
        Settings(), FakeGateway(events, board_data=board_data), bad_groq
    )

    response = await post(
        generation_service,
        {**REQUESTS["standup_draft"], "member_id": "person-1"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_model_response"
    assert events == ["validate_session", "read_board", "consume_quota", "groq"]
