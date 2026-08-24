# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from fastapi.testclient import TestClient

from tubeviz.cli import build_parser
from tubeviz.gui import JobRequest, _job_command, create_gui_app
from tubeviz.library import ClipLibrary, sha256_file


def test_gui_command_parses():
    args = build_parser().parse_args([
        "gui", "--library", "./clips", "--port", "9000", "--no-open"
    ])
    assert args.library == "./clips"
    assert args.port == 9000
    assert args.no_open is True


def test_gui_analyze_job_builds_safe_argument_vector():
    command = _job_command(JobRequest(
        kind="analyze",
        library="./library",
        audio="audio/song.mp3",
        output="timelines/song.json",
        options={
            "semantic": True,
            "semantic_device": "cuda",
            "reshuffle": True,
            "target_unique_clips": 100,
        },
    ))
    assert command[:3]  # python -m tubeviz.cli
    assert "analyze" in command
    assert "audio/song.mp3" in command
    assert "--semantic" in command
    assert "--reshuffle" in command
    assert "--target-unique-clips" in command
    assert "100" in command


def test_gui_render_job_contains_native_tuning():
    command = _job_command(JobRequest(
        kind="render",
        timeline="timelines/song.json",
        audio="audio/song.mp3",
        output="song.mp4",
        options={
            "backend": "native",
            "fps": 30,
            "native_decoder_cache": 24,
            "native_threads": 8,
            "video_codec": "h264_nvenc",
        },
    ))
    joined = " ".join(command)
    assert "--backend native" in joined
    assert "--native-decoder-cache 24" in joined
    assert "--native-threads 8" in joined
    assert "--video-codec h264_nvenc" in joined


def _ready_clip(library: ClipLibrary):
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id="abc",
        source_url="https://example.invalid/abc",
        term="archive",
        rank=1,
        metadata={"title": "Example clip", "duration": 8},
    )
    media = library.normalized_dir / "abc.mp4"
    media.write_bytes(b"video")
    library.mark_normalized(clip_id, media, sha256_file(media))
    thumb = library.thumbnails_dir / "abc"
    thumb.mkdir(parents=True)
    thumb_file = thumb / "0000.jpg"
    thumb_file.write_bytes(b"jpeg")
    library.replace_scenes(
        clip_id, [(0.0, 4.0, str(thumb_file.relative_to(library.root)))]
    )


def test_gui_library_api_and_curation(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    _ready_clip(library)

    app = create_gui_app(default_library=library.root, project_root=tmp_path)
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert "tubeviz" in root.text

    response = client.get("/api/gui/library")
    assert response.status_code == 200
    data = response.json()
    assert data["clips"][0]["source_id"] == "abc"

    response = client.post(
        "/api/gui/clip/abc/reject",
        json={"library": str(library.root), "reason": "boring"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected_manual"

    response = client.post(
        "/api/gui/clip/abc/restore",
        json={"library": str(library.root)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_gui_rejects_unknown_job_kind():
    try:
        _job_command(JobRequest(kind="shell", options={}))
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unknown GUI job kind was accepted")
