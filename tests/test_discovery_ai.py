from pathlib import Path

import numpy as np

import tubeviz.discovery_ai as ai
from tubeviz.discovery_ai import DiscoveryAIConfig, expand_queries, metadata_candidate_score, rank_candidates
from tubeviz.youtube import SearchResult


def _result(source_id: str, title: str, rank: int = 1):
    return SearchResult(
        source="youtube",
        source_id=source_id,
        url=f"https://example.invalid/{source_id}",
        rank=rank,
        metadata={
            "title": title,
            "description": f"archival footage {title}",
            "_tubeviz_query": "abandoned mall archival footage",
            "duration": 120,
            "thumbnail": f"https://example.invalid/{source_id}.jpg",
        },
    )


def test_query_expansion_is_diverse_and_keeps_seed():
    cfg = DiscoveryAIConfig(query_count=6)
    queries = expand_queries("abandoned mall 1980s", cfg, progress=lambda _: None)
    assert queries[0] == "abandoned mall 1980s"
    assert len(queries) == 6
    assert len(set(queries)) == 6
    assert any("archival" in q for q in queries)


def test_metadata_score_rewards_relevant_title():
    relevant = metadata_candidate_score(_result("a", "Abandoned mall 1980s archive"), "abandoned mall 1980s")
    irrelevant = metadata_candidate_score(_result("b", "Modern cooking tutorial"), "abandoned mall 1980s")
    assert relevant > irrelevant


class FakeEmbedder:
    def encode_text(self, texts):
        texts = list(texts)
        if len(texts) == 2:  # negative concepts in this test
            return np.asarray([[0.0, 1.0], [0.0, 1.0]], dtype=np.float32)
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)

    def encode_images(self, paths):
        vectors = {
            "a": np.asarray([1.0, 0.0], dtype=np.float32),
            "b": np.asarray([0.99, 0.01], dtype=np.float32),
            "c": np.asarray([0.75, 0.66], dtype=np.float32),
        }
        return np.stack([vectors[Path(p).stem] for p in paths])


def test_mmr_prefers_visual_diversity(monkeypatch, tmp_path: Path):
    candidates = [
        _result("a", "Abandoned mall archive", 1),
        _result("b", "Abandoned mall archive similar", 2),
        _result("c", "Empty mall corridor unusual angle", 3),
    ]

    def fake_thumb(result, cache_dir, timeout=15):
        path = tmp_path / f"{result.source_id}.jpg"
        path.write_bytes(b"x" * 300)
        return path

    monkeypatch.setattr(ai, "cache_thumbnail", fake_thumb)
    ranked = rank_candidates(
        candidates,
        seed="abandoned mall",
        queries=["abandoned mall archival footage"],
        cache_dir=tmp_path,
        config=DiscoveryAIConfig(
            negative_concepts=("talking head", "slideshow"),
            diversity_weight=.45,
            near_duplicate_threshold=.86,
            negative_weight=0.0,
            metadata_weight=0.0,
        ),
        embedder=FakeEmbedder(),
        progress=lambda _: None,
    )
    assert ranked[0].result.source_id == "a"
    # b is almost identical to a, so diversity should move c ahead of it.
    assert ranked[1].result.source_id == "c"


def test_ranked_candidate_exposes_component_scores(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        ai,
        "cache_thumbnail",
        lambda result, cache_dir, timeout=15: (tmp_path / f"{result.source_id}.jpg"),
    )
    (tmp_path / "a.jpg").write_bytes(b"x" * 300)
    ranked = rank_candidates(
        [_result("a", "Abandoned mall archive")],
        seed="abandoned mall",
        queries=["abandoned mall"],
        cache_dir=tmp_path,
        config=DiscoveryAIConfig(negative_concepts=("talking head", "slideshow")),
        embedder=FakeEmbedder(),
        progress=lambda _: None,
    )
    item = ranked[0]
    assert isinstance(item.ai_score, float)
    assert isinstance(item.visual_score, float)
    assert item.thumbnail_path is not None
