"""install.ps1: syntax and argument validation (runs where PowerShell 7 is available)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_PS1 = Path(__file__).resolve().parents[1] / "app" / "web" / "agent" / "install.ps1"
PWSH = os.environ.get("TARGETHUB_PWSH") or shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell (pwsh) not installed")


def _pwsh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", *args], capture_output=True, text=True, timeout=60)


def test_installer_parses_without_errors():
    script = (
        "$t=$null;$e=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{INSTALL_PS1}',[ref]$t,[ref]$e)|Out-Null;"
        "$e.Count"
    )
    assert _pwsh("-Command", script).stdout.strip() == "0"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["-TargetHubUrl", "https://hub", "-EnrollmentToken", "t", "-AgentSha256", "abc"], "64-character"),
        (["-TargetHubUrl", "http://hub", "-EnrollmentToken", "t", "-AgentSha256", "a" * 64], "plain http"),
        (["-TargetHubUrl", "ftp://hub", "-EnrollmentToken", "t", "-AgentSha256", "a" * 64], "must start with https"),
    ],
)
def test_installer_rejects_bad_arguments(args, message):
    result = _pwsh("-File", str(INSTALL_PS1), *args)
    assert result.returncode != 0
    assert message in (result.stdout + result.stderr)


def test_enrollment_returns_parseable_windows_command(tmp_path, monkeypatch):
    from tests.helpers import api_client, auth, bootstrap

    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        enrollment = client.post("/api/v1/agents/enrollments", json={"agent_name": "win-host"}, headers=auth(admin)).json()
    command = enrollment["install_command_windows"].replace("'", "''")
    script = f"$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseInput('{command}',[ref]$t,[ref]$e)|Out-Null;$e.Count"
    assert _pwsh("-Command", script).stdout.strip() == "0"
    assert "-AllowInsecureHttp" in enrollment["install_command_windows"]  # test hub URL is http://
