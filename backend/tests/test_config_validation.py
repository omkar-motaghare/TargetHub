import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize("key", ["", "short", "replace-me", "targethub-dev-only-change-me"])
def test_weak_secret_rejected_in_production(key):
    with pytest.raises(ValidationError):
        make(secret_key=key, environment="production")


def test_default_environment_is_production(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(ValidationError):
        make(secret_key="short")


def test_strong_secret_accepted_in_production():
    assert make(secret_key="a" * 40, environment="production").secret_key == "a" * 40


def test_weak_secret_allowed_in_development():
    assert make(secret_key="x", environment="development").secret_key == "x"
