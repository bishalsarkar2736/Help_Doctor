from functools import lru_cache
from pydantic import (
    Field,
    AnyUrl,
    field_validator,
    model_validator,
    EmailStr,
    ValidationInfo,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote_plus, unquote, urlsplit
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

    # The whole connection string, when something else supplies it.
    #
    # Declared so it is AUTHORITATIVE. Alembic already preferred it (env.py
    # reads TEST_DATABASE_URL, then DATABASE_URL, before falling back to these
    # settings), while the app composed its own URL from the POSTGRES_* parts
    # and never looked at it. Setting it therefore steered migrations and not
    # the application: the schema would be changed in one database while every
    # query ran against another.
    #
    # Managed platforms inject this variable automatically, so that split was
    # one deployment away rather than hypothetical.
    #
    # The POSTGRES_* parts stay required regardless: the postgres container
    # itself is configured from them, as are the healthcheck and the backup
    # scripts. Where both exist they must agree — enforced below.
    DATABASE_URL: str | None = None

    # Connection pool, applied PER PROCESS. The ceiling is
    #   (api procs + celery children + beat) x (POOL_SIZE + MAX_OVERFLOW)
    # and it must stay under the server's max_connections, or Postgres starts
    # refusing connections outright — an outage, not degradation.
    #
    # Defaults budget for max_connections=100 with celery at --concurrency=4:
    #   api 1 x 15 + celery 4 x 15 + beat 1 x 15 = 90, under the 97 usable.
    # Raise max_connections (or add pgbouncer) before scaling either number.
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)

    # Celery prefork children. Each one holds its own DB pool, so this is a
    # direct multiplier on the connection ceiling above — raise the two
    # together, never one alone.
    CELERY_WORKER_CONCURRENCY: int = Field(default=4, ge=1, le=64)

    # --- File storage ---
    #
    # "local" writes to the uploads/ and media/ directories, which is correct
    # for a single API replica: compose shares those volumes between the api
    # and celery_worker containers, so both see the same files.
    #
    # "s3" is required before running more than one replica. With local
    # storage an upload lands on one replica's disk, the database row points at
    # a path that exists only there, and a download served by another replica
    # is a 404.
    #
    # Defaults to local so nothing changes until the switch is deliberate.
    STORAGE_BACKEND: str = "local"

    # S3-compatible endpoint. MinIO in compose by default; leave empty for real
    # AWS S3, where boto3 resolves the endpoint from the region.
    S3_ENDPOINT_URL: str = "http://minio:9000"
    S3_BUCKET: str = "helpdoctor"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_REGION: str = "us-east-1"

    @field_validator("STORAGE_BACKEND")
    @classmethod
    def validate_storage_backend(cls, v: str) -> str:
        allowed = {"local", "s3"}
        value = v.strip().lower()
        if value not in allowed:
            raise ValueError(
                f"STORAGE_BACKEND must be one of {sorted(allowed)}, got {v!r}"
            )
        return value

    # --- Multi-factor authentication ---
    #
    # Roles for which TOTP is mandatory, as a comma-separated list. Rolled out
    # in descending order of blast radius — widen this as each group enrols:
    #
    #   super_admin  -> admin  -> doctor  -> receptionist
    #
    # super_admin first because it is the platform plane: a handful of accounts
    # that can reach every clinic. receptionist last because it is the largest
    # group and the least privileged, so it costs the most enrolment effort for
    # the least risk reduction.
    #
    # A role listed here does NOT lose the ability to log in without MFA —
    # enrolling requires an authenticated session, so blocking login would lock
    # the account out permanently with no way back. Instead the login response
    # carries mfa_enrollment_required, and privileged endpoints guarded by
    # require_mfa_enrolled refuse until enrolment is finished.
    MFA_REQUIRED_ROLES: str = "super_admin"

    # Comma-separated urlsafe-base64 Fernet keys used to encrypt
    # users.mfa_secret at rest. The FIRST encrypts; ALL are tried when
    # decrypting, which is what allows rotation without downtime.
    #
    # Unset falls back to a key derived from JWT_SECRET_KEY (HKDF, domain
    # separated). That keeps a default deployment working, but couples them:
    # rotating JWT_SECRET_KEY then makes every stored MFA secret
    # undecryptable. Set a dedicated key before you ever rotate it.
    #
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    MFA_SECRET_ENCRYPTION_KEYS: str = ""

    # --- PHI access log retention ---
    #
    # How long a record of "who read which patient's data" is kept before it is
    # purged. Six years is the common healthcare audit-trail baseline (HIPAA
    # §164.316(b)(2) requires six years for security documentation); it is the
    # safe default if this system ever serves patients outside Bangladesh or is
    # put forward for certification.
    #
    # This is a COMPLIANCE control, not a housekeeping knob. Shortening it
    # destroys evidence that a regulator or a patient exercising their right of
    # access may be entitled to, so it has a floor of one year: a typo of `30`
    # would otherwise silently delete almost the entire trail on the next
    # nightly run.
    PHI_ACCESS_LOG_RETENTION_DAYS: int = Field(default=2190, ge=365, le=36500)

    # Rows deleted per statement. Small enough that the table is never locked
    # for long, since clinical reads are writing to it continuously.
    PHI_ACCESS_LOG_PURGE_BATCH_SIZE: int = Field(default=10_000, ge=100, le=100_000)

    # Ceiling on batches per run, so one invocation cannot run unbounded. A
    # backlog is worked off across successive nightly runs instead.
    PHI_ACCESS_LOG_PURGE_MAX_BATCHES: int = Field(default=50, ge=1, le=1000)

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

    @property
    def mfa_required_roles(self) -> set[str]:
        """Roles that must enrol in TOTP, lowercased.

        Lowercased because UserRole values are lowercase in this codebase, and
        a config of "SUPER_ADMIN" silently matching nothing would disable the
        requirement without any error.
        """
        return {
            role.strip().lower()
            for role in self.MFA_REQUIRED_ROLES.split(",")
            if role.strip()
        }

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
    def composed_database_url(self) -> str:
        """The connection string built from the individual POSTGRES_* parts."""
        password = quote_plus(self.POSTGRES_PASSWORD)

        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            f"{password}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url(self) -> str:
        """The database everything talks to.

        DATABASE_URL wins when set, because Alembic already prefers it. Having
        the app disagree is what let migrations and queries reach two different
        databases. One value now decides for both.
        """
        return self.DATABASE_URL or self.composed_database_url

    @model_validator(mode="after")
    def _database_url_must_agree_with_parts(self) -> "Settings":
        """Refuse to start on a contradictory database configuration.

        Both forms have to exist — the postgres container is configured from
        the parts — so the risk is not duplication but disagreement. Changing
        POSTGRES_DB and forgetting the URL, or rotating the password in one
        place only, previously produced no error at all: migrations went one
        way, the application went the other, and nothing said so until the
        schema and the data were already in two different databases.

        Compared field by field rather than as strings, so an equivalent URL
        written differently (percent-encoding, an explicit default port) is not
        reported as a conflict.
        """
        if not self.DATABASE_URL:
            return self

        parsed = urlsplit(self.DATABASE_URL)

        differences = []

        def _compare(label: str, from_url, from_parts) -> None:
            # A part absent from the URL is not a contradiction — the URL is
            # authoritative and may legitimately omit an optional component.
            if from_url in (None, "") or from_url == from_parts:
                return
            differences.append(f"{label}: URL has {from_url!r}, parts have {from_parts!r}")

        _compare("host", parsed.hostname, self.POSTGRES_HOST)
        _compare("port", parsed.port, self.POSTGRES_PORT)
        _compare("database", parsed.path.lstrip("/"), self.POSTGRES_DB)
        _compare("user", unquote(parsed.username or ""), self.POSTGRES_USER)

        # Reported without either value: a mismatch here is usually a half-done
        # credential rotation, and the message goes to logs.
        url_password = unquote(parsed.password or "")

        if url_password and url_password != self.POSTGRES_PASSWORD:
            differences.append(
                "password: the URL and POSTGRES_PASSWORD are different"
            )

        if differences:
            raise ValueError(
                "DATABASE_URL contradicts the POSTGRES_* settings, so "
                "migrations and the application would use different "
                "databases:\n  - "
                + "\n  - ".join(differences)
                + "\nMake them agree, or unset DATABASE_URL to use the parts."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()