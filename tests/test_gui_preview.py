# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from fastapi.testclient import TestClient

import tubeviz.gui as gui
from tubeviz.gui import GuiJob, JobRequest, _free_tcp_port, _job_command, create_gui_app


def test_preview_command_uses_requested_current_paths_and_port():
    command = _job_command(JobRequest(
        kind="preview",
        library="/tmp/current-library",
        audio="audio/current.mp3",
        timeline="timelines/current.json",
        options={"host": "127.0.0.1", "port": 45678},
    ))
    joined = " ".join(command)
    assert "serve timelines/current.json" in joined
    assert "--audio audio/current.mp3" in joined
    assert "--library /tmp/current-library" in joined
    assert "--port 45678" in joined


def test_free_preview_port_is_bindable():
    port = _free_tcp_port("127.0.0.1")
    assert 0 < port < 65536


def test_preview_api_allocates_fresh_port_and_returns_selected_identity(tmp_path: Path, monkeypatch):
    captured = []

    def fake_create(self, kind, command, *, metadata=None):
        job = GuiJob(id="preview-test", kind=kind, command=command, metadata=dict(metadata or {}))
        job.status = "running"
        self._jobs[job.id] = job
        captured.append(job)
        return job

    monkeypatch.setattr(gui.JobManager, "create", fake_create)
    monkeypatch.setattr(gui.JobManager, "cancel_kind", lambda self, kind: [])
    monkeypatch.setattr(gui, "_free_tcp_port", lambda host="127.0.0.1": 49321)

    app = create_gui_app(default_library=tmp_path / "library", project_root=tmp_path)
    client = TestClient(app)
    response = client.post("/api/gui/jobs", json={
        "kind": "preview",
        "library": str(tmp_path / "library2"),
        "audio": "audio/new.mp3",
        "timeline": "timelines/new.json",
        "options": {"host": "127.0.0.1", "port": 0},
    })
    assert response.status_code == 200
    data = response.json()
    assert data["preview_url"] == "http://127.0.0.1:49321/"
    assert data["preview_timeline"] == "timelines/new.json"
    assert data["preview_audio"] == "audio/new.mp3"
    joined = " ".join(captured[0].command)
    assert "serve timelines/new.json" in joined
    assert "--port 49321" in joined


def test_gui_javascript_does_not_use_fixed_8080_preview():
    javascript = Path("src/tubeviz/static/gui.js").read_text()
    assert 'options:{port:0,host:"127.0.0.1",codec_materialize:checked("codecPreviewMaterialize")}' in javascript
    assert 'preview.location="http://127.0.0.1:8080/"' not in javascript
    assert "waitForPreview" in javascript


def test_gui_job_manager_uses_project_root_for_subprocesses(tmp_path: Path):
    manager = gui.JobManager(cwd=tmp_path)
    assert manager._cwd == tmp_path.resolve()
