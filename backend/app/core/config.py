from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_ENVIRONMENTS = {"dev", "development", "test"}
MIN_SECRET_KEY_LENGTH = 32
PLACEHOLDER_SECRET_KEYS = {
    "replace-me",
    "please-change-this",
    "changeme",
    "targethub-dev-only-change-me",
}


class Settings(BaseSettings):
    """
    TargetHub application configuration.
    Values are loaded from the .env file.
    """

    app_name: str = "TargetHub"
    app_version: str = "0.1.0"
    environment: str = "production"

    host: str = "0.0.0.0"
    port: int = 8000

    log_level: str = "INFO"

    database_url: str = "sqlite:///targethub.db"

    secret_key: str
    targethub_public_url: str = "http://localhost:8000"

    # One-time first-admin bootstrap. Unset/empty disables bootstrap entirely.
    admin_bootstrap_token: str | None = None

    # Bearer token for Prometheus scrapes of /metrics. Admin JWTs are also accepted.
    metrics_token: str | None = None

    # Access tokens are short-lived; the UI renews them with a rotating refresh token.
    access_token_minutes: int = 15
    # PBKDF2-SHA256 work factor for new hashes; older hashes are upgraded at login.
    password_hash_iterations: int = 600_000
    refresh_token_hours: int = 168

    # Failed logins / password changes allowed per client IP + username within the window.
    auth_max_failures: int = 5
    auth_failure_window_seconds: int = 300

    @model_validator(mode="after")
    def reject_weak_secret_key(self) -> "Settings":
        if self.environment.lower() in DEV_ENVIRONMENTS:
            return self
        key = self.secret_key.strip()
        if len(key) < MIN_SECRET_KEY_LENGTH or key.lower() in PLACEHOLDER_SECRET_KEYS:
            raise ValueError(
                f"SECRET_KEY must be a random value of at least {MIN_SECRET_KEY_LENGTH} "
                "characters unless ENVIRONMENT=development"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
