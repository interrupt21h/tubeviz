from pathlib import Path

from tubeviz.library import ClipLibrary


def test_library_records_terms_and_deduplicates_source_id(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()

    clip_id_a = library.upsert_discovery(
        source="youtube",
        source_id="abc123",
        source_url="https://www.youtube.com/watch?v=abc123",
        term="abandoned mall",
        rank=1,
        metadata={"title": "Example", "duration": 12.0},
    )
    clip_id_b = library.upsert_discovery(
        source="youtube",
        source_id="abc123",
        source_url="https://www.youtube.com/watch?v=abc123",
        term="vhs shopping mall",
        rank=4,
        metadata={"title": "Example", "duration": 12.0},
    )

    assert clip_id_a == clip_id_b
    stats = library.stats()
    assert stats["clips"] == 1
    assert stats["terms"] == 2


def test_library_scene_replace(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id="xyz",
        source_url="https://www.youtube.com/watch?v=xyz",
        term="test",
        rank=1,
        metadata={},
    )
    library.replace_scenes(clip_id, [(0.0, 2.0, "thumbnails/xyz/0000.jpg"), (2.0, 5.0, None)])
    assert library.stats()["scenes"] == 2
