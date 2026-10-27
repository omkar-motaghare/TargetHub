"""Server installers (scripts/install.sh and scripts/install.ps1) against a fake docker CLI.

The fake records every invocation so the tests check the generated .env and the compose
commands without a Docker daemon. The PowerShell variant runs when TARGETHUB_PWSH points at
pwsh (or pwsh is on PATH).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PWSH = os.environ.get("TARGETHUB_PWSH") or shutil.which("pwsh")

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
exit 0
"""
FAKE_DOCKER_CMD = "@echo off\r\necho %*>>\"%DOCKER_LOG%\"\r\nexit /b 0\r\n"
WINDOWS = sys.platform == "win32"
posix_only = pytest.mark.skipif(WINDOWS, reason="bash installer targets Linux/macOS hosts")


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("install.sh", "install.ps1"):
        shutil.copy(REPO / "scripts" / name, repo / "scripts" / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if WINDOWS:
        (bin_dir / "docker.cmd").write_text(FAKE_DOCKER_CMD, newline="")
    else:
        docker = bin_dir / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "docker.log"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "DOCKER_LOG": str(log)}
    return repo, env, log


def read_env(repo: Path) -> dict[str, str]:
    values = {}
    for line in (repo / ".env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


def run_sh(repo, env, *args):
    return subprocess.run(["bash", str(repo / "scripts" / "install.sh"), *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=60)


def run_ps(repo, env, *args):
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(repo / "scripts" / "install.ps1"), *args],
                          cwd=repo, env=env, capture_output=True, text=True, timeout=120)


def check_generated(values: dict[str, str], port: str):
    assert values["TARGETHUB_PORT"] == port
    assert len(values["SECRET_KEY"]) == 64 and int(values["SECRET_KEY"], 16) >= 0
    assert len(values["POSTGRES_PASSWORD"]) == 48
    assert len(values["ADMIN_BOOTSTRAP_TOKEN"]) == 32
    assert values["METRICS_TOKEN"]


@posix_only
def test_install_sh_writes_env_and_reuses_it(sandbox):
    repo, env, log = sandbox
    result = run_sh(repo, env, "--port", "18080", "--project", "lab1", "--url", "http://hub:18080", "--no-start")
    assert result.returncode == 0, result.stderr
    values = read_env(repo)
    check_generated(values, "18080")
    assert values["COMPOSE_PROJECT_NAME"] == "lab1" and values["TARGETHUB_PUBLIC_URL"] == "http://hub:18080"
    assert stat.S_IMODE((repo / ".env").stat().st_mode) == 0o600

    secret = values["SECRET_KEY"]
    result = run_sh(repo, env, "--image", "ghcr.io/x/targethub:0.2.0", "--no-start")
    assert result.returncode == 0, result.stderr
    values = read_env(repo)
    assert values["SECRET_KEY"] == secret, "reuse must keep secrets"
    assert values["TARGETHUB_IMAGE"] == "ghcr.io/x/targethub:0.2.0"


@posix_only
def test_install_sh_pulls_published_image_instead_of_building(sandbox):
    repo, env, log = sandbox
    result = run_sh(repo, env, "--image", "ghcr.io/x/targethub:0.2.0")
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert "compose pull" in calls
    assert any(c.startswith("compose up -d --no-build --wait") for c in calls)
    assert not any("--build" in c and "--no-build" not in c for c in calls)


@posix_only
def test_install_sh_builds_from_source_by_default(sandbox):
    repo, env, log = sandbox
    assert run_sh(repo, env).returncode == 0
    assert any(c.startswith("compose up -d --build --wait") for c in log.read_text().splitlines())


@posix_only
def test_install_sh_rejects_bad_arguments(sandbox):
    repo, env, _ = sandbox
    assert run_sh(repo, env, "--port", "99999", "--no-start").returncode != 0
    assert run_sh(repo, env, "--project", "Bad Name", "--no-start").returncode != 0
    assert not (repo / ".env").exists()


@pytest.mark.skipif(PWSH is None, reason="pwsh not available (set TARGETHUB_PWSH)")
def test_install_ps1_writes_env_and_reuses_it(sandbox):
    repo, env, log = sandbox
    result = run_ps(repo, env, "-Port", "18081", "-Project", "lab2", "-Url", "http://hub:18081", "-NoStart")
    assert result.returncode == 0, result.stdout + result.stderr
    raw = (repo / ".env").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
    values = read_env(repo)
    check_generated(values, "18081")
    assert values["COMPOSE_PROJECT_NAME"] == "lab2"

    secret = values["SECRET_KEY"]
    result = run_ps(repo, env, "-Image", "ghcr.io/x/targethub:0.2.0")
    assert result.returncode == 0, result.stdout + result.stderr
    values = read_env(repo)
    assert values["SECRET_KEY"] == secret and values["TARGETHUB_IMAGE"] == "ghcr.io/x/targethub:0.2.0"
    calls = [line.strip() for line in log.read_text().splitlines()]
    assert "compose pull" in calls and any(c.startswith("compose up -d --no-build --wait") for c in calls)


@pytest.mark.skipif(PWSH is None, reason="pwsh not available (set TARGETHUB_PWSH)")
def test_install_ps1_rejects_bad_project(sandbox):
    repo, env, _ = sandbox
    assert run_ps(repo, env, "-Project", "Bad Name", "-NoStart").returncode != 0
    assert not (repo / ".env").exists()
