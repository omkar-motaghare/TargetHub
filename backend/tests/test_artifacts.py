"""Uploaded firmware artifacts: storage, permissions, signed downloads and deploy by id."""

from __future__ import annotations

import hashlib
import io
import time

from app.core.config import settings
from app.services.artifact_service import ArtifactService
from tests.helpers import (
    FakeAgent,
    agent_target,
    api_client,
    auth,
    bootstrap,
    create_user,
    enroll_agent,
    heartbeat,
    open_session,
    reserve,
)

FIRMWARE = b"\x7fELF-firmware-image" * 100
DEPLOY = {"resource_key": "deploy:flash", "resource_type": "deploy", "display_name": "flash", "metadata": {}}


def _upload(client, token, data=FIRMWARE, name="fw v1.bin", description=None):
    return client.post(
        "/api/v1/artifacts",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
        data={"description": description} if description else None,
        headers=auth(token),
    )


def test_upload_stores_file_with_checksum_and_sanitised_name(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "store"))
    with api_client(tmp_path, monkeypatch) as (client, _db):
        alice = create_user(client, bootstrap(client), "alice")
        response = _upload(client, alice, name="../../etc/fw v1.bin", description="release candidate")
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["sha256"] == hashlib.sha256(FIRMWARE).hexdigest()
        assert body["size_bytes"] == len(FIRMWARE)
        assert body["name"] == "fw_v1.bin"
        assert body["uploaded_by"] == "alice"
        stored = list((tmp_path / "store").rglob(body["id"]))
        assert len(stored) == 1 and stored[0].read_bytes() == FIRMWARE


def test_upload_rejects_empty_and_oversized_and_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "artifact_max_bytes", 1000)
    with api_client(tmp_path, monkeypatch) as (client, _db):
        alice = create_user(client, bootstrap(client), "alice")
        assert _upload(client, alice, data=b"").status_code == 422
        assert _upload(client, alice, data=b"x" * 1001).status_code == 413
        assert [p for p in (tmp_path / "store").rglob("*") if p.is_file()] == []
        assert client.get("/api/v1/artifacts", headers=auth(alice)).json() == []


def test_viewer_cannot_upload_and_sees_no_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "store"))
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        viewer = create_user(client, admin, "vera", roles=["viewer"])
        assert _upload(client, viewer).status_code == 403
        assert _upload(client, alice).status_code == 201
        assert client.get("/api/v1/artifacts", headers=auth(viewer)).json() == []
        assert len(client.get("/api/v1/artifacts", headers=auth(alice)).json()) == 1


def test_only_owner_or_admin_can_delete_and_file_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "store"))
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        bob = create_user(client, admin, "bob")
        artifact = _upload(client, alice).json()
        assert client.delete(f"/api/v1/artifacts/{artifact['id']}", headers=auth(bob)).status_code == 403
        assert client.delete(f"/api/v1/artifacts/{artifact['id']}", headers=auth(alice)).status_code == 204
        assert [p for p in (tmp_path / "store").rglob("*") if p.is_file()] == []
        assert client.get(f"/api/v1/artifacts/{artifact['id']}", headers=auth(alice)).status_code == 404
        other = _upload(client, alice).json()
        assert client.delete(f"/api/v1/artifacts/{other['id']}", headers=auth(admin)).status_code == 204


def test_signed_download_works_without_login_and_rejects_tampering_and_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "store"))
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        alice = create_user(client, bootstrap(client), "alice")
        artifact = _upload(client, alice).json()
        with session_local() as db:
            service = ArtifactService(db)
            url = service.signed_url(service.get(artifact["id"]))
        path = url.replace(settings.targethub_public_url, "")
        ok = client.get(path)
        assert ok.status_code == 200 and ok.content == FIRMWARE

        assert client.get(path.replace("signature=", "signature=0")).status_code == 403
        assert client.get(f"/api/v1/artifacts/{artifact['id']}/download").status_code == 422
        other = _upload(client, alice, data=b"other-image").json()
        swapped = path.replace(artifact["id"], other["id"])
        assert client.get(swapped).status_code == 403  # signature is bound to the artifact id

        expired = int(time.time()) - 5
        signature = ArtifactService._signature(artifact["id"], expired)
        late = client.get(f"/api/v1/artifacts/{artifact['id']}/download?expires={expired}&signature={signature}")
        assert late.status_code == 403


def test_deploy_by_artifact_id_hands_the_agent_a_signed_url_and_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "store"))
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        agent_id, credential = enroll_agent(client, admin)
        ids = heartbeat(client, agent_id, credential, [DEPLOY])
        target = agent_target(
            client,
            admin,
            "BOARD-FLASH",
            [{"name": "Flash", "capability_type": "deploy", "agent_id": agent_id, "resource_id": ids["deploy:flash"]}],
        )
        reservation = reserve(client, alice, target["id"])
        session = open_session(client, alice, reservation["id"], "deploy")
        artifact = _upload(client, alice).json()

        def answer(operation: dict) -> dict:
            return {"success": True, "message": "flashed", "data": {"status": "ok"}}

        with FakeAgent(client, agent_id, credential, answer) as agent:
            result = client.post(
                f"/api/v1/sessions/{session['id']}/execute",
                json={"operation": "deploy", "params": {"artifact_id": artifact["id"]}},
                headers=auth(alice),
            )
            assert result.status_code == 200, result.text
            params = agent.seen[0]["params"]
        assert params["sha256"] == artifact["sha256"]
        assert params["url"].startswith(settings.targethub_public_url)
        assert f"/artifacts/{artifact['id']}/download?expires=" in params["url"]
        assert "artifact_id" not in params

        missing = client.post(
            f"/api/v1/sessions/{session['id']}/execute",
            json={"operation": "deploy", "params": {"artifact_id": "does-not-exist"}},
            headers=auth(alice),
        )
        assert missing.status_code == 404
