import asyncio
import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest

from app.config import Settings
from app.errors import AppError
from app.supabase import Session, SupabaseGateway


TEST_URL = os.getenv("TEST_SUPABASE_URL", "").rstrip("/")
TEST_ANON_KEY = os.getenv("TEST_SUPABASE_ANON_KEY", "")
TEST_SERVICE_KEY = os.getenv("TEST_SUPABASE_SERVICE_ROLE_KEY", "")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not all((TEST_URL, TEST_ANON_KEY, TEST_SERVICE_KEY)),
        reason="live Supabase test variables are not configured",
    ),
]


@dataclass(frozen=True)
class TenantPair:
    gateway: SupabaseGateway
    sessions: tuple[Session, Session]
    org_ids: tuple[UUID, UUID]
    sentinels: tuple[str, str]


async def checked(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    response = await client.request(method, path, **kwargs)
    assert response.is_success, f"Supabase setup failed: {response.status_code}"
    return response


@pytest.fixture
async def tenants():
    service_headers = {
        "apikey": TEST_SERVICE_KEY,
        "Authorization": f"Bearer {TEST_SERVICE_KEY}",
    }
    anon_headers = {"apikey": TEST_ANON_KEY}
    run_id = uuid4().hex
    emails = [f"ai-tenant-{run_id}-{index}@example.invalid" for index in (1, 2)]
    password = f"Test-{run_id}!Aa1"
    user_ids: list[str] = []
    org_ids: list[UUID] = []

    async with httpx.AsyncClient(base_url=TEST_URL, timeout=30) as client:
        try:
            for email in emails:
                response = await checked(
                    client,
                    "POST",
                    "/auth/v1/admin/users",
                    headers=service_headers,
                    json={
                        "email": email,
                        "password": password,
                        "email_confirm": True,
                    },
                )
                user_ids.append(response.json()["id"])

            for index, user_id in enumerate(user_ids, start=1):
                response = await checked(
                    client,
                    "POST",
                    "/rest/v1/organizations",
                    headers={**service_headers, "Prefer": "return=representation"},
                    json={"name": f"AI tenant {run_id} {index}", "created_by": user_id},
                )
                org_ids.append(UUID(response.json()[0]["id"]))

            sentinels = (f"sentinel-{run_id}-one", f"sentinel-{run_id}-two")
            for org_id, sentinel in zip(org_ids, sentinels, strict=True):
                await checked(
                    client,
                    "POST",
                    "/rest/v1/boards",
                    headers=service_headers,
                    json={"org_id": str(org_id), "data": {"project": {"name": sentinel}}},
                )

            sessions = []
            for email in emails:
                response = await checked(
                    client,
                    "POST",
                    "/auth/v1/token?grant_type=password",
                    headers=anon_headers,
                    json={"email": email, "password": password},
                )
                token = response.json()["access_token"]
                sessions.append(Session(user_id=response.json()["user"]["id"], token=token))

            yield TenantPair(
                gateway=SupabaseGateway(
                    Settings(supabase_url=TEST_URL, supabase_anon_key=TEST_ANON_KEY)
                ),
                sessions=(sessions[0], sessions[1]),
                org_ids=(org_ids[0], org_ids[1]),
                sentinels=sentinels,
            )
        finally:
            cleanup_errors = []
            for org_id in org_ids:
                try:
                    response = await client.delete(
                        f"/rest/v1/organizations?id=eq.{org_id}",
                        headers=service_headers,
                    )
                    if not response.is_success:
                        cleanup_errors.append(f"organization {org_id}: {response.status_code}")
                except httpx.HTTPError as exc:
                    cleanup_errors.append(f"organization {org_id}: {type(exc).__name__}")
            for user_id in user_ids:
                try:
                    response = await client.delete(
                        f"/auth/v1/admin/users/{user_id}", headers=service_headers
                    )
                    if not response.is_success:
                        cleanup_errors.append(f"user {user_id}: {response.status_code}")
                except httpx.HTTPError as exc:
                    cleanup_errors.append(f"user {user_id}: {type(exc).__name__}")
            assert not cleanup_errors, f"Supabase cleanup failed: {cleanup_errors}"


async def test_callers_can_read_only_their_own_tenant(tenants: TenantPair):
    first_board = await tenants.gateway.read_board(
        tenants.sessions[0], tenants.org_ids[0]
    )
    second_board = await tenants.gateway.read_board(
        tenants.sessions[1], tenants.org_ids[1]
    )
    assert first_board["project"]["name"] == tenants.sentinels[0]
    assert second_board["project"]["name"] == tenants.sentinels[1]

    for session, other_org in (
        (tenants.sessions[0], tenants.org_ids[1]),
        (tenants.sessions[1], tenants.org_ids[0]),
    ):
        with pytest.raises(AppError) as raised:
            await tenants.gateway.read_board(session, other_org)
        assert raised.value.code == "organization_forbidden"


async def test_daily_quota_is_atomic_under_concurrency(tenants: TenantPair):
    probe_org = uuid4()
    async with httpx.AsyncClient(base_url=TEST_URL, timeout=30) as client:
        probe = await client.post(
            "/rest/v1/rpc/consume_ai_quota",
            headers={
                "apikey": TEST_ANON_KEY,
                "Authorization": f"Bearer {tenants.sessions[0].token}",
            },
            json={"org": str(probe_org)},
        )
    if probe.status_code == 404 and "consume_ai_quota" in probe.text:
        pytest.skip("consume_ai_quota schema is not installed")

    results = await asyncio.gather(
        *(
            tenants.gateway.consume_quota(tenants.sessions[0], tenants.org_ids[0])
            for _ in range(11)
        ),
        return_exceptions=True,
    )
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(results) - len(errors) == 10
    assert len(errors) == 1
    assert isinstance(errors[0], AppError)
    assert errors[0].code == "daily_quota_reached"
