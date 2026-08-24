# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from fastapi.testclient import TestClient

from tubeviz.gui import create_gui_app
from tubeviz.library import ClipLibrary, sha256_file


def _discover(library: ClipLibrary, source_id: str, *, status_ready: bool = True) -> int:
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id=source_id,
        source_url=f"https://example.invalid/{source_id}",
        term="visual",
        rank=1,
        metadata={"title": source_id, "duration": 4},
    )
    if status_ready:
        media = library.normalized_dir / f"{source_id}.mp4"
        media.write_bytes(b"fake-video-data")
        library.mark_normalized(clip_id, media, sha256_file(media))
    return clip_id


def test_gui_media_endpoint_serves_ready_normalized_clip(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    _discover(library, "abc")

    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))
    response = client.get("/api/gui/clip/abc/media")
    assert response.status_code == 200
    assert response.content == b"fake-video-data"


def test_gui_library_marks_playback_availability(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    _discover(library, "ready")
    _discover(library, "only-db", status_ready=False)

    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))
    clips = client.get("/api/gui/library").json()["clips"]
    by_id = {clip["source_id"]: clip for clip in clips}
    assert by_id["ready"]["media_available"] is True
    assert by_id["only-db"]["media_available"] is False


def test_gui_media_falls_back_to_original_download(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = _discover(library, "original", status_ready=False)
    original = library.originals_dir / "original.webm"
    original.write_bytes(b"original-media")
    library.mark_downloaded(
        clip_id,
        original_path=original,
        info_json_path=None,
        sha256=sha256_file(original),
    )

    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))
    response = client.get("/api/gui/clip/original/media")
    assert response.status_code == 200
    assert response.content == b"original-media"


def test_gui_media_follows_duplicate_to_canonical(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    canonical_id = _discover(library, "canonical")
    canonical = library.get_clip_by_id(canonical_id)
    assert canonical is not None

    alias_id = _discover(library, "alias", status_ready=False)
    library.mark_duplicate(alias_id, canonical)

    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))
    response = client.get("/api/gui/clip/alias/media")
    assert response.status_code == 200
    assert response.content == b"fake-video-data"


def test_gui_media_recovers_stale_db_path_from_source_id(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = _discover(library, "stale", status_ready=False)
    media = library.normalized_dir / "stale.mp4"
    media.write_bytes(b"recovered-media")
    with library.connect() as db:
        db.execute(
            "UPDATE clips SET normalized_path='normalized/does-not-exist.mp4', status='ready' WHERE id=?",
            (clip_id,),
        )

    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))
    response = client.get("/api/gui/clip/stale/media")
    assert response.status_code == 200
    assert response.content == b"recovered-media"


def test_gui_media_missing_returns_diagnostic_json(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    _discover(library, "missing", status_ready=False)

    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))
    response = client.get("/api/gui/clip/missing/media")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["message"] == "clip exists but has no playable local media"
    assert detail["status"] == "discovered"
    assert detail["library"] == str(library.root)
