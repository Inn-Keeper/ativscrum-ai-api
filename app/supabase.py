from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.config import Settings
from app.errors import AppError


@dataclass(frozen=True, slots=True)
class Session:
    user_id: str
    token: str


class SupabaseGateway:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.supabase_url.rstrip("/")
        self._anon_key = settings.supabase_anon_key
        self._http_client = http_client
        self._transport = transport

    async def validate_session(self, token: str) -> Session:
        response = await self._request("GET", "/auth/v1/user", token)
        if response.status_code in (401, 403):
            raise AppError(401, "authentication_required", "Authentication required.")
        self._raise_upstream_error(response)
        user_id = response.json().get("id")
        if not user_id:
            raise AppError(401, "authentication_required", "Authentication required.")
        return Session(user_id=str(user_id), token=token)

    async def read_board(self, session: Session, org_id: UUID) -> dict[str, Any]:
        response = await self._request(
            "GET",
            "/rest/v1/boards",
            session.token,
            params={"org_id": f"eq.{org_id}", "select": "data"},
        )
        if response.status_code in (401, 403):
            self._raise_organization_forbidden()
        self._raise_upstream_error(response)
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1:
            self._raise_organization_forbidden()
        return rows[0]["data"]

    async def consume_quota(self, session: Session, org_id: UUID) -> Any:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/consume_ai_quota",
            session.token,
            json={"org": str(org_id)},
        )
        if "AI_DAILY_LIMIT" in response.text:
            raise AppError(429, "daily_quota_reached", "Daily AI quota reached.")
        if response.status_code in (401, 403):
            self._raise_organization_forbidden()
        self._raise_upstream_error(response)
        return response.json()

    async def _request(
        self, method: str, path: str, token: str, **kwargs
    ) -> httpx.Response:
        headers = {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {token}",
        }
        if self._http_client is not None:
            return await self._http_client.request(
                method, f"{self._base_url}{path}", headers=headers, **kwargs
            )
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
            return await client.request(
                method, f"{self._base_url}{path}", headers=headers, **kwargs
            )

    @staticmethod
    def _raise_organization_forbidden() -> None:
        raise AppError(
            403,
            "organization_forbidden",
            "You cannot access that organization.",
        )

    @staticmethod
    def _raise_upstream_error(response: httpx.Response) -> None:
        if response.is_error:
            raise AppError(502, "supabase_request_failed", "Upstream request failed.")
