from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    allowed_origins: str = "http://localhost:5173"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    groq_api_key: str = ""
    ai_model_fast: str = "openai/gpt-oss-20b"
    ai_model_quality: str = "openai/gpt-oss-120b"
    ai_timeout_seconds: float = 20
    ai_max_retries: int = 1
    ai_context_max_chars: int = 24_000
    ai_max_output_tokens: int = 1_200

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        return [value.strip() for value in self.allowed_origins.split(",") if value.strip()]
