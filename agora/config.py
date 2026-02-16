"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the Agora API."""

    app_name: str = "Agora"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://agora:password@localhost:5432/agora"
    health_check_interval: int = 3600
    monthly_budget_cents: int | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings so env parsing only happens once."""

    return Settings()
