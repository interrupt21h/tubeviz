from pathlib import Path

from fastapi.testclient import TestClient

from tubeviz.gui import create_gui_app
from tubeviz.library import ClipLibrary, sha256_file


def _ready(library: ClipLibrary, source_id: str, term: str) -> int:
    clip_id = library.upsert_discovery(
        source="youtube", source_id=source_id,
        source_url=f"https://youtu.be/{source_id}", term=term, rank=1,
        metadata={"title": source_id, "duration": 10.0},
    )
    media = library.normalized_dir / f"{source_id}.mp4"
    media.write_bytes(source_id.encode())
    library.mark_normalized(clip_id, media, sha256_file(media))
    library.replace_scenes(clip_id, [(0.0, 5.0, None)])
    return clip_id


def test_tags_and_output_pool_limit_scene_candidates(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    first = _ready(library, "first", "city")
    second = _ready(library, "second", "nature")

    assert library.set_clip_tags("youtube", "first", ["Night", " favorite "]) == ["favorite", "Night"]
    assert library.set_clip_tags("youtube", "second", ["night"]) == ["night"]
    assert {item["name"].casefold() for item in library.list_tags()} == {"favorite", "night"}
    assert {scene.clip_id for scene in library.scene_candidates()} == {first, second}

    assert library.select_output_by_tag("NIGHT", True) == 2
    assert {scene.clip_id for scene in library.scene_candidates()} == {first, second}
    assert library.set_output_selected([second], False) == 1
    assert {scene.clip_id for scene in library.scene_candidates()} == {first}
    assert library.clear_output_selection() == 1
    assert {scene.clip_id for scene in library.scene_candidates()} == {first, second}


def test_studio_tag_and_output_pool_api(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = _ready(library, "clip-a", "manual")
    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))

    response = client.post(
        "/api/gui/clip/clip-a/tags",
        json={"library": str(library.root), "source": "youtube", "tags": ["hero", "blue"]},
    )
    assert response.status_code == 200
    assert response.json()["tags"] == ["blue", "hero"]

    response = client.post(
        "/api/gui/library/output-selection",
        json={"library": str(library.root), "clip_ids": [clip_id], "selected": True},
    )
    assert response.json() == {"changed": 1, "count": 1, "active": True}
    state = client.get("/api/gui/library", params={"library": str(library.root), "tag": "hero"}).json()
    assert state["clips"][0]["output_selected"] is True
    assert state["clips"][0]["tags"] == ["blue", "hero"]

