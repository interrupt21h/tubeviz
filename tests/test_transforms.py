# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tubeviz.models import DirectedTimeline, SceneSelection, Section, TrackAnalysis, VideoTransform
from tubeviz.transforms import (
    MaterializeConfig,
    TransformConfig,
    attach_transform_plan,
    materialize_selection,
    plan_transform,
)


def _section(index: int = 0, *, label: str = "peak", energy: float = .85) -> Section:
    return Section(
        index=index, start=index * 8.0, end=(index + 1) * 8.0,
        energy=energy, label=label, key="F minor", brightness=.65,
        onset_density=1.8,
    )


def _selection(index: int = 0, occurrence: int = 1) -> SceneSelection:
    return SceneSelection(
        section_index=index, time=index * 8.0, term="archive", motif_id="motif_01",
        occurrence=occurrence, clip_id=1, scene_id=10 + index, scene_index=index,
        source_id="src", media_file="src.mp4", media_url="/media/src.mp4",
        start=1.0, end=6.0, duration=5.0,
    )


def test_transform_planning_is_deterministic_and_energy_aware():
    a = plan_transform(_section(), _selection(), TransformConfig(intensity=1.0))
    b = plan_transform(_section(), _selection(), TransformConfig(intensity=1.0))
    assert a == b
    assert a.zoom > 1.0
    assert a.playback_rate >= 1.0
    assert a.glitch > 0
    assert a.ripple > 0
    assert a.posterize > 0
    assert a.edge > 0
    assert a.strobe > 0
    assert a.shutter > 0
    assert abs(a.hue_degrees) <= 10.0


def test_zero_transform_intensity_is_identity():
    assert plan_transform(_section(), _selection(), TransformConfig(intensity=0.0)) == VideoTransform()


def test_attach_transform_plan_updates_scene_cue_payload():
    section = _section()
    scene = _selection()
    track = TrackAnalysis(
        source="/tmp/song.wav", duration=8.0, sample_rate=22050, hop_length=512,
        tempo_bpm=120.0, beats=[], bars=[], sections=[section], events=[],
    )
    from tubeviz.models import VisualCue
    timeline = DirectedTimeline(
        track=track, scene_plan=[scene],
        cues=[VisualCue(time=0.0, action="play_scene", parameters=scene.model_dump(mode="json"))],
    )
    result = attach_transform_plan(timeline, TransformConfig(intensity=1.0))
    assert result.scene_plan[0].transform.zoom > 1.0
    assert result.cues[0].parameters["transform"]["zoom"] == result.scene_plan[0].transform.zoom


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")
def test_materialize_selection_real_ffmpeg(tmp_path: Path):
    root = tmp_path / "library"
    normalized = root / "normalized"
    normalized.mkdir(parents=True)
    source = normalized / "src.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
    )
    selection = _selection().model_copy(update={
        "start": .2, "end": 2.8, "duration": 2.6,
        "transform": VideoTransform(
            playback_rate=1.25, reverse=True, mirror=True, zoom=1.18,
            pan_x=.2, pan_y=-.1, rotation_degrees=1.5,
            brightness=1.1, contrast=1.2, saturation=1.3, hue_degrees=12,
            blur_px=.5, noise=.1, feedback=.25, glitch=.3, blend_mode="screen",
        ),
    })
    rendered = materialize_selection(
        selection, library_root=root,
        config=MaterializeConfig(width=320, height=180, fps=30, preset="veryfast"),
    )
    output = root / "transforms" / rendered.media_file
    assert output.exists() and output.stat().st_size > 1000
    assert rendered.media_url.startswith("/transforms/")
    assert rendered.transform.materialized is True
    assert rendered.transform.playback_rate == 1.0
    assert rendered.start == 0.0
