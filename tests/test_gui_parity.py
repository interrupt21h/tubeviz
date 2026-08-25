# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tubeviz.gui import JobRequest, _job_command, cli_schema, create_gui_app


def test_gui_cli_schema_covers_every_current_non_gui_leaf_command():
    names = {item["name"] for item in cli_schema()["commands"]}
    assert names == {
        "analyze",
        "audio-ai doctor",
        "audio-ai inspect",
        "codec doctor",
        "codec inspect",
        "codec materialize",
        "choreography inspect",
        "ingest",
        "ingest-url",
        "library ai-report",
        "library codec-motion-index",
        "library delete",
        "library embed",
        "library list",
        "library reject",
        "library restore",
        "library show",
        "library stats",
        "library visual-index",
        "materialize",
        "music-ai doctor",
        "native build",
        "native doctor",
        "render",
        "serve",
    }


def test_gui_cli_schema_exposes_representative_advanced_flags():
    commands = {item["name"]: item for item in cli_schema()["commands"]}
    analyze = {flag for arg in commands["analyze"]["arguments"] for flag in arg["flags"]}
    render = {flag for arg in commands["render"]["arguments"] for flag in arg["flags"]}
    ingest = {flag for arg in commands["ingest"]["arguments"] for flag in arg["flags"]}
    serve = {flag for arg in commands["serve"]["arguments"] for flag in arg["flags"]}
    manual = {flag for arg in commands["ingest-url"]["arguments"] for flag in arg["flags"]}

    assert {"--audio-ai-temperature", "--ai-director-timeout", "--tempo-change-bpm", "--codec-glitch-intensity"} <= analyze
    assert {"--native-keep-manifest", "--frame-format", "--codec-force", "--browser-channel"} <= render
    assert {"--ai-negative-concepts", "--ai-llm-base-url", "--preferred-max-duration", "--verbose-ytdlp"} <= ingest
    assert {"--replan-scenes", "--replan-transforms", "--codec-materialize", "--source-excerpt-max-seconds"} <= serve
    assert {"--no-visual-index", "--cookies-from-browser", "--fragment-retries", "--scene-threshold"} <= manual


def test_gui_generic_cli_job_is_argument_vector_and_validated():
    command = _job_command(JobRequest(
        kind="cli",
        options={"argv": [
            "analyze", "audio/song.mp3",
            "--library", "./library",
            "--audio-ai",
            "--audio-ai-temperature", "0.08",
            "--codec-glitch", "musical",
            "--no-vector-effects",
        ]},
    ))
    assert command[:3][-2:] == ["-m", "tubeviz.cli"]
    assert command[3:] == [
        "analyze", "audio/song.mp3",
        "--library", "./library",
        "--audio-ai",
        "--audio-ai-temperature", "0.08",
        "--codec-glitch", "musical",
        "--no-vector-effects",
    ]


def test_gui_generic_cli_rejects_unknown_or_recursive_gui_command():
    with pytest.raises(ValueError):
        _job_command(JobRequest(kind="cli", options={"argv": ["not-a-command"]}))
    with pytest.raises(ValueError):
        _job_command(JobRequest(kind="cli", options={"argv": ["gui"]}))


def test_gui_manual_url_ingest_exposes_complete_specialized_workflow():
    command = _job_command(JobRequest(
        kind="ingest-url",
        library="./library",
        urls=["https://youtu.be/a", "https://www.youtube.com/watch?v=b"],
        options={
            "term": "hand-picked",
            "min_duration": 1.25,
            "hard_max_duration": 900,
            "min_width": 640,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "scene_threshold": .35,
            "min_scene_seconds": 1.0,
            "keep_audio": True,
            "no_scenes": False,
            "no_visual_index": True,
            "force": True,
            "cookies_from_browser": "chrome",
            "download_socket_timeout": 25,
            "concurrent_fragments": 8,
            "download_retries": 3,
            "fragment_retries": 4,
            "verbose_ytdlp": True,
        },
    ))
    joined = " ".join(command)
    assert "ingest-url https://youtu.be/a https://www.youtube.com/watch?v=b" in joined
    for expected in [
        "--term hand-picked", "--min-duration 1.25", "--hard-max-duration 900",
        "--min-width 640", "--width 1920", "--height 1080", "--fps 30",
        "--scene-threshold 0.35", "--min-scene-seconds 1.0", "--keep-audio",
        "--no-visual-index", "--force", "--cookies-from-browser chrome",
        "--download-socket-timeout 25", "--concurrent-fragments 8",
        "--download-retries 3", "--fragment-retries 4", "--verbose-ytdlp",
    ]:
        assert expected in joined


def test_gui_schema_endpoint_and_command_center_markup(tmp_path: Path):
    app = create_gui_app(default_library=tmp_path / "library", project_root=tmp_path)
    client = TestClient(app)
    response = client.get("/api/gui/cli-schema")
    assert response.status_code == 200
    assert any(item["name"] == "ingest-url" for item in response.json()["commands"])
    html = client.get("/").text
    assert 'data-tab="command"' in html
    assert 'id="manualIngestBtn"' in html
    assert 'id="cliArguments"' in html
    assert 'id="runCliCommand"' in html
