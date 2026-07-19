import httpx
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
async def client():
    settings = Settings(
        supabase_url="https://test.supabase.co",
        supabase_anon_key="test-anon",
        gemini_api_key="",
    )
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
