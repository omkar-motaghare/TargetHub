from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    TargetHub application configuration.
    Values are loaded from the .env file.
    """

    app_name: str = "TargetHub"
    app_version: str = "0.1.0"
    environment: str = "development"

    host: str = "0.0.0.0"
    port: int = 8000

    log_level: str = "INFO"

    database_url: str = "sqlite:///targethub.db"

    # Redis (cache + broker for Celery)
    redis_url: str = "redis://redis:6379/0"

    # Celery broker (alias of redis_url by default)
    broker_url: str | None = None

    # MinIO / S3-compatible object storage (optional)
    minio_endpoint: str = "minio:9000"
    minio_access_key: str | None = None
    minio_secret_key: str | None = None

    secret_key: str
    targethub_public_url: str = "http://localhost:8000"

    # One-time first-admin bootstrap. Unset/empty disables bootstrap entirely.
    admin_bootstrap_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
