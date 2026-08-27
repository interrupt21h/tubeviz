# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from tubeviz.render import RenderConfig, build_ffmpeg_command, build_webcodecs_mux_command


def test_render_config_validation():
    RenderConfig().validate()
    with pytest.raises(ValueError):
        RenderConfig(fps=0).validate()
    with pytest.raises(ValueError):
        RenderConfig(frame_format="gif").validate()


def test_ffmpeg_raw_fallback_has_pipe_video_and_original_audio(tmp_path: Path):
    output = tmp_path / "out.mp4"
    audio = tmp_path / "song.flac"
    command = build_ffmpeg_command(
        output=output,
        audio=audio,
        duration=12.5,
        config=RenderConfig(width=1280, height=720, fps=60, crf=17),
    )
    joined = " ".join(command)
    assert "-f rawvideo" in joined
    assert "-pixel_format rgba" in joined
    assert "-video_size 1280x720" in joined
    assert "-framerate 60" in joined
    assert "image2pipe" not in joined and "mjpeg" not in joined and "png" not in joined
    assert "pipe:0" in command
    assert str(audio) in command
    assert "-map 0:v:0" in joined
    assert "-map 1:a:0" in joined
    assert "-c:v libx264" in joined
    assert "-c:a aac" in joined
    assert str(output) == command[-1]


def test_legacy_frame_format_no_longer_changes_raw_fallback(tmp_path: Path):
    command = build_ffmpeg_command(
        output=tmp_path / "out.mp4",
        audio=None,
        duration=1.0,
        config=RenderConfig(frame_format="jpeg"),
    )
    joined = " ".join(command)
    assert "-f rawvideo" in joined and "-pixel_format rgba" in joined
    assert "mjpeg" not in command and "image2pipe" not in joined
    assert "-c:a" not in command


def test_browser_renderer_exposes_offline_frame_api():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "window.tubevizOfflineInit" in js
    assert "window.tubevizRenderFrame" in js
    assert "const offlineMode=query.get('offline')==='1'" in js
    assert "function clockSeconds()" in js
    assert "function seekOfflineBank" in js
    assert "if(!offlineMode)scheduleLiveFrame()" in js
    assert "window.tubevizRenderOfflineSequence" in js


def test_webcodecs_mux_command_copies_browser_h264(tmp_path: Path):
    output = tmp_path / "out.mp4"
    audio = tmp_path / "song.flac"
    command = build_webcodecs_mux_command(
        output=output, audio=audio, duration=12.5, config=RenderConfig(fps=30)
    )
    joined = " ".join(command)
    assert "-f h264" in joined
    assert "-c:v copy" in joined
    assert "image2pipe" not in joined
    assert str(audio) in command


def test_browser_render_config_validates_new_acceleration_controls():
    RenderConfig(browser_transport="webcodecs", browser_gpu="webgpu").validate()
    RenderConfig(browser_transport="raw").validate()
    RenderConfig(browser_transport="frames").validate()  # legacy alias
    with pytest.raises(ValueError):
        RenderConfig(browser_transport="bogus").validate()
    with pytest.raises(ValueError):
        RenderConfig(browser_gpu="cuda").validate()
