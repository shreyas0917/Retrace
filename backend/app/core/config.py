from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    environment: str = Field(default="development", alias="ENVIRONMENT")
    api_key: str = Field(..., alias="API_KEY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str = Field(..., alias="DATABASE_URL")

    chroma_host: str = Field(..., alias="CHROMA_HOST")
    chroma_port: int = Field(..., alias="CHROMA_PORT")

    model_base_url: str = Field(..., alias="MODEL_BASE_URL")
    model_api_key: str = Field(..., alias="MODEL_API_KEY")
    model_name: str = Field(..., alias="MODEL_NAME")

    model_timeout_seconds: float = Field(default=60.0, alias="MODEL_TIMEOUT_SECONDS")

    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="EMBEDDING_MODEL",
    )

    cors_origins: str = Field(
        default="http://localhost:5173",
        alias="CORS_ORIGINS",
    )

    @field_validator("api_key")
    @classmethod
    def api_key_must_be_set(cls, value: str) -> str:
        if not value or value.strip() in {"", "replace-me"}:
            raise ValueError("API_KEY must be set to a non-placeholder value")
        return value

    @field_validator("embedding_model")
    @classmethod
    def embedding_model_must_match_prd(cls, value: str) -> str:
        expected = "sentence-transformers/all-MiniLM-L6-v2"
        if value != expected:
            raise ValueError(
                f"EMBEDDING_MODEL must be '{expected}' (PRD-locked); got '{value}'"
            )
        return value

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


def get_settings() -> Settings:
    """Load settings; raises ValidationError if required config is missing."""
    return Settings()  # type: ignore[call-arg]
