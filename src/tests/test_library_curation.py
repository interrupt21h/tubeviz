from pathlib import Path

import numpy as np
import pytest

import tubeviz.ingest as ingest_module
from tubeviz.ingest import IngestConfig, ingest_terms
from tubeviz.library import ClipLibrary, sha256_file
from tubeviz.youtube import SearchResult


def make_ready_clip(
    library: ClipLibrary,
    source_id: str = "abc123",
    *,
    term: str = "cool footage",
):
    library.initialize()
    metadata = {
        "title": "Useful visual footage",
        "channel": "Archive",
        "duration": 30.0,
        "width": 1280,
        "height": 720,
    }
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id=source_id,
        source_url=f"https://youtube.invalid/watch?v={source_id}",
        term=term,
        rank=1,
        metadata=metadata,
    )

    original = library.originals_dir / f"{source_id}.mp4"
    original.write_bytes(b"original-video")
    info = library.originals_dir / f"{source_id}.info.json"
    info.write_text("{}")
    library.mark_downloaded(
        clip_id,
        original_path=original,
        info_json_path=info,
        sha256=sha256_file(original),
    )

    normalized = library.normalized_dir / f"{source_id}.mp4"
    normalized.write_bytes(b"normalized-video")
    library.mark_normalized(clip_id, normalized, sha256_file(normalized))

    thumb_dir = library.thumbnails_dir / source_id
    thumb_dir.mkdir(parents=True)
    thumb = thumb_dir / "0000.jpg"
    thumb.write_bytes(b"jpeg-data")
    library.replace_scenes(clip_id, [(0.0, 5.0, str(thumb.relative_to(library.root)))])

    scene = library.scene_candidates(clip_id=clip_id)[0]
    library.store_scene_embedding(
        scene.scene_id,
        model="fake",
        pretrained="fake",
        vector=np.asarray([1.0, 0.0], dtype=np.float32),
    )

    ai_dir = library.metadata_dir / "ai-thumbnails"
    ai_dir.mkdir(parents=True, exist_ok=True)
    (ai_dir / f"{source_id}.jpg").write_bytes(b"ai-thumb")

    return clip_id, original, info, normalized, thumb


def test_reject_is_non_destructive_and_restore_returns_ready(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    _, original, info, normalized, thumb = make_ready_clip(library)

    rejected = library.reject_clip("youtube", "abc123", reason="boring presenter")
    assert rejected.status == "rejected_manual"
    assert rejected.error == "boring presenter"
    assert original.exists() and info.exists() and normalized.exists() and thumb.exists()
    assert library.scene_candidates(clip_id=rejected.id) == []

    restored = library.restore_clip("youtube", "abc123")
    assert restored.status == "ready"
    assert len(library.scene_candidates(clip_id=restored.id)) == 1


def test_restore_falls_back_to_downloaded_or_discovered(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    _, original, _, normalized, _ = make_ready_clip(library)

    library.reject_clip("youtube", "abc123")
    normalized.unlink()
    assert library.restore_clip("youtube", "abc123").status == "downloaded"

    library.reject_clip("youtube", "abc123")
    original.unlink()
    assert library.restore_clip("youtube", "abc123").status == "discovered"


def test_delete_dry_run_changes_nothing(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    _, original, info, normalized, thumb = make_ready_clip(library)

    plan = library.delete_clip("youtube", "abc123", dry_run=True)
    assert plan["dry_run"] is True
    assert library.get_clip("youtube", "abc123") is not None
    assert original.exists() and info.exists() and normalized.exists() and thumb.exists()


def test_hard_delete_removes_db_scenes_embeddings_and_files(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    clip_id, original, info, normalized, thumb = make_ready_clip(library)
    ai_thumb = library.metadata_dir / "ai-thumbnails" / "abc123.jpg"

    plan = library.delete_clip("youtube", "abc123")
    assert plan["dry_run"] is False
    assert library.get_clip("youtube", "abc123") is None
    assert not original.exists()
    assert not info.exists()
    assert not normalized.exists()
    assert not thumb.exists()
    assert not ai_thumb.exists()

    with library.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM scenes WHERE clip_id=?", (clip_id,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM scene_embeddings").fetchone()[0] == 0


def test_delete_keep_original_retains_source_media(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    _, original, info, normalized, _ = make_ready_clip(library)

    library.delete_clip("youtube", "abc123", keep_original=True)
    assert original.exists()
    assert info.exists()
    assert not normalized.exists()
    assert library.get_clip("youtube", "abc123") is None


def test_delete_canonical_also_removes_duplicate_alias_records(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    canonical_id, original, _, normalized, _ = make_ready_clip(library, "canonical")
    canonical = library.get_clip_by_id(canonical_id)
    assert canonical is not None

    duplicate_id = library.upsert_discovery(
        source="youtube",
        source_id="alias",
        source_url="https://youtube.invalid/watch?v=alias",
        term="cool footage",
        rank=2,
        metadata={"title": "Same physical video"},
    )
    library.mark_duplicate(duplicate_id, canonical)

    plan = library.delete_clip("youtube", "canonical")
    assert len(plan["records"]) == 2
    assert library.get_clip("youtube", "canonical") is None
    assert library.get_clip("youtube", "alias") is None
    assert not original.exists()
    assert not normalized.exists()


def test_list_and_show_include_scene_and_term_metadata(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    make_ready_clip(library)

    rows = library.list_clips(status="ready", term="cool footage")
    assert len(rows) == 1
    assert rows[0]["source_id"] == "abc123"
    assert rows[0]["scene_count"] == 1
    assert rows[0]["embedded_scene_count"] == 1

    details = library.clip_details("youtube", "abc123")
    assert details is not None
    assert details["terms"][0]["term"] == "cool footage"
    assert details["scene_count"] == 1
    assert details["info_json_path"].endswith(".info.json")


class RejectAwareSource:
    def __init__(self):
        self.hydrate_called = False
        self.download_called = False

    def search(self, term, limit):
        return [
            SearchResult(
                source="youtube",
                source_id="abc123",
                url="https://youtube.invalid/watch?v=abc123",
                rank=1,
                metadata={"title": "Rejected clip", "duration": 30.0},
            )
        ]

    def hydrate(self, result):
        self.hydrate_called = True
        raise AssertionError("manually rejected clip must not hydrate")

    def download(self, result, originals_dir):
        self.download_called = True
        raise AssertionError("manually rejected clip must not download")


def test_ingest_never_reuses_manually_rejected_clip_even_with_force(tmp_path: Path, monkeypatch):
    library = ClipLibrary(tmp_path / "library")
    make_ready_clip(library)
    library.reject_clip("youtube", "abc123", reason="user dislikes this footage")

    source = RejectAwareSource()
    monkeypatch.setattr(ingest_module, "require_media_tools", lambda: None)

    summary = ingest_terms(
        ["cool footage"],
        library,
        config=IngestConfig(results_per_term=1, force=True),
        source=source,
        progress=lambda _: None,
    )
    assert summary.manual_rejected == 1
    assert source.hydrate_called is False
    assert source.download_called is False
    assert library.get_clip("youtube", "abc123").status == "rejected_manual"
