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


class FakeS3:
    """In-memory stand-in for the boto3 S3 client calls TargetHub uses."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, path, bucket, key):
        with open(path, "rb") as handle:
            self.objects[(bucket, key)] = handle.read()

    def head_object(self, Bucket, Key):  # noqa: N803 - boto3 signature
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(self, operation, Params, ExpiresIn):  # noqa: N803
        return f"https://s3.example.test/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


def _use_s3(monkeypatch, tmp_path):
    fake = FakeS3()
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "artifact_storage", "s3")
    monkeypatch.setattr(settings, "artifact_s3_bucket", "fw-bucket")
    monkeypatch.setattr(settings, "artifact_s3_prefix", "lab/")
    monkeypatch.setattr("app.services.artifact_service._s3_client", lambda: fake)
    return fake


def test_s3_upload_goes_to_the_bucket_and_download_redirects(tmp_path, monkeypatch):
    fake = _use_s3(monkeypatch, tmp_path)
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        alice = create_user(client, bootstrap(client), "alice")
        body = _upload(client, alice).json()
        assert body["sha256"] == hashlib.sha256(FIRMWARE).hexdigest()
        key = ("fw-bucket", f"lab/{body['id'][:2]}/{body['id']}")
        assert fake.objects[key] == FIRMWARE
        assert not [p for p in (tmp_path / "store").rglob("*") if p.is_file()]  # nothing left on local disk

        with session_local() as db:
            service = ArtifactService(db)
            path = service.signed_url(service.get(body["id"])).replace(settings.targethub_public_url, "")
        redirect = client.get(path, follow_redirects=False)
        assert redirect.status_code == 302
        assert redirect.headers["location"].startswith(f"https://s3.example.test/fw-bucket/lab/{body['id'][:2]}/")
        # The signature check still guards the redirect.
        assert client.get(path.replace("signature=", "signature=0"), follow_redirects=False).status_code == 403

        assert client.delete(f"/api/v1/artifacts/{body['id']}", headers=auth(alice)).status_code == 204
        assert key not in fake.objects


def test_s3_failure_leaves_no_row_and_no_local_file(tmp_path, monkeypatch):
    fake = _use_s3(monkeypatch, tmp_path)

    def boom(*_args):
        raise RuntimeError("bucket unreachable")

    monkeypatch.setattr(fake, "upload_file", boom)
    with api_client(tmp_path, monkeypatch) as (client, _db):
        alice = create_user(client, bootstrap(client), "alice")
        try:
            response = _upload(client, alice)
            assert response.status_code >= 500
        except RuntimeError:
            pass  # TestClient re-raises server errors
        assert client.get("/api/v1/artifacts", headers=auth(alice)).json() == []
        assert not [p for p in (tmp_path / "store").rglob("*") if p.is_file()]


def test_artifacts_written_before_switching_to_s3_still_download_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "store"))
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        alice = create_user(client, bootstrap(client), "alice")
        old = _upload(client, alice).json()
        _use_s3(monkeypatch, tmp_path)
        with session_local() as db:
            service = ArtifactService(db)
            path = service.signed_url(service.get(old["id"])).replace(settings.targethub_public_url, "")
        served = client.get(path, follow_redirects=False)
        assert served.status_code == 200 and served.content == FIRMWARE


def test_s3_storage_needs_a_bucket():
    import pytest

    from app.core.config import Settings

    with pytest.raises(ValueError, match="ARTIFACT_S3_BUCKET"):
        Settings(secret_key="x", environment="development", artifact_storage="s3", artifact_s3_bucket="")
    with pytest.raises(ValueError, match="ARTIFACT_STORAGE"):
        Settings(secret_key="x", environment="development", artifact_storage="ftp")
