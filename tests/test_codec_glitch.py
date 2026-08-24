# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tubeviz.codec_glitch as cg
from tubeviz.codec_glitch import CodecGlitchConfig
from tubeviz.library import SceneCandidate
from tubeviz.models import DirectedTimeline, SceneSelection, Section, TrackAnalysis, VisualDirection
from tubeviz.visual_director import build_visual_direction


def candidate() -> SceneCandidate:
    return SceneCandidate(
        scene_id=7, clip_id=7, scene_index=0,
        start_time=0.0, end_time=8.0, duration=8.0,
        thumbnail_path=None, source_id="clip7", title="clip", description=None,
        channel=None, normalized_path="normalized/clip7.mp4", term="techno", term_rank=1,
        visual_features={
            "motion": .7, "codec_motion": .8,
            "motion_direction_x": .3, "motion_direction_y": -.2,
            "codec_motion_direction_x": .6, "codec_motion_direction_y": -.1,
            "complexity": .7, "brightness": .5, "saturation": .7,
            "dominant_hue": 210, "visual_entropy": .6, "warmth": .3,
            "palette": ["#102040"], "accents": [],
        },
    )


def section(label="peak", vibe="driving") -> Section:
    return Section(
        index=2, start=0, end=8, energy=.9, label=label, brightness=.6,
        onset_density=.65, local_tempo_bpm=128, bass_weight=.7,
        percussive_ratio=.75, tonal_stability=.45, noisiness=.45,
        spectral_contrast=.6, vibe=vibe,
    )


def test_codec_effects_off_by_default():
    direction = build_visual_direction(
        candidate(), section(), rhythm_alignment=.8, source_playback_rate=1,
        transition=.5, occurrence=1, shot_index_in_section=0,
    )
    assert direction.codec_effects == []


def test_musical_peak_schedules_sparse_codec_effects():
    direction = build_visual_direction(
        candidate(), section(), rhythm_alignment=.8, source_playback_rate=1,
        transition=.5, occurrence=1, shot_index_in_section=0,
        codec_glitch_mode="musical", codec_glitch_intensity=.7,
    )
    kinds = {effect.kind for effect in direction.codec_effects}
    assert "mv_explode" in kinds
    assert "datamosh" in kinds
    assert len(direction.codec_effects) <= 2
    assert all(0 <= effect.start < effect.end <= 1 for effect in direction.codec_effects)


def test_subtle_breakdown_has_no_codec_effects():
    direction = build_visual_direction(
        candidate(), section("breakdown", "ambient"), rhythm_alignment=.5,
        source_playback_rate=1, transition=.1, occurrence=1, shot_index_in_section=0,
        codec_glitch_mode="subtle", codec_glitch_intensity=.7,
    )
    assert direction.codec_effects == []


def test_codec_doctor_reports_tools(monkeypatch):
    monkeypatch.setattr(cg.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cg, "_version", lambda name: f"{name} 0.10.2")
    info = cg.codec_doctor()
    assert info["available"] is True
    assert info["ffedit"].endswith("ffedit")
    assert "MPEG-4 Part 2" in info["note"]


def _selection() -> SceneSelection:
    return SceneSelection(
        section_index=0, time=0.0, term="test", clip_id=1, scene_id=1,
        scene_index=0, source_id="a", media_file="a.mp4", media_url="/media/a.mp4",
        start=1.0, end=3.0, duration=2.0,
        direction=VisualDirection(codec_effects=[
            cg.CodecEffect(kind="mv_shear", amount=.6, start=.2, end=.8, seed=3)
        ]),
    )


def test_materialize_codec_selection_caches_and_rewrites_media(tmp_path: Path, monkeypatch):
    library = tmp_path / "library"
    normalized = library / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "a.mp4").write_bytes(b"source")
    monkeypatch.setattr(cg, "codec_doctor", lambda cfg=None: {
        "available": True, "ffedit_version": "ffglitch-0.10.2",
    })

    calls = []
    def fake_run(command, timeout=None):
        calls.append(command)
        # All three stages name their output as the final command argument.
        out = Path(command[-1])
        if command[0] in {"ffmpeg", "ffedit"} and out.suffix in {".avi", ".mp4"}:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"generated")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cg, "_run", fake_run)

    result = cg.materialize_codec_selection(
        _selection(), library_root=library,
        config=CodecGlitchConfig(width=320, height=180, fps=30),
    )
    assert result.codec_materialization.materialized is True
    assert result.media_url.startswith("/codec-glitch/")
    assert result.start == 0
    assert result.end == pytest.approx(2.0)
    assert (library / "codec-glitch" / result.media_file).is_file()
    ffedit_call = next(c for c in calls if c[0] == "ffedit")
    assert "-f" in ffedit_call and "mv" in ffedit_call
    assert "-s" in ffedit_call and "-sp" not in ffedit_call


