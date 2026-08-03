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

    secret_key: str

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
