# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

import tubeviz.media as media_module
from tubeviz.media import _parse_ratio, detect_scene_boundaries, make_thumbnail, normalize_video, prepare_preview_proxy, probe


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


def test_browser_compatible_common_youtube_formats():
    from tubeviz.media import MediaInfo, is_browser_compatible

    h264 = MediaInfo(10.0, 1920, 1080, 30.0, codec_name="h264", pixel_format="yuv420p", format_name="mov,mp4,m4a,3gp,3g2,mj2")
    vp9 = MediaInfo(10.0, 1920, 1080, 60.0, codec_name="vp9", pixel_format="yuv420p", format_name="matroska,webm")
    av1 = MediaInfo(10.0, 1920, 1080, 30.0, codec_name="av1", pixel_format="yuv420p10le", format_name="mov,mp4,m4a,3gp,3g2,mj2")
    hevc = MediaInfo(10.0, 1920, 1080, 30.0, codec_name="hevc", pixel_format="yuv420p", format_name="mov,mp4,m4a,3gp,3g2,mj2")

    assert is_browser_compatible(h264)[0] is True
    assert is_browser_compatible(vp9)[0] is True
    assert is_browser_compatible(av1)[0] is True
    assert is_browser_compatible(hevc)[0] is False


def test_prepare_media_auto_reuses_compatible_source(tmp_path, monkeypatch):
    from tubeviz.media import MediaInfo, prepare_media

    source = tmp_path / "source.webm"
    source.write_bytes(b"source")
    proxy = tmp_path / "proxy.mp4"
    info = MediaInfo(20.0, 1920, 1080, 30.0, codec_name="vp9", pixel_format="yuv420p", format_name="matroska,webm")
    monkeypatch.setattr(media_module, "probe", lambda path: info)
    monkeypatch.setattr(media_module, "normalize_video", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("transcode should not run")))

    prepared = prepare_media(source, proxy, mode="auto")
    assert prepared.path == source
    assert prepared.transcoded is False
    assert prepared.encoder is None
    assert not proxy.exists()


def test_prepare_media_auto_transcodes_only_incompatible_source(tmp_path, monkeypatch):
    from tubeviz.media import MediaInfo, prepare_media

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    proxy = tmp_path / "proxy.mp4"
    info = MediaInfo(20.0, 1920, 1080, 60.0, codec_name="hevc", pixel_format="yuv420p", format_name="mov,mp4")
    monkeypatch.setattr(media_module, "probe", lambda path: info)
    captured = {}

    def fake_normalize(source_path, destination, **kwargs):
        captured.update(kwargs)
        destination.write_bytes(b"proxy")
        return "h264_nvenc"

    monkeypatch.setattr(media_module, "normalize_video", fake_normalize)
    prepared = prepare_media(source, proxy, mode="auto")

    assert prepared.path == proxy
    assert prepared.transcoded is True
    assert prepared.encoder == "h264_nvenc"
    assert captured["width"] == 0
    assert captured["height"] == 0
    assert captured["fps"] == 0


def test_normalize_video_auto_prefers_nvenc_without_forced_scale(tmp_path, monkeypatch):
    from tubeviz.media import MediaInfo, normalize_video

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    destination = tmp_path / "proxy.mp4"
    info = MediaInfo(20.0, 1920, 1080, 60.0, codec_name="hevc", pixel_format="yuv420p", sample_aspect_ratio="1:1", format_name="mov,mp4")
    monkeypatch.setattr(media_module, "nvenc_usable", lambda: True)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"proxy")

    monkeypatch.setattr(media_module, "_run_ffmpeg_progress", fake_run)
    encoder = normalize_video(source, destination, encoder="auto", source_info=info)

    assert encoder == "h264_nvenc"
    assert destination.read_bytes() == b"proxy"
    command = commands[0]
    assert command[command.index("-c:v") + 1] == "h264_nvenc"
    assert "-vf" not in command


