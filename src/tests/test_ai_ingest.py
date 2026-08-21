from pathlib import Path

import numpy as np

import tubeviz.ingest as ingest_module
from tubeviz.discovery_ai import RankedCandidate
from tubeviz.ingest import IngestConfig, ingest_terms
from tubeviz.library import ClipLibrary
from tubeviz.youtube import SearchResult


class FakeEmbedder:
    def __init__(self, *args, **kwargs):
        pass

    def encode_images(self, paths):
        return np.asarray([[1.0, 0.0] for _ in paths], dtype=np.float32)


class FakeSource:
    def search(self, term, limit):
        return []

    def hydrate(self, result):
        return SearchResult(
            source=result.source,
            source_id=result.source_id,
            url=result.url,
            rank=result.rank,
            metadata={**result.metadata, "duration": 30, "width": 1920},
        )

    def download(self, result, originals_dir: Path):
        originals_dir.mkdir(parents=True, exist_ok=True)
        path = originals_dir / f"{result.source_id}.mp4"
        path.write_bytes(result.source_id.encode())
        return path, None, result.metadata


def test_ai_ingest_downloads_ranked_shortlist_and_persists_score(tmp_path: Path, monkeypatch):
    library = ClipLibrary(tmp_path / "library")
    candidates = [
        SearchResult("youtube", "good", "https://example.invalid/good", 2, {"title": "good"}),
        SearchResult("youtube", "bad", "https://example.invalid/bad", 1, {"title": "bad"}),
    ]

    monkeypatch.setattr(ingest_module, "OpenClipEmbedder", FakeEmbedder)
    monkeypatch.setattr(
        ingest_module,
        "discover_candidates",
        lambda source, term, cfg, progress=print: ([term, term + " archive"], candidates),
    )
    monkeypatch.setattr(
        ingest_module,
        "rank_candidates",
        lambda candidates, **kwargs: [
            RankedCandidate(candidates[0], .8, .7, .1, .2, 0.0, None),
            RankedCandidate(candidates[1], -.3, .1, .6, .1, .0, None),
        ],
    )
    monkeypatch.setattr(ingest_module, "require_media_tools", lambda: None)
    monkeypatch.setattr(
        ingest_module,
        "normalize_video",
        lambda source, destination, **kwargs: destination.write_bytes(source.read_bytes()),
    )
    monkeypatch.setattr(ingest_module, "_index_scenes", lambda *args, **kwargs: 0)

    summary = ingest_terms(
        ["archive"],
        library,
        config=IngestConfig(
            results_per_term=1,
            ai_discovery=True,
            ai_min_score=0.0,
            ai_index_scenes=False,
        ),
        source=FakeSource(),
        progress=lambda _: None,
    )

    assert summary.ready == 1
    assert summary.ai_scored == 2
    assert summary.ai_rejected == 1
    assert library.get_clip("youtube", "good").status == "ready"
    assert library.get_clip("youtube", "bad") is None
