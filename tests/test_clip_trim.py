from pathlib import Path

from fastapi.testclient import TestClient

from tubeviz.gui import create_gui_app
from tubeviz.library import ClipLibrary, sha256_file


def make_clip(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id="trimme",
        source_url="https://example.invalid/trimme",
        term="archive",
        rank=1,
        metadata={"title": "Trim test", "duration": 20.0, "width": 1280, "height": 720},
    )
    media = library.normalized_dir / "trimme.mp4"
    media.write_bytes(b"fake video")
    library.mark_normalized(clip_id, media, sha256_file(media))
    library.replace_scenes(
        clip_id,
        [
            (0.0, 4.0, None),
            (4.0, 10.0, None),
            (10.0, 16.0, None),
            (16.0, 20.0, None),
        ],
    )
    return library, clip_id


def test_trim_clamps_and_excludes_scene_candidates(tmp_path: Path):
    library, clip_id = make_clip(tmp_path)
    library.set_clip_trim("youtube", "trimme", usable_start=5.5, usable_end=17.25)

    scenes = library.scene_candidates(clip_id=clip_id)
    assert [(round(x.start_time, 2), round(x.end_time, 2)) for x in scenes] == [
        (5.5, 10.0),
        (10.0, 16.0),
        (16.0, 17.25),
    ]
    assert all(x.start_time >= 5.5 and x.end_time <= 17.25 for x in scenes)


def test_min_duration_applies_after_trim(tmp_path: Path):
    library, clip_id = make_clip(tmp_path)
    library.set_clip_trim("youtube", "trimme", usable_start=5.5, usable_end=17.25)
    scenes = library.scene_candidates(clip_id=clip_id, min_duration=2.0)
    assert [(x.start_time, x.end_time) for x in scenes] == [(5.5, 10.0), (10.0, 16.0)]


def test_clear_trim_restores_full_scene_corpus(tmp_path: Path):
    library, clip_id = make_clip(tmp_path)
    library.set_clip_trim("youtube", "trimme", usable_start=5.5, usable_end=17.25)
    library.clear_clip_trim("youtube", "trimme")
    scenes = library.scene_candidates(clip_id=clip_id)
    assert [(x.start_time, x.end_time) for x in scenes] == [
        (0.0, 4.0), (4.0, 10.0), (10.0, 16.0), (16.0, 20.0)
    ]
    details = library.clip_details("youtube", "trimme")
    assert details["usable_start"] is None
    assert details["usable_end"] is None


def test_trim_shifts_visual_accents_inside_clipped_scene(tmp_path: Path):
    library, clip_id = make_clip(tmp_path)
    first_middle = library.scene_candidates(clip_id=clip_id)[1]
    library.store_scene_visual_features(first_middle.scene_id, {
        "version": 1,
        "motion": .8,
        "accents": [
            {"time": .5, "strength": .7},
            {"time": 2.0, "strength": 1.0},
            {"time": 5.0, "strength": .9},
        ],
    })
    library.set_clip_trim("youtube", "trimme", usable_start=5.5, usable_end=20.0)
    scene = next(x for x in library.scene_candidates(clip_id=clip_id) if x.scene_id == first_middle.scene_id)
    # Original scene starts at 4.0, so the trim removes the first 1.5 seconds.
    assert scene.start_time == 5.5
    assert [round(a["time"], 2) for a in scene.visual_features["accents"]] == [.5, 3.5]


def test_visual_index_can_request_untrimmed_candidates(tmp_path: Path):
    library, clip_id = make_clip(tmp_path)
    library.set_clip_trim("youtube", "trimme", usable_start=5.5, usable_end=17.25)
    scenes = library.scene_candidates(clip_id=clip_id, respect_trim=False)
    assert [(x.start_time, x.end_time) for x in scenes] == [
        (0.0, 4.0), (4.0, 10.0), (10.0, 16.0), (16.0, 20.0)
    ]


def test_gui_trim_save_and_clear(tmp_path: Path):
    library, _ = make_clip(tmp_path)
    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))

    response = client.post(
        "/api/gui/clip/trimme/trim",
        json={
            "library": str(library.root),
            "source": "youtube",
            "usable_start": 3.25,
            "usable_end": 18.5,
        },
    )
    assert response.status_code == 200
    assert response.json()["usable_start"] == 3.25
    assert response.json()["usable_end"] == 18.5

    listing = client.get("/api/gui/library").json()["clips"]
    clip = next(x for x in listing if x["source_id"] == "trimme")
    assert clip["usable_start"] == 3.25
    assert clip["usable_end"] == 18.5
    assert clip["usable_duration"] == 15.25

    response = client.post(
        "/api/gui/clip/trimme/trim/clear",
        json={"library": str(library.root), "source": "youtube"},
    )
    assert response.status_code == 200
    assert response.json()["usable_start"] is None
    assert response.json()["usable_end"] is None


def test_gui_trim_rejects_invalid_range(tmp_path: Path):
    library, _ = make_clip(tmp_path)
    client = TestClient(create_gui_app(default_library=library.root, project_root=tmp_path))
    response = client.post(
        "/api/gui/clip/trimme/trim",
        json={
            "library": str(library.root),
            "source": "youtube",
            "usable_start": 10.0,
            "usable_end": 9.0,
        },
    )
    assert response.status_code == 400