def test_normalize_video_auto_falls_back_to_x264(tmp_path, monkeypatch):
    from tubeviz.media import MediaInfo, MediaToolError, normalize_video

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    destination = tmp_path / "proxy.mp4"
    info = MediaInfo(20.0, 1920, 1080, 30.0, codec_name="hevc", pixel_format="yuv420p", sample_aspect_ratio="1:1", format_name="mov,mp4")
    monkeypatch.setattr(media_module, "nvenc_usable", lambda: True)
    encoders = []

    def fake_run(command, **kwargs):
        selected = command[command.index("-c:v") + 1]
        encoders.append(selected)
        if selected == "h264_nvenc":
            raise MediaToolError("simulated NVENC runtime failure")
        Path(command[-1]).write_bytes(b"proxy")

    monkeypatch.setattr(media_module, "_run_ffmpeg_progress", fake_run)
    encoder = normalize_video(source, destination, encoder="auto", source_info=info)

    assert encoders == ["h264_nvenc", "libx264"]
    assert encoder == "libx264"
    assert destination.exists()


def test_preview_proxy_reuses_small_browser_source(tmp_path, monkeypatch):
    from tubeviz.media import MediaInfo
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    info = MediaInfo(10.0, 854, 480, 30.0, codec_name="h264", pixel_format="yuv420p", format_name="mov,mp4")
    monkeypatch.setattr(media_module, "probe", lambda path: info)
    monkeypatch.setattr(media_module, "normalize_video", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no transcode expected")))
    result = prepare_preview_proxy(source, tmp_path / "preview")
    assert result.path == source
    assert result.transcoded is False


def test_preview_proxy_caps_height_and_fps_and_caches(tmp_path, monkeypatch):
    from tubeviz.media import MediaInfo
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    info = MediaInfo(10.0, 1920, 1080, 60.0, codec_name="h264", pixel_format="yuv420p", format_name="mov,mp4")
    monkeypatch.setattr(media_module, "probe", lambda path: info)
    calls=[]
    def fake_normalize(source_path, destination, **kwargs):
        calls.append(kwargs); destination.write_bytes(b"preview"); return "libx264"
    monkeypatch.setattr(media_module, "normalize_video", fake_normalize)
    first=prepare_preview_proxy(source,tmp_path / "preview")
    second=prepare_preview_proxy(source,tmp_path / "preview")
    assert first.path == second.path
    assert first.path.read_bytes() == b"preview"
    assert calls[0]["height"] == 720
    assert calls[0]["fps"] == 30
    assert len(calls) == 1



def test_normalize_video_scene_range_uses_input_seek_and_duration(tmp_path, monkeypatch):
    from tubeviz.media import MediaInfo

    source = tmp_path / "source.mp4"; source.write_bytes(b"source")
    destination = tmp_path / "proxy.mp4"
    info = MediaInfo(120.0, 1920, 1080, 30.0, codec_name="h264", pixel_format="yuv420p", sample_aspect_ratio="1:1", format_name="mov,mp4")
    monkeypatch.setattr(media_module, "nvenc_usable", lambda: False)
    commands = []
    def fake_run(command, **kwargs):
        commands.append(command); Path(command[-1]).write_bytes(b"proxy")
    monkeypatch.setattr(media_module, "_run_ffmpeg_progress", fake_run)
    normalize_video(source, destination, encoder="x264", source_info=info, start_seconds=42.25, duration_seconds=3.5)
    command = commands[0]
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "42.250000"
    assert command[command.index("-t") + 1] == "3.500000"


def test_preview_proxy_scene_range_never_transcodes_whole_source(tmp_path, monkeypatch):
    from tubeviz.media import MediaInfo

    source = tmp_path / "source.mp4"; source.write_bytes(b"source")
    info = MediaInfo(300.0, 854, 480, 30.0, codec_name="h264", pixel_format="yuv420p", format_name="mov,mp4")
    monkeypatch.setattr(media_module, "probe", lambda path: info)
    captured = {}
    def fake_normalize(source_path, destination, **kwargs):
        captured.update(kwargs); destination.write_bytes(b"preview"); return "libx264"
    monkeypatch.setattr(media_module, "normalize_video", fake_normalize)
    result = prepare_preview_proxy(source, tmp_path / "preview", max_height=360, max_fps=30, start=90.0, end=94.25)
    assert result.path != source
    assert result.reason == "generated scene-range preview proxy"
    assert captured["start_seconds"] == pytest.approx(90.0)
    assert captured["duration_seconds"] == pytest.approx(4.25)
    assert captured["height"] == 360
