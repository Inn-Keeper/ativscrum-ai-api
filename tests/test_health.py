import pytest


@pytest.mark.asyncio
async def test_health_is_always_live(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_rejects_missing_provider_key(client):
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "missing": ["GROQ_API_KEY"]}
