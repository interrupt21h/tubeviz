# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.models import DirectedTimeline, SceneSelection, TrackAnalysis, VectorEffect, VisualDirection
from tubeviz.native_render import write_native_manifest


def test_native_manifest_serializes_vector_effects(tmp_path: Path):
    library = tmp_path / "library"
    normalized = library / "normalized"
    normalized.mkdir(parents=True)
    media = normalized / "a.mp4"
    media.write_bytes(b"video")

    track = TrackAnalysis(
        source=str(tmp_path / "song.wav"),
        duration=4.0,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120,
        beats=[0, .5, 1],
        bars=[0],
        sections=[],
        events=[],
    )
    scene = SceneSelection(
        section_index=0,
        time=0,
        term="test",
        clip_id=1,
        scene_id=1,
        scene_index=0,
        source_id="a",
        media_file="a.mp4",
        media_url="/media/a.mp4",
        start=0,
        end=2,
        duration=2,
        direction=VisualDirection(
            vector_effects=[
                VectorEffect(
                    kind="delaunay_fracture",
                    amount=.8,
                    opacity=.3,
                    seed=42,
                    count=24,
                    line_width=1.5,
                    displace=True,
                    parameters={"motion_x": .4, "motion_y": -.2},
                    automation={
                        "amount": [(0, .1), (.5, .5), (1, .8)],
                        "explode": [(0, 0), (1, .7)],
                    },
                )
            ]
        ),
    )
    timeline = DirectedTimeline(track=track, cues=[], scene_plan=[scene])
    text = write_native_manifest(timeline, library, tmp_path / "native.tsv").read_text()
    vec = next(line for line in text.splitlines() if line.startswith("VEC\t"))
    fields = vec.split("\t")
    assert fields[1] == "delaunay_fracture"
    assert fields[4] == "42"
    assert fields[8] == "1"
    assert float(fields[15]) == .7


def test_native_manifest_prunes_legacy_visible_vector_stack(tmp_path: Path):
    library = tmp_path / "library"
    normalized = library / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "a.mp4").write_bytes(b"video")
    track = TrackAnalysis(
        source=str(tmp_path / "song.wav"), duration=4.0, sample_rate=22050,
        hop_length=512, tempo_bpm=120, beats=[0, .5], bars=[0], sections=[], events=[],
    )
    direction = VisualDirection(
        effect_family="hyper",
        narrative_role="develop",
        vector_effects=[
            VectorEffect(kind="contours", amount=.5),
            VectorEffect(kind="semantic_outline", amount=.5),
            VectorEffect(kind="flow_ribbons", amount=.5),
            VectorEffect(kind="delaunay_fracture", amount=.5),
            VectorEffect(kind="vector_displacement", amount=.5, visible=False, displace=True),
        ],
    )
    scene = SceneSelection(
        section_index=0, time=0, term="test", clip_id=1, scene_id=1,
        scene_index=0, source_id="a", media_file="a.mp4", media_url="/media/a.mp4",
        start=0, end=2, duration=2, direction=direction,
    )
    timeline = DirectedTimeline(track=track, cues=[], scene_plan=[scene])
    text = write_native_manifest(timeline, library, tmp_path / "native.tsv").read_text()
    kinds = [line.split("\t")[1] for line in text.splitlines() if line.startswith("VEC\t")]
    assert kinds == ["flow_ribbons", "vector_displacement"]


def test_native_manifest_serializes_creative_treatment(tmp_path: Path):
    from tubeviz.models import CreativeEffectPlan, SemanticVisualProfile

    library = tmp_path / "library"
    originals = library / "originals"
    originals.mkdir(parents=True)
    (originals / "a.webm").write_bytes(b"video")
    track = TrackAnalysis(
        source=str(tmp_path / "song.wav"), duration=4.0, sample_rate=22050,
        hop_length=512, tempo_bpm=120, beats=[0, .5], bars=[0], sections=[], events=[],
    )
    creative = CreativeEffectPlan(
        flow_warp=.7, temporal_echo=.4, camera_energy=.6,
        camera_target_x=.63, camera_target_y=.41, depth_parallax=.5,
        subject_preserve=.8, feedback=.35, local_symmetry=.2,
        palette_strength=.5, source_fidelity=.87, hero_kind="depth_burst", hero_amount=.85,
        hero_start=.05, hero_end=.45,
        semantic=SemanticVisualProfile(person=.7, subject_radius=.31),
        automation={"flow_warp": [(0, .1), (.5, .8), (1, .2)]},
    )
    scene = SceneSelection(
        section_index=0, time=0, term="test", clip_id=1, scene_id=1,
        scene_index=0, source_id="a", media_file="originals/a.webm",
        media_url="/media/originals/a.webm", start=0, end=2, duration=2,
        direction=VisualDirection(creative=creative),
    )
    timeline = DirectedTimeline(track=track, cues=[], scene_plan=[scene])
    text = write_native_manifest(timeline, library, tmp_path / "native.tsv").read_text()
    line = next(line for line in text.splitlines() if line.startswith("CREATIVE\t"))
    fields = line.split("\t")
    assert float(fields[1]) == .7
    assert float(fields[8]) == .63
    assert float(fields[14]) == .8
    assert fields[28] == "depth_burst"
    assert float(fields[29]) == .85
    assert len(fields) == 99
    assert int(fields[98]) == creative.style_version
    # Extended v0.33 manifest carries per-channel four-point envelopes.
    assert float(fields[37]) < float(fields[38])
    assert float(fields[93]) == .87
    assert float(fields[94]) == 0.0
    assert float(fields[95]) == 1.0
