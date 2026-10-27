"""Static web routes: SPA entry, agent downloads, and the removed legacy dashboard."""

from fastapi.testclient import TestClient

import app.main as main


def test_agent_files_are_served():
    client = TestClient(main.app)
    for name in ("install.sh", "install.ps1", "targethub_agent.py"):
        response = client.get(f"/web/agent/{name}")
        assert response.status_code == 200, name
        assert response.content


def test_legacy_dashboard_is_gone_and_dashboard_redirects():
    client = TestClient(main.app)
    assert client.get("/legacy-dashboard").status_code == 404
    assert client.get("/web/app.js").status_code == 404
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 307 and response.headers["location"] == "/app"


def test_spa_routes_serve_index_or_build_hint(tmp_path, monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main, "REACT_DIR", tmp_path / "missing")
    response = client.get("/app/targets")
    assert response.status_code == 503 and "npm run build" in response.text

    (tmp_path / "react").mkdir()
    (tmp_path / "react" / "index.html").write_text("<div id=root></div>")
    monkeypatch.setattr(main, "REACT_DIR", tmp_path / "react")
    response = client.get("/app/sessions/42")
    assert response.status_code == 200 and "root" in response.text
    assert response.headers["cache-control"] == "no-cache"
