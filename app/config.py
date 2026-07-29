from functools import lru_cache
from pydantic import Field, AnyUrl,field_validator,EmailStr,ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote_plus
from typing import Literal

class Settings(BaseSettings):
    # Application
    APP_NAME: str = "HelpDoctor"
    ENV: Literal[
        "development",
        "staging",
        "production",
    ] = "development"
    DEBUG: bool = False


    # PostgreSQL
    POSTGRES_HOST: str
    POSTGRES_PORT: int = Field(
        default=5432,
        ge=1,
        le=65535,
    )
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str


    REDIS_URL: str = "redis://localhost:6379/0"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = Field(
        default=6379,
        ge=1,
        le=65535,
    )

    # Elasticsearch
    ELASTIC_HOST: AnyUrl = "http://localhost:9200"

    # Google OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    WHATSAPP_ACCESS_TOKEN: str
    WHATSAPP_PHONE_NUMBER_ID: str

    BKASH_BASE_URL: AnyUrl
    BKASH_APP_KEY: str
    BKASH_APP_SECRET: str
    BKASH_USERNAME: str
    BKASH_PASSWORD: str
    BKASH_CALLBACK_URL: AnyUrl

    NAGAD_BASE_URL: AnyUrl
    NAGAD_MERCHANT_ID: str
    NAGAD_PUBLIC_KEY: str
    NAGAD_PRIVATE_KEY: str
    NAGAD_CALLBACK_URL: AnyUrl

    # ROCKET
    ROCKET_BASE_URL: AnyUrl
    ROCKET_MERCHANT_ID: str
    ROCKET_API_KEY: str
    ROCKET_CALLBACK_URL: AnyUrl

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid"
    )

    # JWT
    JWT_SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # VAPID
    VAPID_PUBLIC_KEY: str | None = None
    VAPID_PRIVATE_KEY: str | None = None
    VAPID_EMAIL: str | None = None

    #QR
    BASE_URL: AnyUrl

    #Email
    MAIL_HOST: str
    MAIL_PORT: int = Field(
        default=587,
        ge=1,
        le=65535,
    )

    MAIL_USERNAME: str
    MAIL_PASSWORD: str

    MAIL_FROM: EmailStr

    MAIL_USE_TLS: bool = True

    ENABLE_MEDICINE_AI: bool = False

    AI_PROVIDER: Literal[
        "openai",
        "anthropic",
        "gemini",
    ] = "openai"

    OPENAI_API_KEY: str | None = None

    OPENAI_MODEL: str = "gpt-4.1-mini"


    FRONTEND_URL: str = "http://localhost:5173"

    # Payment gateway: "bkash" (live) or "fake" (dev/test simulate flow).
    PAYMENT_GATEWAY: Literal["bkash", "fake"] = "bkash"

    ALLOWED_ORIGINS: str = "http://localhost:5173"

    METRICS_TOKEN: str | None = None

    # OpenTelemetry OTLP/HTTP traces endpoint (the collector to export spans to).
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: str = "http://localhost:4318/v1/traces"

    # Sentry error monitoring. Leave unset to disable (no-op).
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # Rate-limit storage. Default in-memory (per-process). For a multi-instance
    # deploy set a shared backend so limits are distributed, e.g.
    # "async+redis://host:6379". A Redis outage fails open (swallow_errors).
    RATE_LIMIT_STORAGE_URI: str | None = None

    # Super Admin bootstrap (used by scripts/create_super_admin.py)
    SUPER_ADMIN_EMAIL: EmailStr | None = None
    SUPER_ADMIN_PASSWORD: str | None = None
    SUPER_ADMIN_NAME: str = "Platform Super Admin"

    # Require a verified email before password login is allowed.
    REQUIRE_EMAIL_VERIFICATION: bool = True

    @property
    def allowed_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    @field_validator("DEBUG")
    @classmethod
    def validate_debug(
        cls,
        value: bool,
        info: ValidationInfo,
    ) -> bool:

        env = info.data.get("ENV")

        if env == "production" and value:
            raise ValueError(
                "DEBUG cannot be enabled in production"
            )

        return value


    @field_validator("PAYMENT_GATEWAY")
    @classmethod
    def validate_payment_gateway(
        cls,
        value: str,
        info: ValidationInfo,
    ) -> str:
        # The fake gateway is a dev/test simulator — never allow real money
        # flows to be bypassed in production.
        if info.data.get("ENV") == "production" and value == "fake":
            raise ValueError(
                "PAYMENT_GATEWAY=fake is not allowed in production"
            )

        return value


    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(
        cls,
        value: str,
    ) -> str:

        if len(value.strip()) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters"
            )

        return value
        
    
    @property
    def database_url(self) -> str:
        password = quote_plus(self.POSTGRES_PASSWORD)

        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            #f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{password}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()