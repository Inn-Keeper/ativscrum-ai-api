from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.errors import AppError
from app.supabase import Session, SupabaseGateway


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_url="https://test.supabase.co",
        supabase_anon_key="test-anon-key",
    )


def assert_caller_credentials(request: httpx.Request, token: str) -> None:
    assert request.headers.get_list("apikey") == ["test-anon-key"]
    assert request.headers.get_list("authorization") == [f"Bearer {token}"]
    credential_headers = {
        name
        for name in request.headers
        if "authorization" in name
        or "apikey" in name
        or "api-key" in name
        or name == "cookie"
    }
    assert credential_headers == {"apikey", "authorization"}
    serialized = f"{request.url}\n{request.headers}\n{request.content!r}".lower()
    assert "service_role" not in serialized


@pytest.mark.asyncio
async def test_validate_session_forwards_only_anon_key_and_caller_token(settings):
    token = "caller-token"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/auth/v1/user"
        assert_caller_credentials(request, token)
        return httpx.Response(200, json={"id": "user-123"})

    gateway = SupabaseGateway(settings, transport=httpx.MockTransport(handler))

    assert await gateway.validate_session(token) == Session(
        user_id="user-123", token=token
    )


@pytest.mark.asyncio
async def test_validate_session_maps_401_to_authentication_required(settings):
    gateway = SupabaseGateway(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(401)),
    )

    with pytest.raises(AppError) as raised:
        await gateway.validate_session("expired-token")

    assert raised.value.status_code == 401
    assert raised.value.code == "authentication_required"


@pytest.mark.asyncio
async def test_read_board_is_caller_scoped_and_returns_board_data(settings):
    org_id = uuid4()
    session = Session(user_id="user-123", token="caller-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/boards"
        assert dict(request.url.params) == {
            "org_id": f"eq.{org_id}",
            "select": "data",
        }
        assert_caller_credentials(request, session.token)
        return httpx.Response(200, json=[{"data": {"project": {"name": "Mine"}}}])

    gateway = SupabaseGateway(settings, transport=httpx.MockTransport(handler))

    assert await gateway.read_board(session, org_id) == {
        "project": {"name": "Mine"}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json=[]), httpx.Response(401), httpx.Response(403)],
)
async def test_read_board_hides_missing_and_forbidden_boards(settings, response):
    gateway = SupabaseGateway(
        settings,
        transport=httpx.MockTransport(lambda request: response),
    )

    with pytest.raises(AppError) as raised:
        await gateway.read_board(
            Session(user_id="user-123", token="caller-token"), uuid4()
        )

    assert raised.value.status_code == 403
    assert raised.value.code == "organization_forbidden"
    assert "board" not in raised.value.message.lower()


@pytest.mark.asyncio
async def test_consume_quota_is_caller_scoped(settings):
    org_id = uuid4()
    session = Session(user_id="user-123", token="caller-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/consume_ai_quota"
        assert request.read() == f'{{"org":"{org_id}"}}'.encode()
        assert_caller_credentials(request, session.token)
        return httpx.Response(200, json={"allowed": True})

    gateway = SupabaseGateway(settings, transport=httpx.MockTransport(handler))

    assert await gateway.consume_quota(session, org_id) == {"allowed": True}


@pytest.mark.asyncio
async def test_consume_quota_maps_daily_limit(settings):
    gateway = SupabaseGateway(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400, json={"code": "P0001", "message": "AI_DAILY_LIMIT"}
            )
        ),
    )

    with pytest.raises(AppError) as raised:
        await gateway.consume_quota(
            Session(user_id="user-123", token="caller-token"), uuid4()
        )

    assert raised.value.status_code == 429
    assert raised.value.code == "daily_quota_reached"
