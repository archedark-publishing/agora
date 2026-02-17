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
    database_echo_sql: bool = False
    max_request_body_bytes: int = 1_048_576
    health_check_interval: int = 3600
    recovery_challenge_ttl_seconds: int = 900
    outbound_http_timeout_seconds: int = 10
    registry_refresh_interval: int = 3600
    admin_api_token: str | None = None
    allow_private_network_targets: bool = False
    allow_unresolvable_registration_hostnames: bool = False
    metrics_max_entries: int = 2048
    rate_limit_backend: str = "auto"
    redis_url: str | None = None
    rate_limit_prefix: str = "agora:rate_limit"
    registration_rate_limit_per_ip: int = 10
    registration_rate_limit_per_api_key: int = 10
    registration_rate_limit_global: int = 200
    list_agents_rate_limit_per_ip: int = 100
    list_agents_rate_limit_per_api_key: int = 1000
    list_agents_rate_limit_global: int = 5000
    admin_rate_limit_per_ip: int = 30
    admin_rate_limit_global: int = 300
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
