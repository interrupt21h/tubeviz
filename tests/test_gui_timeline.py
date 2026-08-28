# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path

from fastapi.testclient import TestClient

from tubeviz.gui import create_gui_app


def _timeline_payload():
    return {
        "track": {
            "duration": 12.0,
            "tempo_bpm": 128.0,
            "key": "Am",
            "beats": [0.0, 0.5, 1.0],
            "bars": [0.0, 2.0],
            "sections": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 12.0,
                    "energy": 0.8,
                    "label": "peak",
                    "ai_direction": {
                        "provenance": "llm",
                        "strategy": "accelerate",
                        "director_beats": [{"at": 0.5, "purpose": "hero moment"}],
                    },
                }
            ],
        },
        "scene_plan": [
            {
                "time": 0.0,
                "source_id": "abc",
                "title": "Night city",
                "start": 2.0,
                "end": 6.0,
                "crossfade_seconds": 0.0,
                "transform": {"ripple": 0.5},
                "direction": {"effect_family": "liquid", "vector_effects": [{"kind": "flow_ribbons"}]},
            },
            {
                "time": 6.0,
                "source_id": "def",
                "title": "Crowd",
                "start": 10.0,
                "end": 14.0,
                "crossfade_seconds": 0.75,
                "transform": {},
                "direction": {},
            },
        ],
    }


def test_gui_timeline_api_reads_project_relative_timeline(tmp_path: Path):
    timeline_dir = tmp_path / "timelines"
    timeline_dir.mkdir()
    timeline_path = timeline_dir / "song.json"
    timeline_path.write_text(json.dumps(_timeline_payload()), encoding="utf-8")
    client = TestClient(create_gui_app(project_root=tmp_path, default_library=tmp_path / "library"))

    response = client.get("/api/gui/timeline", params={"timeline": "timelines/song.json"})
    assert response.status_code == 200
    data = response.json()
    assert data["timeline"]["track"]["duration"] == 12.0
    assert data["timeline"]["scene_plan"][1]["crossfade_seconds"] == 0.75
    assert data["path"] == str(timeline_path.resolve())


def test_gui_timeline_api_reports_missing_and_invalid_files(tmp_path: Path):
    client = TestClient(create_gui_app(project_root=tmp_path, default_library=tmp_path / "library"))
    assert client.get("/api/gui/timeline", params={"timeline": "missing.json"}).status_code == 404
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert client.get("/api/gui/timeline", params={"timeline": "bad.json"}).status_code == 400


def test_timeline_workspace_static_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "src/tubeviz/static/gui.html").read_text(encoding="utf-8")
    js = (root / "src/tubeviz/static/gui.js").read_text(encoding="utf-8")
    css = (root / "src/tubeviz/static/gui.css").read_text(encoding="utf-8")
    preview_html = (root / "src/tubeviz/static/index.html").read_text(encoding="utf-8")
    visualizer = (root / "src/tubeviz/static/visualizer.js").read_text(encoding="utf-8")
    screenshots = (root / "scripts/screenshot_studio.py").read_text(encoding="utf-8")

    assert 'data-tab="timeline">Timeline</button>' in html
    assert 'id="timelinePreviewFrame"' in html
    assert 'id="timelineLanes"' in html
    assert 'id="timelineInspector"' in html
    assert 'id="timelineAnalysisDetails"' in html
    assert 'function renderTimelineWorkspace()' in js
    assert 'tubeviz-preview-state' in js
    assert 'AI Director' in js
    assert 'timeline-preview-shell' in css
    assert 'body.studio-embedded #hud' in preview_html
    assert 'tubeviz-preview-command' in visualizer
    assert 'studio_role' in visualizer
    assert '"timeline"' in screenshots
    assert 'prepare_timeline' in screenshots
