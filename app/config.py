from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


STRICT_GROQ_MODELS = frozenset({"openai/gpt-oss-20b", "openai/gpt-oss-120b"})


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

    @field_validator("ai_model_fast", "ai_model_quality")
    @classmethod
    def require_strict_groq_model(cls, value: str) -> str:
        if value not in STRICT_GROQ_MODELS:
            supported = ", ".join(sorted(STRICT_GROQ_MODELS))
            raise ValueError(f"model must support Groq strict outputs: {supported}")
        return value

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        return [
            value.strip() for value in self.allowed_origins.split(",") if value.strip()
        ]
