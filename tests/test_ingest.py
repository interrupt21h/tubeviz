from pathlib import Path

import tubeviz.ingest as ingest_module
from tubeviz.ingest import IngestConfig, ingest_terms, read_search_terms
from tubeviz.library import ClipLibrary
from tubeviz.youtube import SearchResult


class FakeSource:
    def search(self, term: str, limit: int):
        return [
            SearchResult(
                source="youtube",
                source_id="clip1",
                url="https://example.invalid/clip1",
                rank=1,
                metadata={"title": "Clip 1"},
            )
        ]

    def hydrate(self, result: SearchResult):
        return SearchResult(
            source=result.source,
            source_id=result.source_id,
            url=result.url,
            rank=result.rank,
            metadata={"title": "Clip 1", "duration": 10.0, "width": 1920, "height": 1080},
        )

    def download(self, result: SearchResult, originals_dir: Path):
        originals_dir.mkdir(parents=True, exist_ok=True)
        media = originals_dir / "clip1.mp4"
        media.write_bytes(b"fake-video-bytes")
        return media, None, result.metadata


def test_read_search_terms_ignores_comments_blanks_and_duplicates(tmp_path: Path):
    path = tmp_path / "terms.txt"
    path.write_text("# visual universe\nmall\n\nspace\nmall\n")
    assert read_search_terms(path) == ["mall", "space"]


def test_ingest_is_idempotent_for_ready_clip(tmp_path: Path, monkeypatch):
    library = ClipLibrary(tmp_path / "library")

    monkeypatch.setattr(ingest_module, "require_media_tools", lambda: None)
    monkeypatch.setattr(ingest_module, "normalize_video", lambda source, destination, **kwargs: destination.write_bytes(source.read_bytes()))
    monkeypatch.setattr(ingest_module, "_index_scenes", lambda *args, **kwargs: 3)

    first = ingest_terms(
        ["abandoned mall"],
        library,
        config=IngestConfig(results_per_term=1),
        source=FakeSource(),
        progress=lambda _: None,
    )
    second = ingest_terms(
        ["abandoned mall"],
        library,
        config=IngestConfig(results_per_term=1),
        source=FakeSource(),
        progress=lambda _: None,
    )

    assert first.downloaded == 1
    assert first.ready == 1
    assert first.scenes == 3
    assert second.downloaded == 0
    assert second.skipped_existing == 1
    assert library.stats()["clips"] == 1


class QuotaSource:
    def __init__(self):
        self.download_attempts = []

    def search(self, term: str, limit: int):
        assert limit >= 4
        return [
            SearchResult(source="youtube", source_id="long", url="https://example.invalid/long", rank=1,
                         metadata={"title": "Long", "duration": 1500.0}),
            SearchResult(source="youtube", source_id="blocked", url="https://example.invalid/blocked", rank=2,
                         metadata={"title": "Blocked", "duration": 30.0}),
            SearchResult(source="youtube", source_id="ok1", url="https://example.invalid/ok1", rank=3,
                         metadata={"title": "OK1", "duration": 40.0}),
            SearchResult(source="youtube", source_id="ok2", url="https://example.invalid/ok2", rank=4,
                         metadata={"title": "OK2", "duration": 50.0}),
        ]

    def hydrate(self, result: SearchResult):
        return SearchResult(
            source=result.source,
            source_id=result.source_id,
            url=result.url,
            rank=result.rank,
            metadata={**result.metadata, "width": 1920, "height": 1080},
        )

    def download(self, result: SearchResult, originals_dir: Path):
        from tubeviz.youtube import DownloadFailure
        self.download_attempts.append(result.source_id)
        if result.source_id == "blocked":
            raise DownloadFailure("HTTP Error 403: Forbidden", status="blocked_403")
        originals_dir.mkdir(parents=True, exist_ok=True)
        media = originals_dir / f"{result.source_id}.mp4"
        media.write_bytes(result.source_id.encode())
        return media, None, result.metadata


