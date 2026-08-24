# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from fastapi.testclient import TestClient
import tubeviz.gui as gui
from tubeviz.gui import GuiJob, create_gui_app


def test_gui_config_reports_hf_token_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "secret-from-env")
    client = TestClient(create_gui_app(default_library=tmp_path / "library", project_root=tmp_path))
    data = client.get("/api/gui/config").json()
    assert data["huggingface"]["token_from_env"] is True
    assert "secret-from-env" not in str(data)


def test_gui_token_is_process_environment_not_argv_or_metadata(tmp_path: Path, monkeypatch):
    captured = {}
    def fake_create(self, kind, command, *, metadata=None, env_overrides=None):
        captured.update(command=command, metadata=metadata or {}, env=env_overrides or {})
        job = GuiJob(id="hf-test", kind=kind, command=command, metadata=dict(metadata or {}))
        self._jobs[job.id] = job
        return job
    monkeypatch.setattr(gui.JobManager, "create", fake_create)
    client = TestClient(create_gui_app(default_library=tmp_path / "library", project_root=tmp_path))
    response = client.post("/api/gui/jobs", json={
        "kind":"audio-ai-doctor", "library":str(tmp_path / "library"),
        "hf_token":"hf_super_secret", "options":{}
    })
    assert response.status_code == 200
    assert captured["env"]["HF_TOKEN"] == "hf_super_secret"
    assert captured["env"]["HUGGING_FACE_HUB_TOKEN"] == "hf_super_secret"
    assert "hf_super_secret" not in " ".join(captured["command"])
    assert "hf_super_secret" not in str(captured["metadata"])
    assert "hf_super_secret" not in response.text

def test_studio_static_assets_disable_cache():
    from fastapi.testclient import TestClient
    from tubeviz.gui import create_gui_app
    client = TestClient(create_gui_app(default_library="./library", project_root="."))
    root = client.get("/")
    css = client.get("/static/gui.css?v=0.26.10")
    assert "no-store" in root.headers.get("cache-control", "")
    assert "no-store" in css.headers.get("cache-control", "")
    assert client.get("/api/gui/config").json()["studio_version"] == "0.26.10"
