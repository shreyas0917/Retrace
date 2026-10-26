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

    # --- Session auth for the console (v1.0) ---
    # HMAC key for signing short-lived session tokens. When unset, a key is
    # derived from API_KEY so development works out of the box; set an
    # independent random value in production.
    session_secret: str | None = Field(default=None, alias="SESSION_SECRET")
    session_ttl_minutes: int = Field(default=480, alias="SESSION_TTL_MINUTES")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")

    # --- Abuse controls (v1.0) ---
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")
    auth_rate_limit_per_minute: int = Field(
        default=10, alias="AUTH_RATE_LIMIT_PER_MINUTE"
    )
    max_query_chars: int = Field(default=4000, alias="MAX_QUERY_CHARS")
    max_request_bytes: int = Field(default=1_048_576, alias="MAX_REQUEST_BYTES")

    # --- LLM resilience (v1.0) ---
    model_max_retries: int = Field(default=2, alias="MODEL_MAX_RETRIES")
    model_retry_backoff_seconds: float = Field(
        default=0.5, alias="MODEL_RETRY_BACKOFF_SECONDS"
    )
    model_connect_timeout_seconds: float = Field(
        default=10.0, alias="MODEL_CONNECT_TIMEOUT_SECONDS"
    )

    # --- Durable telemetry + cost accounting (v1.0) ---
    telemetry_durable: bool = Field(default=True, alias="TELEMETRY_DURABLE")
    pricing_path: str | None = Field(default=None, alias="PRICING_PATH")

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

    @property
    def effective_session_secret(self) -> str:
        """Session signing key: SESSION_SECRET, else derived from API_KEY."""
        if self.session_secret and self.session_secret.strip():
            return self.session_secret.strip()
        import hashlib

        return hashlib.sha256(f"retrace-session:{self.api_key}".encode("utf-8")).hexdigest()


def get_settings() -> Settings:
    """Load settings; raises ValidationError if required config is missing."""
    return Settings()  # type: ignore[call-arg]
