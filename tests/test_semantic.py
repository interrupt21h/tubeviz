from pathlib import Path

import numpy as np

from tubeviz.library import ClipLibrary, SceneCandidate
from tubeviz.semantic import cosine_similarity, metadata_semantic_score


def test_metadata_semantic_score_prefers_matching_provenance():
    mall = SceneCandidate(
        scene_id=1, clip_id=1, scene_index=0, start_time=0, end_time=5,
        duration=5, thumbnail_path=None, source_id="a", title="Dead mall walkthrough",
        description="empty retail corridors", channel="archive", normalized_path="normalized/a.mp4",
        term="abandoned shopping mall 1980s", term_rank=1,
    )
    nasa = SceneCandidate(
        scene_id=2, clip_id=2, scene_index=0, start_time=0, end_time=5,
        duration=5, thumbnail_path=None, source_id="b", title="Apollo mission control",
        description="NASA flight controllers", channel="space", normalized_path="normalized/b.mp4",
        term="NASA mission control archival", term_rank=1,
    )
    query = "abandoned shopping mall atmospheric archival footage"
    assert metadata_semantic_score(mall, query) > metadata_semantic_score(nasa, query)


def test_scene_embedding_round_trip(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = library.upsert_discovery(
        source="youtube", source_id="x", source_url="https://example/x",
        term="archive", rank=1, metadata={"title": "X"},
    )
    media = library.normalized_dir / "x.mp4"
    media.write_bytes(b"x")
    from tubeviz.library import sha256_file
    library.mark_normalized(clip_id, media, sha256_file(media))
    library.replace_scenes(clip_id, [(0.0, 5.0, None)])
    scene_id = library.scene_candidates()[0].scene_id

    vector = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    library.store_scene_embedding(scene_id, model="m", pretrained="p", vector=vector)
    loaded = library.load_scene_embeddings([scene_id], model="m", pretrained="p")
    assert np.allclose(loaded[scene_id], vector)
    assert cosine_similarity(vector, vector) > 0.999
