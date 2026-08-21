from pathlib import Path

import pytest

from tubeviz.render import RenderConfig, build_ffmpeg_command


def test_render_config_validation():
    RenderConfig().validate()
    with pytest.raises(ValueError):
        RenderConfig(fps=0).validate()
    with pytest.raises(ValueError):
        RenderConfig(frame_format="gif").validate()


def test_ffmpeg_render_command_has_pipe_video_and_original_audio(tmp_path: Path):
    output = tmp_path / "out.mp4"
    audio = tmp_path / "song.flac"
    command = build_ffmpeg_command(
        output=output,
        audio=audio,
        duration=12.5,
        config=RenderConfig(width=1280, height=720, fps=60, crf=17),
    )
    joined = " ".join(command)
    assert "-f image2pipe" in joined
    assert "-framerate 60" in joined
    assert "-vcodec png" in joined
    assert "pipe:0" in command
    assert str(audio) in command
    assert "-map 0:v:0" in joined
    assert "-map 1:a:0" in joined
    assert "-c:v libx264" in joined
    assert "-c:a aac" in joined
    assert str(output) == command[-1]


def test_jpeg_transport_selects_mjpeg(tmp_path: Path):
    command = build_ffmpeg_command(
        output=tmp_path / "out.mp4",
        audio=None,
        duration=1.0,
        config=RenderConfig(frame_format="jpeg"),
    )
    assert "mjpeg" in command
    assert "-c:a" not in command


def test_browser_renderer_exposes_offline_frame_api():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "window.tubevizOfflineInit" in js
    assert "window.tubevizRenderFrame" in js
    assert "const offlineMode=query.get('offline')==='1'" in js
    assert "function clockSeconds()" in js
    assert "function seekOfflineBank" in js
    assert "if(!offlineMode)requestAnimationFrame(frame)" in js