def test_ingest_keeps_searching_until_ready_quota(tmp_path: Path, monkeypatch):
    library = ClipLibrary(tmp_path / "library")
    source = QuotaSource()

    monkeypatch.setattr(ingest_module, "require_media_tools", lambda: None)
    monkeypatch.setattr(ingest_module, "normalize_video", lambda source, destination, **kwargs: destination.write_bytes(source.read_bytes()))
    monkeypatch.setattr(ingest_module, "_index_scenes", lambda *args, **kwargs: 1)

    summary = ingest_terms(
        ["archive"],
        library,
        config=IngestConfig(results_per_term=2, search_pool=4, preferred_max_duration=1200, hard_max_duration=3600),
        source=source,
        progress=lambda _: None,
    )

    assert summary.ready == 2
    assert summary.blocked_403 == 1
    assert summary.quota_shortfall == 0
    assert "long" not in source.download_attempts  # shorter candidates filled quota first
    assert library.get_clip("youtube", "blocked").status == "blocked_403"


def test_soft_duration_is_not_a_rejection(tmp_path: Path, monkeypatch):
    class LongOnlySource:
        def search(self, term: str, limit: int):
            return [SearchResult(source="youtube", source_id="long", url="https://example.invalid/long", rank=1,
                                 metadata={"title": "Long", "duration": 1500.0})]
        def hydrate(self, result):
            return SearchResult(source=result.source, source_id=result.source_id, url=result.url, rank=result.rank,
                                metadata={**result.metadata, "width": 1920})
        def download(self, result, originals_dir):
            originals_dir.mkdir(parents=True, exist_ok=True)
            media = originals_dir / "long.mp4"
            media.write_bytes(b"long")
            return media, None, result.metadata

    library = ClipLibrary(tmp_path / "library")
    monkeypatch.setattr(ingest_module, "require_media_tools", lambda: None)
    monkeypatch.setattr(ingest_module, "normalize_video", lambda source, destination, **kwargs: destination.write_bytes(source.read_bytes()))
    monkeypatch.setattr(ingest_module, "_index_scenes", lambda *args, **kwargs: 1)

    summary = ingest_terms(
        ["archive"], library,
        config=IngestConfig(results_per_term=1, search_pool=1, preferred_max_duration=1200, hard_max_duration=3600),
        source=LongOnlySource(), progress=lambda _: None,
    )
    assert summary.ready == 1
    assert summary.rejected == 0

class ExpandingSource:
    def __init__(self):
        self.search_limits = []

    def search(self, term: str, limit: int):
        self.search_limits.append(limit)
        all_results = [
            SearchResult(
                source="youtube",
                source_id=f"long{i}",
                url=f"https://example.invalid/long{i}",
                rank=i + 1,
                metadata={"title": f"Long {i}", "duration": 900.0},
            )
            for i in range(6)
        ] + [
            SearchResult(
                source="youtube",
                source_id="short1",
                url="https://example.invalid/short1",
                rank=7,
                metadata={"title": "Short 1", "duration": 120.0},
            ),
            SearchResult(
                source="youtube",
                source_id="short2",
                url="https://example.invalid/short2",
                rank=8,
                metadata={"title": "Short 2", "duration": 180.0},
            ),
        ]
        return all_results[:limit]

    def hydrate(self, result):
        return SearchResult(
            source=result.source,
            source_id=result.source_id,
            url=result.url,
            rank=result.rank,
            metadata={**result.metadata, "width": 1920},
        )

    def download(self, result, originals_dir):
        originals_dir.mkdir(parents=True, exist_ok=True)
        path = originals_dir / f"{result.source_id}.mp4"
        path.write_bytes(result.source_id.encode())
        return path, None, result.metadata


def test_ingest_progressively_expands_search_for_restrictive_hard_max(tmp_path: Path, monkeypatch):
    library = ClipLibrary(tmp_path / "library")
    source = ExpandingSource()
    monkeypatch.setattr(ingest_module, "require_media_tools", lambda: None)
    monkeypatch.setattr(ingest_module, "normalize_video", lambda source, destination, **kwargs: destination.write_bytes(source.read_bytes()))
    monkeypatch.setattr(ingest_module, "_index_scenes", lambda *args, **kwargs: 1)

    summary = ingest_terms(
        ["archive"],
        library,
        config=IngestConfig(
            results_per_term=2,
            search_pool=4,
            max_search_pool=8,
            search_pool_step=2,
            hard_max_duration=400,
        ),
        source=source,
        progress=lambda _: None,
    )

    assert summary.ready == 2
    assert summary.quota_shortfall == 0
    assert source.search_limits == [4, 6, 8]
    assert library.get_clip("youtube", "long0").status == "rejected"
    assert library.get_clip("youtube", "short1").status == "ready"
