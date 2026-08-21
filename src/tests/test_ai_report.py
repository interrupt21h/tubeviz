from pathlib import Path

from tubeviz.library import ClipLibrary


def test_ai_report_reads_persisted_component_scores(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id="abc",
        source_url="https://example.invalid/abc",
        term="archive",
        rank=2,
        metadata={
            "title": "Archive",
            "_tubeviz_query": "archive vintage film",
            "_tubeviz_ai_score": .31,
            "_tubeviz_ai_visual_score": .28,
            "_tubeviz_ai_negative_score": .11,
            "_tubeviz_ai_metadata_score": .40,
            "_tubeviz_ai_diversity_penalty": .22,
        },
    )
    rows = library.ai_report(term="archive")
    assert len(rows) == 1
    assert rows[0]["source_id"] == "abc"
    assert rows[0]["score"] == .31
    assert rows[0]["query"] == "archive vintage film"
