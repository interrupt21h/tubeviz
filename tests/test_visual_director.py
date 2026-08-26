# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.library import ClipLibrary, SceneCandidate, sha256_file
from tubeviz.models import Section
from tubeviz.visual_director import (
    aligned_excerpt,
    build_visual_direction,
    transition_score,
    visual_match_score,
)


def scene(scene_id: int, *, motion: float, hue: float, brightness: float = .5) -> SceneCandidate:
    return SceneCandidate(
        scene_id=scene_id,
        clip_id=scene_id,
        scene_index=0,
        start_time=10.0,
        end_time=20.0,
        duration=10.0,
        thumbnail_path=None,
        source_id=str(scene_id),
        title="scene",
        description=None,
        channel=None,
        normalized_path=f"normalized/{scene_id}.mp4",
        term="test",
        term_rank=1,
        visual_features={
            "motion": motion,
            "complexity": .65,
            "brightness": brightness,
            "saturation": .7,
            "dominant_hue": hue,
            "visual_entropy": .7,
            "warmth": .5,
            "palette": ["#102030", "#405060"],
            "accents": [
                {"time": 1.0, "strength": 1.0},
                {"time": 2.0, "strength": .9},
                {"time": 3.0, "strength": .8},
            ],
        },
    )


def section(**updates) -> Section:
    values = dict(
        index=1,
        start=0,
        end=8,
        energy=.8,
        label="peak",
        brightness=.6,
        onset_density=.55,
        local_tempo_bpm=120,
        bass_weight=.55,
        percussive_ratio=.7,
        tonal_stability=.5,
        noisiness=.25,
        spectral_contrast=.5,
        vibe="driving",
    )
    values.update(updates)
    return Section(**values)


def test_visual_match_prefers_motion_compatible_scene():
    target = section(energy=.85, onset_density=.65)
    fast = scene(1, motion=.78, hue=200)
    slow = scene(2, motion=.05, hue=200)
    assert visual_match_score(fast, target) > visual_match_score(slow, target)


def test_transition_prefers_contrast_at_peak_and_continuity_in_breakdown():
    previous = scene(1, motion=.1, hue=220, brightness=.2)
    contrast = scene(2, motion=.9, hue=30, brightness=.9)
    similar = scene(3, motion=.12, hue=225, brightness=.22)
    assert transition_score(previous, contrast, section(label="peak")) > transition_score(previous, similar, section(label="peak"))
    assert transition_score(previous, similar, section(label="breakdown", vibe="ambient")) > transition_score(previous, contrast, section(label="breakdown", vibe="ambient"))


def test_aligned_excerpt_finds_visual_accents_on_beats():
    candidate = scene(1, motion=.7, hue=180)
    start, end, rate, score = aligned_excerpt(
        candidate,
        shot_duration=3.2,
        beat_positions=[0.0, 1.0, 2.0, 3.0],
        seed_unit=.5,
        min_scene_seconds=.5,
        excerpt_max_seconds=4,
    )
    assert 10 <= start < end <= 20
    assert .88 <= rate <= 1.12
    assert score > .5


def test_visual_direction_has_color_and_continuous_automation():
    candidate = scene(1, motion=.7, hue=30)
    direction = build_visual_direction(
        candidate,
        section(),
        rhythm_alignment=.9,
        source_playback_rate=1.06,
        transition=.7,
        occurrence=2,
        shot_index_in_section=1,
    )
    assert direction.rhythm_alignment == .9
    assert direction.effect_family == "hyper"
    assert direction.narrative_role in {"mutate", "payoff"}
    assert abs(direction.color.hue_shift_degrees) <= 14
    assert len(direction.automation["spectral_warp"]) >= 3
    assert len(direction.automation["hue"]) >= 3


def test_library_visual_feature_roundtrip(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = library.upsert_discovery(
        source="youtube", source_id="a", source_url="https://example.invalid/a",
        term="test", rank=1, metadata={"title": "a", "duration": 10},
    )
    media = library.normalized_dir / "a.mp4"
    media.write_bytes(b"video")
    library.mark_normalized(clip_id, media, sha256_file(media))
    library.replace_scenes(clip_id, [(0.0, 5.0, None)])
    candidate = library.scene_candidates(clip_id=clip_id)[0]
    library.store_scene_visual_features(candidate.scene_id, {
        "version": 1, "motion": .8, "dominant_hue": 240, "accents": [],
    })
    loaded = library.scene_candidates(clip_id=clip_id)[0]
    assert loaded.visual_features["motion"] == .8
    assert library.stats()["visual_features"] == 1
