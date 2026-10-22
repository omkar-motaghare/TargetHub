from app.core import logging as logging_module


def test_default_enqueue_disabled_under_pytest(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test-id")
    assert logging_module._default_enqueue() is False


def test_default_enqueue_enabled_without_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert logging_module._default_enqueue() is True


def test_env_bool_parsing(monkeypatch):
    monkeypatch.setenv("TARGETHUB_LOG_ENQUEUE", "false")
    assert logging_module._env_bool("TARGETHUB_LOG_ENQUEUE", True) is False

    monkeypatch.setenv("TARGETHUB_LOG_ENQUEUE", "1")
    assert logging_module._env_bool("TARGETHUB_LOG_ENQUEUE", False) is True

    monkeypatch.delenv("TARGETHUB_LOG_ENQUEUE", raising=False)
    assert logging_module._env_bool("TARGETHUB_LOG_ENQUEUE", True) is True