def test_codec_timeline_updates_scene_cues(tmp_path: Path, monkeypatch):
    sel = _selection()
    timeline = DirectedTimeline(
        track=TrackAnalysis(
            source="song.wav", duration=4, sample_rate=22050, hop_length=512,
            tempo_bpm=120, beats=[0,.5], bars=[0], sections=[], events=[],
        ),
        cues=[], scene_plan=[sel],
    )
    monkeypatch.setattr(cg, "materialize_codec_selection", lambda selection, **kwargs: selection.model_copy(update={"media_file":"cached.mp4", "media_url":"/codec-glitch/cached.mp4"}))
    result = cg.materialize_codec_timeline(timeline, library_root=tmp_path)
    assert result.scene_plan[0].media_file == "cached.mp4"


def test_codec_motion_parser(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.mp4"; source.write_bytes(b"x")
    def fake_prepare(source, selection, output, cfg):
        output.write_bytes(b"avi")
    monkeypatch.setattr(cg, "_prepare_working_clip", fake_prepare)
    def fake_run(command, timeout=None):
        if "-e" in command:
            path = Path(command[command.index("-e")+1])
            path.write_text(json.dumps({"streams":[{"frames":[
                {"mv":{"forward":[[[1,0],[2,0]],[[1,1],None]]}},
                {"mv":{"forward":[[[8,0],[7,1]],[[9,0],[8,-1]]]}},
            ]}]}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cg, "_run", fake_run)
    stats = cg.export_codec_motion(source, start=0, end=1, config=CodecGlitchConfig(fps=2))
    assert stats["codec_motion"] > 0
    assert stats["codec_motion_direction_x"] > 0
    assert stats["codec_motion_frames"] == 2


def test_generated_ffglitch_script_handles_overflow_and_four_mv_macroblocks():
    assert 'frame.mv.overflow = "truncate"' in cg._FFGLITCH_SCRIPT
    assert 'typeof cell[0] === "number"' in cg._FFGLITCH_SCRIPT
    assert 'for (let k=0; k<cell.length; k++)' in cg._FFGLITCH_SCRIPT



def test_generated_ffglitch_script_embeds_fractional_payload_without_sp_parser():
    effects = [
        cg.CodecEffect(
            kind="mv_wave",
            amount=0.07678046181634314,
            start=0.3,
            end=0.91,
            seed=17,
        )
    ]
    script = cg._render_ffglitch_script(effects, frames=73, seed=42)
    assert script.startswith("const TUBEVIZ_PARAMS = ")
    assert '"amount":0.07678046181634314' in script
    assert '"start":0.3' in script
    assert '"frames":73' in script
    assert '"seed":42' in script
    assert 'params = (typeof TUBEVIZ_PARAMS !== "undefined")' in script


def test_transplicate_never_passes_effect_payload_via_sp(tmp_path: Path, monkeypatch):
    working = tmp_path / "in.avi"
    working.write_bytes(b"avi")
    glitched = tmp_path / "out.avi"
    effect = cg.CodecEffect(kind="mv_wave", amount=.12345, start=.2, end=.8, seed=9)
    calls = []

    def fake_run(command, timeout=None):
        calls.append(command)
        glitched.write_bytes(b"out")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cg, "_run", fake_run)
    cg._transplicate(
        working, glitched, [effect], CodecGlitchConfig(),
        frames=60, seed=123, workdir=tmp_path,
    )
    command = calls[0]
    assert "-sp" not in command
    script_path = Path(command[command.index("-s") + 1])
    text = script_path.read_text()
    assert '"amount":0.12345' in text


def test_finalize_retries_without_faststart(tmp_path: Path, monkeypatch):
    glitched = tmp_path / "glitched.avi"
    glitched.write_bytes(b"avi")
    output = tmp_path / "final.mp4"
    calls = []

    def fake_run(command, timeout=None):
        calls.append(command)
        if "+faststart" in command:
            return SimpleNamespace(
                returncode=1, stdout="",
                stderr="Unable to re-open output file for shifting data",
            )
        Path(command[-1]).write_bytes(b"valid-mp4")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cg, "_run", fake_run)
    cg._finalize(glitched, output, CodecGlitchConfig())
    assert output.read_bytes() == b"valid-mp4"
    assert len(calls) == 2
    assert "+faststart" in calls[0]
    assert "+faststart" not in calls[1]


def test_publish_cache_file_is_atomic_and_cleans_partial(tmp_path: Path):
    source = tmp_path / "local-final.mp4"
    source.write_bytes(b"codec-cache")
    cache = tmp_path / "library" / "codec-glitch" / "abc.mp4"
    cg._publish_cache_file(source, cache)
    assert cache.read_bytes() == b"codec-cache"
    assert not (cache.parent / ".abc.mp4.partial").exists()
