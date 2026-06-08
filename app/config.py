from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote_plus


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "HelpDoctor"
    ENV: str = Field(default="development", pattern="^(development|staging|production)$")
    DEBUG: bool = False


    # PostgreSQL
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str


    REDIS_URL: str = "redis://localhost:6379/0"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # Elasticsearch
    ELASTIC_HOST: str = "http://localhost:9200"

    # Google OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    BKASH_BASE_URL: str
    BKASH_APP_KEY: str
    BKASH_APP_SECRET: str
    BKASH_USERNAME: str
    BKASH_PASSWORD: str
    BKASH_CALLBACK_URL: str

    NAGAD_BASE_URL: str
    NAGAD_MERCHANT_ID: str
    NAGAD_PUBLIC_KEY: str
    NAGAD_PRIVATE_KEY: str
    NAGAD_CALLBACK_URL: str

    # ROCKET
    ROCKET_BASE_URL: str
    ROCKET_MERCHANT_ID: str
    ROCKET_API_KEY: str
    ROCKET_CALLBACK_URL: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid"
    )

    # JWT
    JWT_SECRET_KEY : str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # VAPID
    VAPID_PUBLIC_KEY: str | None = None
    VAPID_PRIVATE_KEY: str | None = None
    VAPID_EMAIL: str | None = None

    #QR
    BASE_URL: str

    #Email
    MAIL_HOST: str
    MAIL_PORT: int = 587

    MAIL_USERNAME: str
    MAIL_PASSWORD: str

    MAIL_FROM: str

    MAIL_USE_TLS: bool = True

    ENABLE_MEDICINE_AI: bool = False

    AI_PROVIDER: str = "openai"

    OPENAI_API_KEY: str | None = None

    OPENAI_MODEL: str = "gpt-4.1-mini"
    
    
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