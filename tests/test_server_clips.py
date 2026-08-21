from pathlib import Path

from fastapi.testclient import TestClient

from tubeviz.library import ClipLibrary, sha256_file
from tubeviz.models import DirectedTimeline, Section, TrackAnalysis
from tubeviz.server import create_app


def test_server_plans_and_serves_normalized_media(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id="abc",
        source_url="https://www.youtube.com/watch?v=abc",
        term="archive",
        rank=1,
        metadata={"title": "Archive"},
    )
    media = library.normalized_dir / "abc.mp4"
    media.write_bytes(b"tubeviz-test-media")
    library.mark_normalized(clip_id, media, sha256_file(media))
    library.replace_scenes(clip_id, [(0.0, 5.0, None)])

    track = TrackAnalysis(
        source="/tmp/song.wav", duration=5.0, sample_rate=22050, hop_length=512,
        tempo_bpm=120.0, beats=[], bars=[], events=[],
        sections=[Section(index=0, start=0.0, end=5.0, energy=.5, label="drive")],
    )
    timeline_path = tmp_path / "timeline.json"
    timeline_path.write_text(DirectedTimeline(track=track, cues=[]).model_dump_json())

    client = TestClient(create_app(timeline_path, library_path=library.root))
    status = client.get("/api/status").json()
    assert status["clips_enabled"] is True
    assert status["scene_count"] == 1
    timeline = client.get("/api/timeline").json()
    assert timeline["scene_plan"][0]["source_id"] == "abc"
    response = client.get("/media/abc.mp4")
    assert response.status_code == 200
    assert response.content == b"tubeviz-test-media"

    partial = client.get("/media/abc.mp4", headers={"Range": "bytes=0-5"})
    assert partial.status_code == 206
    assert partial.content == b"tubevi"
    assert partial.headers["accept-ranges"] == "bytes"
