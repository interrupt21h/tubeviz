# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from tubeviz.models import (
    CompositeLayer,
    DirectedTimeline,
    SceneSelection,
    TrackAnalysis,
    VideoTransform,
)
from tubeviz.native_render import NativeRenderError, _resolve_media, write_native_manifest


def _track(tmp_path: Path) -> TrackAnalysis:
    return TrackAnalysis(
        source=str(tmp_path / "song.wav"),
        duration=4.0,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120.0,
        beats=[0.0, 0.5],
        bars=[0.0],
        sections=[],
        events=[],
    )


def test_current_basename_media_file_resolves_under_normalized(tmp_path: Path):
    library = tmp_path / "library"
    normalized = library / "normalized"
    normalized.mkdir(parents=True)
    expected = normalized / "np7nJ5HsYuw.mp4"
    expected.write_bytes(b"video")

    resolved = _resolve_media(
        library,
        "np7nJ5HsYuw.mp4",
        media_url="/media/np7nJ5HsYuw.mp4",
        materialized=False,
    )
    assert resolved == expected.resolve()


def test_materialized_basename_resolves_under_transforms(tmp_path: Path):
    library = tmp_path / "library"
    transforms = library / "transforms"
    transforms.mkdir(parents=True)
    expected = transforms / "baked.mp4"
    expected.write_bytes(b"video")

    resolved = _resolve_media(
        library,
        "baked.mp4",
        media_url="/transforms/baked.mp4",
        materialized=True,
    )
    assert resolved == expected.resolve()


def test_manifest_uses_normalized_mount_for_current_timeline_convention(tmp_path: Path):
    library = tmp_path / "library"
    normalized = library / "normalized"
    normalized.mkdir(parents=True)
    primary = normalized / "a.mp4"
    companion = normalized / "b.mp4"
    primary.write_bytes(b"a")
    companion.write_bytes(b"b")

    scene = SceneSelection(
        section_index=0,
        time=0.0,
        term="archive",
        clip_id=1,
        scene_id=1,
        scene_index=0,
        source_id="a",
        media_file="a.mp4",
        media_url="/media/a.mp4",
        start=0.0,
        end=2.0,
        duration=2.0,
        layers=[
            CompositeLayer(
                clip_id=2,
                scene_id=2,
                scene_index=0,
                source_id="b",
                media_file="b.mp4",
                media_url="/media/b.mp4",
                start=1.0,
                end=3.0,
                duration=2.0,
            )
        ],
    )
    timeline = DirectedTimeline(track=_track(tmp_path), cues=[], scene_plan=[scene])
    manifest = write_native_manifest(timeline, library, tmp_path / "native.tsv").read_text()

    assert str(primary.resolve()) in manifest
    assert str(companion.resolve()) in manifest


def test_manifest_uses_transforms_mount_after_materialization(tmp_path: Path):
    library = tmp_path / "library"
    transforms = library / "transforms"
    transforms.mkdir(parents=True)
    baked = transforms / "baked.mp4"
    baked.write_bytes(b"x")

    scene = SceneSelection(
        section_index=0,
        time=0.0,
        term="archive",
        clip_id=1,
        scene_id=1,
        scene_index=0,
        source_id="a",
        media_file="baked.mp4",
        media_url="/transforms/baked.mp4",
        start=0.0,
        end=2.0,
        duration=2.0,
        transform=VideoTransform(materialized=True, transform_id="abc"),
    )
    timeline = DirectedTimeline(track=_track(tmp_path), cues=[], scene_plan=[scene])
    manifest = write_native_manifest(timeline, library, tmp_path / "native.tsv").read_text()
    assert str(baked.resolve()) in manifest


def test_missing_media_error_reports_all_lookup_locations(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    scene = SceneSelection(
        section_index=0,
        time=0.0,
        term="archive",
        clip_id=1,
        scene_id=1,
        scene_index=0,
        source_id="missing-id",
        media_file="missing.mp4",
        media_url="/media/missing.mp4",
        start=0.0,
        end=1.0,
        duration=1.0,
    )
    timeline = DirectedTimeline(track=_track(tmp_path), cues=[], scene_plan=[scene])
    with pytest.raises(NativeRenderError) as exc:
        write_native_manifest(timeline, library, tmp_path / "native.tsv")
    message = str(exc.value)
    assert "missing-id" in message
    assert str((library / "normalized" / "missing.mp4").resolve()) in message


def test_original_media_url_resolves_under_originals(tmp_path: Path):
    library = tmp_path / "library"
    originals = library / "originals"
    originals.mkdir(parents=True)
    expected = originals / "direct.webm"
    expected.write_bytes(b"video")

    resolved = _resolve_media(
        library,
        "originals/direct.webm",
        media_url="/originals/direct.webm",
        materialized=False,
    )
    assert resolved == expected.resolve()
