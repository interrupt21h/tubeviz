from pathlib import Path

from tubeviz.library import ClipLibrary


def test_initialize_migrates_v4_library_with_trim_columns(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    with library.connect() as db:
        db.execute("ALTER TABLE clips DROP COLUMN usable_start")
        db.execute("ALTER TABLE clips DROP COLUMN usable_end")
        db.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','4')"
        )
        before = {row["name"] for row in db.execute("PRAGMA table_info(clips)")}
    assert "usable_start" not in before
    assert "usable_end" not in before

    library.initialize()
    with library.connect() as db:
        after = {row["name"] for row in db.execute("PRAGMA table_info(clips)")}
        version = db.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()["value"]
    assert "usable_start" in after
    assert "usable_end" in after
    assert version == "5"
