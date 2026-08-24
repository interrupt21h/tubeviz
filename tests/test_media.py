# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

import tubeviz.media as media_module
from tubeviz.media import _parse_ratio, detect_scene_boundaries, make_thumbnail, normalize_video, probe


def test_parse_ratio():
    assert _parse_ratio("30000/1001") == pytest.approx(29.97002997)
    assert _parse_ratio("25/1") == 25.0
    assert _parse_ratio("0/0") is None


def test_make_thumbnail_accepts_time_seconds_keyword(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    destination = tmp_path / "thumb.jpg"
    source.touch()
    commands = []

    def fake_run_checked(command):
        commands.append(command)
        return None

    monkeypatch.setattr(media_module, "run_checked", fake_run_checked)
    make_thumbnail(source, destination, time_seconds=12.3456, width=640)

    assert destination.parent.exists()
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("-ss") + 1] == "12.346"
    assert command[command.index("-vf") + 1] == "scale=640:-2"
    assert command[-1] == str(destination)
