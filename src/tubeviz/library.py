# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 7


@dataclass(frozen=True)
class ClipRecord:
    id: int
    source: str
    source_id: str
    source_url: str
    title: str | None
    channel: str | None
    description: str | None
    duration: float | None
    width: int | None
    height: int | None
    upload_date: str | None
    original_path: str | None
    normalized_path: str | None
    original_sha256: str | None
    normalized_sha256: str | None
    usable_start: float | None
    usable_end: float | None
    status: str
    error: str | None


@dataclass(frozen=True)
class SceneCandidate:
    scene_id: int
    clip_id: int
    scene_index: int
    start_time: float
    end_time: float
    duration: float
    thumbnail_path: str | None
    source_id: str
    title: str | None
    description: str | None
    channel: str | None
    normalized_path: str
    term: str | None
    term_rank: int | None
    visual_features: dict[str, Any] | None = None
    ai_description: dict[str, Any] | None = None


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _ai_card_summary(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    utility = data.get("editing_utility") if isinstance(data.get("editing_utility"), dict) else {}
    tags = data.get("semantic_tags") if isinstance(data.get("semantic_tags"), list) else []
    moods = data.get("moods") if isinstance(data.get("moods"), list) else []
    return {
        "summary": str(data.get("summary") or "").strip(),
        "semantic_tags": [str(value) for value in tags[:8]],
        "moods": [str(value) for value in moods[:5]],
        "editing_utility": {
            key: utility.get(key) for key in (
                "energy", "motion", "complexity", "continuity",
                "build_fit", "drop_fit", "ambient_fit",
            ) if isinstance(utility.get(key), (int, float))
        },
    }


class ClipLibrary:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.originals_dir = self.root / "originals"
        self.normalized_dir = self.root / "normalized"
        self.preview_dir = self.root / "preview"
        self.thumbnails_dir = self.root / "thumbnails"
        self.metadata_dir = self.root / "metadata"
        self.db_path = self.root / "metadata.sqlite3"

    def initialize(self) -> None:
        for path in (
            self.root,
            self.originals_dir,
            self.normalized_dir,
            self.preview_dir,
            self.thumbnails_dir,
            self.metadata_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    title TEXT,
                    channel TEXT,
                    description TEXT,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    upload_date TEXT,
                    webpage_url TEXT,
                    extractor TEXT,
                    original_path TEXT,
                    normalized_path TEXT,
                    info_json_path TEXT,
                    original_sha256 TEXT,
                    normalized_sha256 TEXT,
                    usable_start REAL,
                    usable_end REAL,
                    status TEXT NOT NULL DEFAULT 'discovered',
                    duplicate_of_clip_id INTEGER REFERENCES clips(id),
                    error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    discovered_at TEXT NOT NULL,
                    downloaded_at TEXT,
                    normalized_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, source_id)
                );

                CREATE INDEX IF NOT EXISTS idx_clips_original_sha ON clips(original_sha256);
                CREATE INDEX IF NOT EXISTS idx_clips_normalized_sha ON clips(normalized_sha256);

                CREATE TABLE IF NOT EXISTS search_terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL UNIQUE,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS clip_terms (
                    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                    term_id INTEGER NOT NULL REFERENCES search_terms(id) ON DELETE CASCADE,
                    rank INTEGER,
                    discovered_at TEXT NOT NULL,
                    PRIMARY KEY(clip_id, term_id)
                );

                CREATE TABLE IF NOT EXISTS scenes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                    scene_index INTEGER NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    duration REAL NOT NULL,
                    thumbnail_path TEXT,
                    UNIQUE(clip_id, scene_index)
                );

                CREATE INDEX IF NOT EXISTS idx_scenes_clip ON scenes(clip_id, scene_index);
                CREATE INDEX IF NOT EXISTS idx_clip_terms_term ON clip_terms(term_id, rank);

                CREATE TABLE IF NOT EXISTS scene_embeddings (
                    scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    pretrained TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scene_id, model, pretrained)
                );

                CREATE INDEX IF NOT EXISTS idx_scene_embeddings_model
                    ON scene_embeddings(model, pretrained, scene_id);


                CREATE TABLE IF NOT EXISTS scene_visual_features (
                    scene_id INTEGER PRIMARY KEY REFERENCES scenes(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_scene_visual_features_version
                    ON scene_visual_features(version, scene_id);

                CREATE TABLE IF NOT EXISTS clip_ai_descriptions (
                    clip_id INTEGER PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scene_ai_descriptions (
                    scene_id INTEGER PRIMARY KEY REFERENCES scenes(id) ON DELETE CASCADE,
                    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scene_ai_clip ON scene_ai_descriptions(clip_id, scene_id);

                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS clip_tags (
                    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY(clip_id, tag_id)
                );

                CREATE TABLE IF NOT EXISTS output_selection (
                    clip_id INTEGER PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
                    selected_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_clip_tags_tag ON clip_tags(tag_id, clip_id);
                """
            )
            # Forward-compatible in-place migrations for persistent libraries.
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(clips)").fetchall()
            }
            if "usable_start" not in columns:
                db.execute("ALTER TABLE clips ADD COLUMN usable_start REAL")
            if "usable_end" not in columns:
                db.execute("ALTER TABLE clips ADD COLUMN usable_end REAL")

            db.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_clip(self, source: str, source_id: str) -> ClipRecord | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM clips WHERE source=? AND source_id=?",
                (source, source_id),
            ).fetchone()
        return self._record(row) if row else None

    def get_clip_by_id(self, clip_id: int) -> ClipRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        return self._record(row) if row else None

    def upsert_discovery(
        self,
        *,
        source: str,
        source_id: str,
        source_url: str,
        term: str,
        rank: int,
        metadata: dict[str, Any],
    ) -> int:
        now = utcnow()
        clean_metadata = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO clips(
                    source, source_id, source_url, title, channel, description,
                    duration, width, height, upload_date, webpage_url, extractor,
                    metadata_json, discovered_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    source_url=excluded.source_url,
                    title=COALESCE(excluded.title, clips.title),
                    channel=COALESCE(excluded.channel, clips.channel),
                    description=COALESCE(excluded.description, clips.description),
                    duration=COALESCE(excluded.duration, clips.duration),
                    width=COALESCE(excluded.width, clips.width),
                    height=COALESCE(excluded.height, clips.height),
                    upload_date=COALESCE(excluded.upload_date, clips.upload_date),
                    webpage_url=COALESCE(excluded.webpage_url, clips.webpage_url),
                    extractor=COALESCE(excluded.extractor, clips.extractor),
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    source,
                    source_id,
                    source_url,
                    metadata.get("title"),
                    metadata.get("channel") or metadata.get("uploader"),
                    metadata.get("description"),
                    metadata.get("duration"),
                    metadata.get("width"),
                    metadata.get("height"),
                    metadata.get("upload_date"),
                    metadata.get("webpage_url"),
                    metadata.get("extractor_key") or metadata.get("extractor"),
                    clean_metadata,
                    now,
                    now,
                ),
            )
            clip_id = int(
                db.execute(
                    "SELECT id FROM clips WHERE source=? AND source_id=?",
                    (source, source_id),
                ).fetchone()[0]
            )
            db.execute(
                """
                INSERT INTO search_terms(term, first_seen_at, last_seen_at)
                VALUES(?,?,?)
                ON CONFLICT(term) DO UPDATE SET last_seen_at=excluded.last_seen_at
                """,
                (term, now, now),
            )
            term_id = int(db.execute("SELECT id FROM search_terms WHERE term=?", (term,)).fetchone()[0])
            db.execute(
                """
                INSERT INTO clip_terms(clip_id, term_id, rank, discovered_at)
                VALUES(?,?,?,?)
                ON CONFLICT(clip_id, term_id) DO UPDATE SET
                    rank=MIN(COALESCE(clip_terms.rank, excluded.rank), excluded.rank)
                """,
                (clip_id, term_id, rank, now),
            )
        return clip_id


    def find_by_original_sha256(self, sha256: str, *, exclude_clip_id: int | None = None) -> ClipRecord | None:
        query = "SELECT * FROM clips WHERE original_sha256=?"
        params: list[object] = [sha256]
        if exclude_clip_id is not None:
            query += " AND id<>?"
            params.append(exclude_clip_id)
        query += " ORDER BY CASE status WHEN 'ready' THEN 0 WHEN 'downloaded' THEN 1 ELSE 2 END, id LIMIT 1"
        with self.connect() as db:
            row = db.execute(query, params).fetchone()
        return self._record(row) if row else None

    def mark_duplicate(self, clip_id: int, canonical: ClipRecord) -> None:
        now = utcnow()
        with self.connect() as db:
            db.execute(
                """
                UPDATE clips SET duplicate_of_clip_id=?, original_path=?, normalized_path=?,
                    original_sha256=?, normalized_sha256=?, status='duplicate', error=NULL, updated_at=?
                WHERE id=?
                """,
                (canonical.id, canonical.original_path, canonical.normalized_path,
                 canonical.original_sha256, canonical.normalized_sha256, now, clip_id),
            )

    def mark_downloaded(
        self,
        clip_id: int,
        *,
        original_path: Path,
        info_json_path: Path | None,
        sha256: str,
    ) -> None:
        now = utcnow()
        with self.connect() as db:
            db.execute(
                """
                UPDATE clips SET original_path=?, info_json_path=?, original_sha256=?,
                    status='downloaded', error=NULL, downloaded_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    str(original_path.relative_to(self.root)),
                    str(info_json_path.relative_to(self.root)) if info_json_path else None,
                    sha256,
                    now,
                    now,
                    clip_id,
                ),
            )

    def mark_ready_media(self, clip_id: int, path: Path, sha256: str) -> None:
        """Mark the canonical media used by scene planning/rendering as ready.

        ``normalized_path`` remains the on-disk schema column for backward
        compatibility, but since v0.32 it may reference either an originals/
        source file or a normalized/ compatibility proxy.
        """
        now = utcnow()
        with self.connect() as db:
            db.execute(
                """
                UPDATE clips SET normalized_path=?, normalized_sha256=?, status='ready',
                    error=NULL, normalized_at=?, updated_at=? WHERE id=?
                """,
                (str(path.relative_to(self.root)), sha256, now, now, clip_id),
            )

    def mark_normalized(self, clip_id: int, path: Path, sha256: str) -> None:
        # Backward-compatible API used by older integrations/tests.
        self.mark_ready_media(clip_id, path, sha256)

    def mark_failure(self, clip_id: int, status: str, error: str) -> None:
        if status not in {
            'rejected', 'blocked_403', 'unavailable', 'private', 'auth_required',
            'metadata_error', 'download_error', 'normalize_error',
            'live_stream', 'no_finite_format'
        }:
            status = 'download_error'
        with self.connect() as db:
            db.execute(
                "UPDATE clips SET status=?, error=?, updated_at=? WHERE id=?",
                (status, error[:4000], utcnow(), clip_id),
            )

    def mark_error(self, clip_id: int, error: str) -> None:
        # Backward-compatible alias for older callers.
        self.mark_failure(clip_id, 'download_error', error)

    def replace_scenes(self, clip_id: int, scenes: list[tuple[float, float, str | None]]) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM scenes WHERE clip_id=?", (clip_id,))
            db.executemany(
                """
                INSERT INTO scenes(clip_id, scene_index, start_time, end_time, duration, thumbnail_path)
                VALUES(?,?,?,?,?,?)
                """,
                [
                    (clip_id, i, start, end, end - start, thumb)
                    for i, (start, end, thumb) in enumerate(scenes)
                    if end > start
                ],
            )

    def list_terms(self, *, ready_only: bool = False) -> list[str]:
        with self.connect() as db:
            if ready_only:
                rows = db.execute(
                    """
                    SELECT DISTINCT st.term
                    FROM search_terms st
                    JOIN clip_terms ct ON ct.term_id=st.id
                    JOIN clips c ON c.id=ct.clip_id
                    JOIN scenes s ON s.clip_id=c.id
                    WHERE c.status='ready' AND c.normalized_path IS NOT NULL
                    ORDER BY st.term COLLATE NOCASE
                    """
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT term FROM search_terms ORDER BY term COLLATE NOCASE"
                ).fetchall()
        return [str(row["term"]) for row in rows]

    def list_tags(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT t.name, COUNT(ct.clip_id) AS clip_count,
                       SUM(CASE WHEN os.clip_id IS NOT NULL THEN 1 ELSE 0 END) AS selected_count
                FROM tags t
                LEFT JOIN clip_tags ct ON ct.tag_id=t.id
                LEFT JOIN output_selection os ON os.clip_id=ct.clip_id
                GROUP BY t.id ORDER BY t.name COLLATE NOCASE
                """
            ).fetchall()
        return [{"name": str(row["name"]), "clip_count": int(row["clip_count"] or 0),
                 "selected_count": int(row["selected_count"] or 0)} for row in rows]

    @staticmethod
    def _clean_tags(tags: list[str]) -> list[str]:
        cleaned: dict[str, str] = {}
        for raw in tags:
            name = " ".join(str(raw).strip().split())
            if not name:
                continue
            if len(name) > 64:
                raise ValueError("tags must be at most 64 characters")
            cleaned.setdefault(name.casefold(), name)
        if len(cleaned) > 50:
            raise ValueError("a clip may have at most 50 tags")
        return sorted(cleaned.values(), key=str.casefold)

    def set_clip_tags(self, source: str, source_id: str, tags: list[str]) -> list[str]:
        names = self._clean_tags(tags)
        with self.connect() as db:
            row = db.execute("SELECT id FROM clips WHERE source=? AND source_id=?", (source, source_id)).fetchone()
            if row is None:
                raise KeyError(f"clip not found: {source}:{source_id}")
            clip_id = int(row["id"])
            db.execute("DELETE FROM clip_tags WHERE clip_id=?", (clip_id,))
            for name in names:
                db.execute("INSERT INTO tags(name, created_at) VALUES(?,?) ON CONFLICT(name) DO NOTHING", (name, utcnow()))
                tag_id = int(db.execute("SELECT id FROM tags WHERE name=? COLLATE NOCASE", (name,)).fetchone()[0])
                db.execute("INSERT INTO clip_tags(clip_id, tag_id) VALUES(?,?)", (clip_id, tag_id))
            db.execute("DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM clip_tags ct WHERE ct.tag_id=tags.id)")
        return names

    def set_output_selected(self, clip_ids: list[int], selected: bool) -> int:
        ids = sorted({int(value) for value in clip_ids})
        if not ids:
            return 0
        with self.connect() as db:
            placeholders = ",".join("?" for _ in ids)
            status_clause = " AND status='ready'" if selected else ""
            valid = [int(row[0]) for row in db.execute(
                f"SELECT id FROM clips WHERE id IN ({placeholders}){status_clause}", ids
            ).fetchall()]
            if selected:
                db.executemany(
                    "INSERT INTO output_selection(clip_id, selected_at) VALUES(?,?) ON CONFLICT(clip_id) DO UPDATE SET selected_at=excluded.selected_at",
                    [(clip_id, utcnow()) for clip_id in valid],
                )
            elif valid:
                marks = ",".join("?" for _ in valid)
                db.execute(f"DELETE FROM output_selection WHERE clip_id IN ({marks})", valid)
        return len(valid)

    def select_output_by_tag(self, tag: str, selected: bool) -> int:
        with self.connect() as db:
            rows = db.execute(
                """SELECT c.id FROM clips c JOIN clip_tags ct ON ct.clip_id=c.id
                   JOIN tags t ON t.id=ct.tag_id WHERE t.name=? COLLATE NOCASE AND c.status='ready'""",
                (tag,),
            ).fetchall()
        return self.set_output_selected([int(row[0]) for row in rows], selected)

    def clear_output_selection(self) -> int:
        with self.connect() as db:
            count = int(db.execute("SELECT COUNT(*) FROM output_selection").fetchone()[0])
            db.execute("DELETE FROM output_selection")
        return count

    def output_selection_count(self) -> int:
        with self.connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM output_selection").fetchone()[0])

    def visual_preference_profile(self, *, min_rejected_scenes: int = 3) -> dict[str, object] | None:
        """Build a lightweight negative preference profile from manual rejects.

        Rejection is an explicit curation signal. We intentionally do not treat
        every READY clip as a positive rating; instead the profile only learns
        which broad visual-feature region the user repeatedly rejected.
        """
        keys = ("motion", "complexity", "brightness", "saturation", "visual_entropy", "cut_rate")
        sql = """
            SELECT c.status, svf.data_json
            FROM scene_visual_features svf
            JOIN scenes s ON s.id=svf.scene_id
            JOIN clips c ON c.id=s.clip_id
            WHERE c.status IN ('ready','rejected_manual')
        """
        rejected: list[list[float]] = []
        ready: list[list[float]] = []
        with self.connect() as db:
            rows = db.execute(sql).fetchall()
        for row in rows:
            try:
                data = json.loads(row["data_json"])
            except Exception:
                continue
            vec = [float(data.get(key, .0 if key == "cut_rate" else .5)) for key in keys]
            (rejected if row["status"] == "rejected_manual" else ready).append(vec)
        if len(rejected) < max(1, int(min_rejected_scenes)):
            return None
        import numpy as _np
        r = _np.asarray(rejected, dtype=float)
        profile: dict[str, object] = {
            "keys": list(keys), "rejected_count": len(rejected),
            "rejected_centroid": [float(x) for x in _np.mean(r, axis=0)],
            "rejected_scale": [float(max(.08, x)) for x in _np.std(r, axis=0)],
        }
        if ready:
            profile["ready_centroid"] = [float(x) for x in _np.mean(_np.asarray(ready, dtype=float), axis=0)]
        return profile

    def scene_candidates(
        self,
        *,
        term: str | None = None,
        clip_id: int | None = None,
        min_duration: float = 0.0,
        respect_trim: bool = True,
    ) -> list[SceneCandidate]:
        start_expr = (
            "MAX(s.start_time, COALESCE(c.usable_start, 0.0))"
            if respect_trim else "s.start_time"
        )
        end_expr = (
            "MIN(s.end_time, COALESCE(c.usable_end, s.end_time))"
            if respect_trim else "s.end_time"
        )
        clauses = [
            "c.status='ready'",
            "c.normalized_path IS NOT NULL",
            "(NOT EXISTS (SELECT 1 FROM output_selection) OR EXISTS "
            "(SELECT 1 FROM output_selection os WHERE os.clip_id=c.id))",
            f"({end_expr} - {start_expr})>=?",
        ]
        params: list[object] = [max(0.0, min_duration)]
        if term is not None:
            clauses.append("st.term=?")
            params.append(term)
        if clip_id is not None:
            clauses.append("c.id=?")
            params.append(clip_id)

        sql = f"""
            SELECT
                s.id AS scene_id, s.clip_id, s.scene_index,
                s.start_time AS original_start_time, s.end_time AS original_end_time,
                {start_expr} AS effective_start_time,
                {end_expr} AS effective_end_time,
                s.thumbnail_path, c.usable_start, c.usable_end,
                c.source_id, c.title, c.description, c.channel, c.normalized_path,
                st.term, ct.rank AS term_rank, svf.data_json AS visual_features_json,
                sai.data_json AS ai_description_json
            FROM scenes s
            JOIN clips c ON c.id=s.clip_id
            LEFT JOIN clip_terms ct ON ct.clip_id=c.id
            LEFT JOIN search_terms st ON st.id=ct.term_id
            LEFT JOIN scene_visual_features svf ON svf.scene_id=s.id
            LEFT JOIN scene_ai_descriptions sai ON sai.scene_id=s.id
            WHERE {' AND '.join(clauses)}
            ORDER BY
                CASE WHEN ct.rank IS NULL THEN 1 ELSE 0 END,
                ct.rank, c.id, s.scene_index
        """
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()

        # A scene can have multiple provenance terms. For an unscoped query,
        # collapse those joins so each physical scene appears exactly once.
        seen: set[int] = set()
        result: list[SceneCandidate] = []
        for row in rows:
            scene_id = int(row["scene_id"])
            if scene_id in seen:
                continue
            seen.add(scene_id)
            effective_start = float(row["effective_start_time"])
            effective_end = float(row["effective_end_time"])
            if effective_end <= effective_start:
                continue
            visual_features = (
                json.loads(row["visual_features_json"])
                if row["visual_features_json"] else None
            )
            # Visual accent times are stored relative to the original indexed
            # scene. If a trim clips the beginning of that scene, shift/filter
            # them so rhythm alignment never targets excluded intro footage.
            if visual_features and visual_features.get("accents"):
                original_start = float(row["original_start_time"])
                shift = effective_start - original_start
                usable_duration = effective_end - effective_start
                visual_features = dict(visual_features)
                adjusted = []
                for accent in visual_features.get("accents", []):
                    time_value = float(accent.get("time", 0.0)) - shift
                    if 0.0 <= time_value <= usable_duration:
                        item = dict(accent)
                        item["time"] = time_value
                        adjusted.append(item)
                visual_features["accents"] = adjusted

            result.append(
                SceneCandidate(
                    scene_id=scene_id,
                    clip_id=int(row["clip_id"]),
                    scene_index=int(row["scene_index"]),
                    start_time=effective_start,
                    end_time=effective_end,
                    duration=effective_end - effective_start,
                    thumbnail_path=row["thumbnail_path"],
                    source_id=str(row["source_id"]),
                    title=row["title"],
                    description=row["description"],
                    channel=row["channel"],
                    normalized_path=str(row["normalized_path"]),
                    term=row["term"],
                    term_rank=int(row["term_rank"]) if row["term_rank"] is not None else None,
                    visual_features=visual_features,
                    ai_description=(json.loads(row["ai_description_json"])
                                    if row["ai_description_json"] else None),
                )
            )
        return result

    def clip_ai_cache_key(self, clip_id: int) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT cache_key FROM clip_ai_descriptions WHERE clip_id=?", (clip_id,)
            ).fetchone()
        return str(row["cache_key"]) if row else None

    def store_clip_ai_description(
        self, clip_id: int, data: dict[str, Any], *, provider: str, model: str,
        prompt_version: str, cache_key: str,
    ) -> None:
        now = utcnow()
        scenes = data.get("scenes", []) if isinstance(data.get("scenes"), list) else []
        with self.connect() as db:
            db.execute(
                """INSERT INTO clip_ai_descriptions(
                       clip_id,provider,model,prompt_version,cache_key,data_json,updated_at)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(clip_id) DO UPDATE SET
                       provider=excluded.provider,model=excluded.model,
                       prompt_version=excluded.prompt_version,cache_key=excluded.cache_key,
                       data_json=excluded.data_json,updated_at=excluded.updated_at""",
                (clip_id, provider, model, prompt_version, cache_key,
                 json.dumps(data, ensure_ascii=False, sort_keys=True), now),
            )
            indexed = {
                int(row["scene_index"]): int(row["id"])
                for row in db.execute(
                    "SELECT id,scene_index FROM scenes WHERE clip_id=?", (clip_id,)
                ).fetchall()
            }
            db.execute("DELETE FROM scene_ai_descriptions WHERE clip_id=?", (clip_id,))
            for scene in scenes:
                if not isinstance(scene, dict):
                    continue
                try:
                    scene_id = indexed[int(scene["scene_index"])]
                except (KeyError, TypeError, ValueError):
                    continue
                # Repeat clip context on each scene row so final candidate
                # ranking can consume every returned dimension without another
                # join or silently dropping global camera/world information.
                enriched = {"clip_context": {key: value for key, value in data.items() if key != "scenes"}, **scene}
                db.execute(
                    "INSERT INTO scene_ai_descriptions(scene_id,clip_id,data_json,updated_at) VALUES(?,?,?,?)",
                    (scene_id, clip_id, json.dumps(enriched, ensure_ascii=False, sort_keys=True), now),
                )

    def load_clip_ai_description(self, clip_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT data_json FROM clip_ai_descriptions WHERE clip_id=?", (clip_id,)
            ).fetchone()
        return json.loads(row["data_json"]) if row else None



    def scene_visual_feature_ids(self) -> set[int]:
        with self.connect() as db:
            rows = db.execute("SELECT scene_id FROM scene_visual_features").fetchall()
        return {int(row["scene_id"]) for row in rows}

    def store_scene_visual_features(self, scene_id: int, features: dict[str, Any]) -> None:
        version = int(features.get("version", 1))
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO scene_visual_features(scene_id, version, data_json, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(scene_id) DO UPDATE SET
                    version=excluded.version,
                    data_json=excluded.data_json,
                    updated_at=excluded.updated_at
                """,
                (
                    scene_id,
                    version,
                    json.dumps(features, ensure_ascii=False, sort_keys=True),
                    utcnow(),
                ),
            )

    def load_scene_visual_features(self, scene_ids: list[int] | None = None) -> dict[int, dict[str, Any]]:
        clauses = ""
        params: list[object] = []
        if scene_ids is not None:
            if not scene_ids:
                return {}
            placeholders = ",".join("?" for _ in scene_ids)
            clauses = f" WHERE scene_id IN ({placeholders})"
            params = list(scene_ids)
        with self.connect() as db:
            rows = db.execute(
                "SELECT scene_id, data_json FROM scene_visual_features" + clauses,
                params,
            ).fetchall()
        out: dict[int, dict[str, Any]] = {}
        for row in rows:
            try:
                out[int(row["scene_id"])] = json.loads(row["data_json"])
            except json.JSONDecodeError:
                continue
        return out

    def list_clips(
        self,
        *,
        status: str | None = None,
        term: str | None = None,
        source: str | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: list[object] = []
        if status:
            clauses.append("c.status=?")
            params.append(status)
        if term:
            clauses.append(
                "EXISTS (SELECT 1 FROM clip_terms ct2 "
                "JOIN search_terms st2 ON st2.id=ct2.term_id "
                "WHERE ct2.clip_id=c.id AND st2.term=?)"
            )
            params.append(term)
        if source:
            clauses.append("c.source=?")
            params.append(source)
        if tag:
            clauses.append(
                "EXISTS (SELECT 1 FROM clip_tags ct3 JOIN tags t3 ON t3.id=ct3.tag_id "
                "WHERE ct3.clip_id=c.id AND t3.name=? COLLATE NOCASE)"
            )
            params.append(tag)

        params.append(max(1, int(limit)))
        sql = f"""
            SELECT
                c.id, c.source, c.source_id, c.title, c.channel, c.duration,
                c.width, c.height, c.status, c.error,
                c.original_path, c.normalized_path, c.normalized_sha256, c.duplicate_of_clip_id,
                c.usable_start, c.usable_end,
                EXISTS(SELECT 1 FROM clip_ai_descriptions cad WHERE cad.clip_id=c.id) AS ai_enhanced,
                (SELECT cad.data_json FROM clip_ai_descriptions cad WHERE cad.clip_id=c.id) AS ai_description_json,
                EXISTS(SELECT 1 FROM output_selection os WHERE os.clip_id=c.id) AS output_selected,
                (SELECT GROUP_CONCAT(t.name, char(31)) FROM clip_tags ctag
                 JOIN tags t ON t.id=ctag.tag_id WHERE ctag.clip_id=c.id) AS tags,
                COUNT(DISTINCT sc.id) AS scene_count,
                COUNT(DISTINCT se.scene_id) AS embedded_scene_count,
                GROUP_CONCAT(DISTINCT st.term) AS terms
            FROM clips c
            LEFT JOIN scenes sc ON sc.clip_id=c.id
            LEFT JOIN scene_embeddings se ON se.scene_id=sc.id
            LEFT JOIN clip_terms ct ON ct.clip_id=c.id
            LEFT JOIN search_terms st ON st.id=ct.term_id
            WHERE {' AND '.join(clauses)}
            GROUP BY c.id
            ORDER BY
                CASE c.status
                    WHEN 'ready' THEN 0
                    WHEN 'rejected_manual' THEN 1
                    ELSE 2
                END,
                c.updated_at DESC, c.id DESC
            LIMIT ?
        """
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [
            {
                "id": int(row["id"]),
                "source": str(row["source"]),
                "source_id": str(row["source_id"]),
                "title": row["title"],
                "channel": row["channel"],
                "duration": row["duration"],
                "width": row["width"],
                "height": row["height"],
                "status": str(row["status"]),
                "error": row["error"],
                "original_path": row["original_path"],
                "normalized_path": row["normalized_path"],
                "normalized_sha256": row["normalized_sha256"],
                "duplicate_of_clip_id": row["duplicate_of_clip_id"],
                "usable_start": float(row["usable_start"]) if row["usable_start"] is not None else None,
                "usable_end": float(row["usable_end"]) if row["usable_end"] is not None else None,
                "output_selected": bool(row["output_selected"]),
                "ai_enhanced": bool(row["ai_enhanced"]),
                "ai_metadata": _ai_card_summary(row["ai_description_json"]),
                "tags": sorted((x for x in str(row["tags"] or "").split(chr(31)) if x), key=str.casefold),
                "usable_duration": max(
                    0.0,
                    (float(row["usable_end"]) if row["usable_end"] is not None else float(row["duration"] or 0.0))
                    - (float(row["usable_start"]) if row["usable_start"] is not None else 0.0),
                ),
                "media_available": self.resolve_clip_media_by_id(
                    int(row["id"])
                ) is not None,
                "scene_count": int(row["scene_count"] or 0),
                "embedded_scene_count": int(row["embedded_scene_count"] or 0),
                "terms": sorted(
                    x for x in str(row["terms"] or "").split(",") if x
                ),
            }
            for row in rows
        ]

    def clip_details(self, source: str, source_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT c.*,
                       COUNT(DISTINCT s.id) AS scene_count,
                       COUNT(DISTINCT se.scene_id) AS embedded_scene_count
                FROM clips c
                LEFT JOIN scenes s ON s.clip_id=c.id
                LEFT JOIN scene_embeddings se ON se.scene_id=s.id
                WHERE c.source=? AND c.source_id=?
                GROUP BY c.id
                """,
                (source, source_id),
            ).fetchone()
            if row is None:
                return None
            term_rows = db.execute(
                """
                SELECT st.term, ct.rank, ct.discovered_at
                FROM clip_terms ct
                JOIN search_terms st ON st.id=ct.term_id
                WHERE ct.clip_id=?
                ORDER BY ct.rank, st.term COLLATE NOCASE
                """,
                (int(row["id"]),),
            ).fetchall()
            scene_rows = db.execute(
                """
                SELECT id, scene_index, start_time, end_time, duration, thumbnail_path
                FROM scenes WHERE clip_id=? ORDER BY scene_index
                """,
                (int(row["id"]),),
            ).fetchall()
            duplicate_rows = db.execute(
                """
                SELECT source, source_id, title, status
                FROM clips WHERE duplicate_of_clip_id=? ORDER BY id
                """,
                (int(row["id"]),),
            ).fetchall()
            output_selected = bool(db.execute(
                "SELECT 1 FROM output_selection WHERE clip_id=?", (int(row["id"]),)
            ).fetchone())
            tag_rows = db.execute(
                "SELECT t.name FROM clip_tags ct JOIN tags t ON t.id=ct.tag_id "
                "WHERE ct.clip_id=? ORDER BY t.name COLLATE NOCASE",
                (int(row["id"]),),
            ).fetchall()

        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}

        return {
            "id": int(row["id"]),
            "source": str(row["source"]),
            "source_id": str(row["source_id"]),
            "source_url": str(row["source_url"]),
            "title": row["title"],
            "channel": row["channel"],
            "description": row["description"],
            "duration": row["duration"],
            "width": row["width"],
            "height": row["height"],
            "upload_date": row["upload_date"],
            "status": str(row["status"]),
            "error": row["error"],
            "original_path": row["original_path"],
            "normalized_path": row["normalized_path"],
            "duplicate_of_clip_id": row["duplicate_of_clip_id"],
            "info_json_path": row["info_json_path"],
            "original_sha256": row["original_sha256"],
            "normalized_sha256": row["normalized_sha256"],
            "usable_start": float(row["usable_start"]) if row["usable_start"] is not None else None,
            "usable_end": float(row["usable_end"]) if row["usable_end"] is not None else None,
            "output_selected": output_selected,
            "ai_description": self.load_clip_ai_description(int(row["id"])),
            "tags": [str(item[0]) for item in tag_rows],
            "usable_duration": max(
                0.0,
                (float(row["usable_end"]) if row["usable_end"] is not None else float(row["duration"] or 0.0))
                - (float(row["usable_start"]) if row["usable_start"] is not None else 0.0),
            ),
            "scene_count": int(row["scene_count"] or 0),
            "embedded_scene_count": int(row["embedded_scene_count"] or 0),
            "metadata": metadata,
            "terms": [
                {
                    "term": str(item["term"]),
                    "rank": item["rank"],
                    "discovered_at": item["discovered_at"],
                }
                for item in term_rows
            ],
            "scenes": [
                {
                    "id": int(item["id"]),
                    "index": int(item["scene_index"]),
                    "start": float(item["start_time"]),
                    "end": float(item["end_time"]),
                    "duration": float(item["duration"]),
                    "thumbnail_path": item["thumbnail_path"],
                }
                for item in scene_rows
            ],
            "duplicate_aliases": [
                {
                    "source": str(item["source"]),
                    "source_id": str(item["source_id"]),
                    "title": item["title"],
                    "status": str(item["status"]),
                }
                for item in duplicate_rows
            ],
        }

    def _safe_library_file(self, value: str | None) -> Path | None:
        if not value:
            return None
        raw = Path(value).expanduser()
        path = raw if raw.is_absolute() else self.root / raw
        try:
            resolved = path.resolve()
            resolved.relative_to(self.root)
        except (ValueError, OSError):
            return None
        return resolved if resolved.is_file() else None

    def resolve_clip_media_by_id(self, clip_id: int) -> Path | None:
        """Resolve the best locally playable media for a clip.

        Prefer normalized media, follow duplicate aliases to their canonical
        clip, then fall back to the downloaded original. Finally recover older
        libraries whose DB path is stale but whose source-id-named media still
        exists under normalized/ or originals/.
        """
        visited: set[int] = set()
        current_id = int(clip_id)

        with self.connect() as db:
            while current_id not in visited:
                visited.add(current_id)
                row = db.execute(
                    """
                    SELECT id, source_id, normalized_path, original_path,
                           duplicate_of_clip_id
                    FROM clips WHERE id=?
                    """,
                    (current_id,),
                ).fetchone()
                if row is None:
                    break

                for value in (row["normalized_path"], row["original_path"]):
                    resolved = self._safe_library_file(value)
                    if resolved is not None:
                        return resolved

                duplicate_of = row["duplicate_of_clip_id"]
                if duplicate_of is not None:
                    current_id = int(duplicate_of)
                    continue

                source_id = str(row["source_id"])
                # Compatibility/recovery for old DBs with stale path columns.
                # source_id is controlled metadata but still sanitize basename.
                safe_id = Path(source_id).name
                for directory in (self.normalized_dir, self.originals_dir):
                    matches = sorted(
                        path for path in directory.glob(f"{safe_id}.*")
                        if path.is_file()
                    )
                    if matches:
                        return matches[0]
                break
        return None

    def resolve_clip_media(self, source: str, source_id: str) -> Path | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT id FROM clips WHERE source=? AND source_id=?",
                (source, source_id),
            ).fetchone()
        if row is None:
            return None
        return self.resolve_clip_media_by_id(int(row["id"]))

    def clip_media_diagnostic(self, source: str, source_id: str) -> dict[str, Any]:
        """Return enough state to explain why Studio playback is unavailable."""
        with self.connect() as db:
            row = db.execute(
                """
                SELECT id, source, source_id, status, normalized_path,
                       original_path, duplicate_of_clip_id, error
                FROM clips WHERE source=? AND source_id=?
                """,
                (source, source_id),
            ).fetchone()
        if row is None:
            return {
                "found": False,
                "source": source,
                "source_id": source_id,
                "library": str(self.root),
            }
        resolved = self.resolve_clip_media_by_id(int(row["id"]))
        return {
            "found": True,
            "source": str(row["source"]),
            "source_id": str(row["source_id"]),
            "status": str(row["status"]),
            "normalized_path": row["normalized_path"],
            "original_path": row["original_path"],
            "duplicate_of_clip_id": row["duplicate_of_clip_id"],
            "error": row["error"],
            "resolved_media": str(resolved) if resolved else None,
            "library": str(self.root),
        }

    def set_clip_trim(
        self,
        source: str,
        source_id: str,
        *,
        usable_start: float | None,
        usable_end: float | None,
    ) -> dict[str, Any]:
        """Persist non-destructive usable In/Out points for a source clip."""
        with self.connect() as db:
            row = db.execute(
                "SELECT id, duration FROM clips WHERE source=? AND source_id=?",
                (source, source_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown clip: {source}:{source_id}")

            duration = float(row["duration"] or 0.0)
            start = 0.0 if usable_start is None else max(0.0, float(usable_start))
            end = duration if usable_end is None else float(usable_end)
            if duration > 0:
                start = min(start, duration)
                end = min(max(0.0, end), duration)
            if end <= start + 0.05:
                raise ValueError("trim Out point must be at least 0.05s after In point")

            # Store NULL for natural media boundaries so an ingest metadata
            # refresh can extend the clip without leaving a stale artificial cap.
            stored_start = None if start <= 1e-6 else start
            stored_end = None if duration > 0 and abs(end - duration) <= 1e-3 else end
            db.execute(
                """
                UPDATE clips
                SET usable_start=?, usable_end=?, updated_at=?
                WHERE id=?
                """,
                (stored_start, stored_end, utcnow(), int(row["id"])),
            )

        details = self.clip_details(source, source_id)
        assert details is not None
        return details

    def clear_clip_trim(self, source: str, source_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT id FROM clips WHERE source=? AND source_id=?",
                (source, source_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown clip: {source}:{source_id}")
            db.execute(
                "UPDATE clips SET usable_start=NULL, usable_end=NULL, updated_at=? WHERE id=?",
                (utcnow(), int(row["id"])),
            )
        details = self.clip_details(source, source_id)
        assert details is not None
        return details

    def is_manually_rejected(self, source: str, source_id: str) -> bool:
        record = self.get_clip(source, source_id)
        return bool(record and record.status == "rejected_manual")

    def reject_clip(
        self,
        source: str,
        source_id: str,
        *,
        reason: str = "manually rejected",
    ) -> ClipRecord:
        record = self.get_clip(source, source_id)
        if record is None:
            raise KeyError(f"clip not found: {source}:{source_id}")
        with self.connect() as db:
            db.execute("DELETE FROM output_selection WHERE clip_id=?", (record.id,))
            db.execute(
                """
                UPDATE clips
                SET status='rejected_manual', error=?, updated_at=?
                WHERE id=?
                """,
                (reason[:4000], utcnow(), record.id),
            )
        updated = self.get_clip_by_id(record.id)
        assert updated is not None
        return updated

    def restore_clip(self, source: str, source_id: str) -> ClipRecord:
        record = self.get_clip(source, source_id)
        if record is None:
            raise KeyError(f"clip not found: {source}:{source_id}")

        normalized_ok = bool(
            record.normalized_path
            and (self.root / record.normalized_path).is_file()
        )
        original_ok = bool(
            record.original_path
            and (self.root / record.original_path).is_file()
        )
        if normalized_ok:
            status = "ready"
        elif original_ok:
            status = "downloaded"
        else:
            status = "discovered"

        with self.connect() as db:
            db.execute(
                """
                UPDATE clips SET status=?, error=NULL, updated_at=?
                WHERE id=?
                """,
                (status, utcnow(), record.id),
            )
        updated = self.get_clip_by_id(record.id)
        assert updated is not None
        return updated

    def _tracked_paths_for_clip_ids(
        self,
        db: sqlite3.Connection,
        clip_ids: list[int],
        *,
        keep_original: bool,
    ) -> list[Path]:
        if not clip_ids:
            return []
        placeholders = ",".join("?" for _ in clip_ids)
        rows = db.execute(
            f"""
            SELECT source_id, original_path, normalized_path, info_json_path
            FROM clips WHERE id IN ({placeholders})
            """,
            clip_ids,
        ).fetchall()

        candidates: set[Path] = set()
        for row in rows:
            if not keep_original and row["original_path"]:
                candidates.add(self.root / str(row["original_path"]))
            if row["normalized_path"]:
                normalized_value = str(row["normalized_path"])
                original_value = str(row["original_path"]) if row["original_path"] else None
                # With direct-source media, the legacy normalized_path column
                # intentionally points at original_path. --keep-original must
                # not delete that shared canonical file.
                if not (keep_original and original_value == normalized_value):
                    candidates.add(self.root / normalized_value)
            if not keep_original and row["info_json_path"]:
                candidates.add(self.root / str(row["info_json_path"]))

            source_id = str(row["source_id"])
            thumb_dir = self.thumbnails_dir / source_id
            if thumb_dir.exists():
                candidates.add(thumb_dir)
            ai_thumb = self.metadata_dir / "ai-thumbnails" / f"{source_id}.jpg"
            if ai_thumb.exists():
                candidates.add(ai_thumb)

        # Include DB-recorded thumbnails for older/custom layouts.
        thumb_rows = db.execute(
            f"""
            SELECT thumbnail_path FROM scenes
            WHERE clip_id IN ({placeholders}) AND thumbnail_path IS NOT NULL
            """,
            clip_ids,
        ).fetchall()
        for row in thumb_rows:
            candidates.add(self.root / str(row["thumbnail_path"]))

        # Never allow a corrupt DB path to escape the library root.
        safe: list[Path] = []
        root = self.root.resolve()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root)
            except (ValueError, OSError):
                continue
            if resolved.exists():
                safe.append(resolved)

        # If a directory is staged, don't separately stage descendants.
        safe.sort(key=lambda path: (len(path.parts), str(path)))
        result: list[Path] = []
        for path in safe:
            if any(parent == path or parent in path.parents for parent in result):
                continue
            result.append(path)
        return result

    def delete_clip(
        self,
        source: str,
        source_id: str,
        *,
        dry_run: bool = False,
        keep_original: bool = False,
    ) -> dict[str, Any]:
        """Hard-delete a physical clip and duplicate aliases.

        Tracked files are atomically moved to an in-library staging directory
        before the database delete. If the DB transaction fails, the moves are
        rolled back. Duplicate aliases pointing at the same physical asset are
        deleted with the canonical row so they cannot retain broken paths.
        """
        details = self.clip_details(source, source_id)
        if details is None:
            raise KeyError(f"clip not found: {source}:{source_id}")
        root_id = int(details["id"])

        with self.connect() as db:
            # Recursively include aliases of aliases, though current ingest only
            # creates one duplicate level.
            clip_ids = [root_id]
            cursor = 0
            while cursor < len(clip_ids):
                rows = db.execute(
                    "SELECT id FROM clips WHERE duplicate_of_clip_id=?",
                    (clip_ids[cursor],),
                ).fetchall()
                for row in rows:
                    child = int(row["id"])
                    if child not in clip_ids:
                        clip_ids.append(child)
                cursor += 1
            paths = self._tracked_paths_for_clip_ids(
                db, clip_ids, keep_original=keep_original
            )
            aliases = db.execute(
                f"""
                SELECT source, source_id FROM clips
                WHERE id IN ({','.join('?' for _ in clip_ids)})
                ORDER BY id
                """,
                clip_ids,
            ).fetchall()

        plan = {
            "source": source,
            "source_id": source_id,
            "clip_ids": clip_ids,
            "records": [
                {"source": str(row["source"]), "source_id": str(row["source_id"])}
                for row in aliases
            ],
            "files": [str(path.relative_to(self.root)) for path in paths],
            "keep_original": keep_original,
            "dry_run": dry_run,
        }
        if dry_run:
            return plan

        trash_root = self.metadata_dir / ".delete-trash" / uuid.uuid4().hex
        moved: list[tuple[Path, Path]] = []
        try:
            for original in paths:
                relative = original.relative_to(self.root)
                staged = trash_root / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                os.replace(original, staged)
                moved.append((original, staged))

            with self.connect() as db:
                placeholders = ",".join("?" for _ in clip_ids)
                db.execute(
                    f"DELETE FROM clips WHERE id IN ({placeholders})",
                    clip_ids,
                )
                # Keep the term table tidy after cascaded clip_terms deletion.
                db.execute(
                    """
                    DELETE FROM search_terms
                    WHERE NOT EXISTS (
                        SELECT 1 FROM clip_terms WHERE clip_terms.term_id=search_terms.id
                    )
                    """
                )
        except Exception:
            for original, staged in reversed(moved):
                if staged.exists():
                    original.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, original)
            shutil.rmtree(trash_root, ignore_errors=True)
            raise
        else:
            shutil.rmtree(trash_root, ignore_errors=True)
            parent = trash_root.parent
            try:
                parent.rmdir()
            except OSError:
                pass

        return plan


    def scene_embedding_ids(self, *, model: str, pretrained: str) -> set[int]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT scene_id FROM scene_embeddings
                WHERE model=? AND pretrained=?
                """,
                (model, pretrained),
            ).fetchall()
        return {int(row["scene_id"]) for row in rows}

    def store_scene_embedding(
        self,
        scene_id: int,
        *,
        model: str,
        pretrained: str,
        vector: "Any",
    ) -> None:
        import numpy as np

        array = np.asarray(vector, dtype=np.float32).reshape(-1)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO scene_embeddings(
                    scene_id, model, pretrained, dim, vector, updated_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(scene_id, model, pretrained) DO UPDATE SET
                    dim=excluded.dim,
                    vector=excluded.vector,
                    updated_at=excluded.updated_at
                """,
                (
                    scene_id,
                    model,
                    pretrained,
                    int(array.size),
                    array.tobytes(),
                    utcnow(),
                ),
            )

    def load_scene_embeddings(
        self,
        scene_ids: list[int],
        *,
        model: str,
        pretrained: str,
    ) -> dict[int, "Any"]:
        import numpy as np

        if not scene_ids:
            return {}
        placeholders = ",".join("?" for _ in scene_ids)
        params: list[object] = [model, pretrained, *scene_ids]
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT scene_id, dim, vector
                FROM scene_embeddings
                WHERE model=? AND pretrained=?
                  AND scene_id IN ({placeholders})
                """,
                params,
            ).fetchall()
        result: dict[int, Any] = {}
        for row in rows:
            arr = np.frombuffer(row["vector"], dtype=np.float32, count=int(row["dim"])).copy()
            result[int(row["scene_id"])] = arr
        return result

    def embedding_models(self) -> list[tuple[str, str, int]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT model, pretrained, COUNT(*) AS n
                FROM scene_embeddings
                GROUP BY model, pretrained
                ORDER BY n DESC, model, pretrained
                """
            ).fetchall()
        return [
            (str(row["model"]), str(row["pretrained"]), int(row["n"]))
            for row in rows
        ]

    def ai_report(self, *, term: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Return persisted AI discovery scores for inspectable ranking decisions."""
        clauses = ["c.metadata_json IS NOT NULL"]
        params: list[object] = []
        if term is not None:
            clauses.append("st.term=?")
            params.append(term)
        sql = f"""
            SELECT c.source_id, c.title, c.status, c.metadata_json,
                   st.term, ct.rank
            FROM clips c
            JOIN clip_terms ct ON ct.clip_id=c.id
            JOIN search_terms st ON st.id=ct.term_id
            WHERE {' AND '.join(clauses)}
            ORDER BY c.updated_at DESC
        """
        rows: list[dict[str, Any]] = []
        with self.connect() as db:
            for row in db.execute(sql, params):
                try:
                    metadata = json.loads(row["metadata_json"] or "{}")
                except json.JSONDecodeError:
                    continue
                if "_tubeviz_ai_score" not in metadata:
                    continue
                rows.append({
                    "source_id": str(row["source_id"]),
                    "title": row["title"],
                    "status": str(row["status"]),
                    "term": str(row["term"]),
                    "rank": row["rank"],
                    "query": metadata.get("_tubeviz_query"),
                    "score": metadata.get("_tubeviz_ai_score"),
                    "visual": metadata.get("_tubeviz_ai_visual_score"),
                    "negative": metadata.get("_tubeviz_ai_negative_score"),
                    "metadata": metadata.get("_tubeviz_ai_metadata_score"),
                    "diversity": metadata.get("_tubeviz_ai_diversity_penalty"),
                })
                if len(rows) >= max(1, limit):
                    break
        rows.sort(key=lambda item: float(item["score"] or -999), reverse=True)
        return rows

    def stats(self) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute("SELECT status, COUNT(*) AS n FROM clips GROUP BY status").fetchall()
            result = {str(row["status"]): int(row["n"]) for row in rows}
            result["clips"] = int(db.execute("SELECT COUNT(*) FROM clips").fetchone()[0])
            result["scenes"] = int(db.execute("SELECT COUNT(*) FROM scenes").fetchone()[0])
            result["terms"] = int(db.execute("SELECT COUNT(*) FROM search_terms").fetchone()[0])
            result["embeddings"] = int(db.execute("SELECT COUNT(*) FROM scene_embeddings").fetchone()[0])
            result["visual_features"] = int(
                db.execute("SELECT COUNT(*) FROM scene_visual_features").fetchone()[0]
            )
            result["tags"] = int(db.execute("SELECT COUNT(*) FROM tags").fetchone()[0])
            result["output_selected"] = int(db.execute("SELECT COUNT(*) FROM output_selection").fetchone()[0])
        return result

    @staticmethod
    def _record(row: sqlite3.Row) -> ClipRecord:
        return ClipRecord(
            id=int(row["id"]),
            source=str(row["source"]),
            source_id=str(row["source_id"]),
            source_url=str(row["source_url"]),
            title=row["title"],
            channel=row["channel"],
            description=row["description"],
            duration=row["duration"],
            width=row["width"],
            height=row["height"],
            upload_date=row["upload_date"],
            original_path=row["original_path"],
            normalized_path=row["normalized_path"],
            original_sha256=row["original_sha256"],
            normalized_sha256=row["normalized_sha256"],
            usable_start=float(row["usable_start"]) if row["usable_start"] is not None else None,
            usable_end=float(row["usable_end"]) if row["usable_end"] is not None else None,
            status=str(row["status"]),
            error=row["error"],
        )
