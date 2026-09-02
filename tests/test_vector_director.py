# SPDX-License-Identifier: Apache-2.0
from tubeviz.library import SceneCandidate
from tubeviz.models import Section
from tubeviz.visual_director import build_visual_direction


def candidate(scene_id=7):
    return SceneCandidate(
        scene_id=scene_id,
        clip_id=scene_id,
        scene_index=0,
        start_time=0,
        end_time=8,
        duration=8,
        thumbnail_path=None,
        source_id=str(scene_id),
        title="vector source",
        description=None,
        channel=None,
        normalized_path=f"normalized/{scene_id}.mp4",
        term="test",
        term_rank=1,
        visual_features={
            "motion": .8,
            "motion_peak": 1.0,
            "motion_entropy": .75,
            "motion_direction_x": .6,
            "motion_direction_y": -.25,
            "complexity": .8,
            "visual_entropy": .7,
            "brightness": .6,
            "saturation": .75,
            "dominant_hue": 210,
            "warmth": .3,
            "palette": ["#102040", "#50a0e0"],
            "accents": [{"time": 1.0, "strength": 1.0}],
        },
    )


def section(vibe="driving", label="peak", **updates):
    data = dict(
        index=3, start=0, end=8, energy=.9, label=label,
        brightness=.65, onset_density=.7, local_tempo_bpm=128,
        bass_weight=.65, percussive_ratio=.72, tonal_stability=.48,
        noisiness=.55, spectral_contrast=.6, vibe=vibe,
    )
    data.update(updates)
    return Section(**data)


def kinds(direction):
    return {effect.kind for effect in direction.vector_effects}


def test_vector_scene_graph_is_sparse_and_hidden_displacement_is_high_intensity_only():
    normal = build_visual_direction(
        candidate(), section("driving"), rhythm_alignment=.9,
        source_playback_rate=1.0, transition=.8, occurrence=1,
        shot_index_in_section=0, vector_intensity=1.0,
    )
    assert len([effect for effect in normal.vector_effects if effect.visible]) <= 1
    assert not [effect for effect in normal.vector_effects if not effect.visible]

    experimental = build_visual_direction(
        candidate(), section("driving"), rhythm_alignment=.9,
        source_playback_rate=1.0, transition=.8, occurrence=1,
        shot_index_in_section=0, vector_intensity=2.0,
    )
    hidden = {effect.kind for effect in experimental.vector_effects if not effect.visible}
    assert {"motion_transplant", "vector_displacement"} <= hidden


def test_non_peak_shots_use_at_most_one_visible_vector_family():
    direction = build_visual_direction(
        candidate(), section("driving", label="drive", energy=.65),
        rhythm_alignment=.8, source_playback_rate=1.0, transition=.4,
        occurrence=1, shot_index_in_section=1,
    )
    assert len([effect for effect in direction.vector_effects if effect.visible]) <= 1


def test_prismatic_family_uses_footage_derived_effects_when_visible():
    seen = []
    for scene_id in range(1, 60):
        direction = build_visual_direction(
            candidate(scene_id), section("euphoric"), rhythm_alignment=.8,
            source_playback_rate=1.0, transition=.8, occurrence=2,
            shot_index_in_section=1, vector_intensity=1.2,
        )
        visible = [effect.kind for effect in direction.vector_effects if effect.visible]
        if visible:
            seen.extend(visible)
    assert seen
    assert all(kind in {"voronoi", "flow_ribbons", "contours", "vector_echo", "portal"} for kind in seen)
    assert seen.count("portal") < len(seen) * .25


def test_portal_vector_effect_is_rare_across_prismatic_shots():
    total = 0
    portals = 0
    for scene_id in range(1, 121):
        d = build_visual_direction(
            candidate(scene_id), section("euphoric"), rhythm_alignment=.8,
            source_playback_rate=1.0, transition=.8, occurrence=1,
            shot_index_in_section=2, vector_intensity=1.0,
        )
        visible = [effect.kind for effect in d.vector_effects if effect.visible]
        total += bool(visible)
        portals += "portal" in visible
    assert 20 < total < 75
    assert portals < max(2, total * .25)


def test_vector_effects_have_deterministic_seeds_and_automation():
    a = build_visual_direction(
        candidate(), section(), rhythm_alignment=.7,
        source_playback_rate=1.0, transition=.4, occurrence=2,
        shot_index_in_section=2,
    )
    b = build_visual_direction(
        candidate(), section(), rhythm_alignment=.7,
        source_playback_rate=1.0, transition=.4, occurrence=2,
        shot_index_in_section=2,
    )
    assert [(e.kind, e.seed) for e in a.vector_effects] == [(e.kind, e.seed) for e in b.vector_effects]
    assert all("amount" in e.automation for e in a.vector_effects)


def test_vector_effects_can_be_disabled():
    direction = build_visual_direction(
        candidate(), section(), rhythm_alignment=.7,
        source_playback_rate=1.0, transition=.4, occurrence=1,
        shot_index_in_section=0, vector_enabled=False,
    )
    assert direction.vector_effects == []


def test_vector_intensity_scales_occurrence_and_effect_amounts():
    def totals(intensity):
        amount = 0.0
        visible = 0
        for scene_id in range(1, 81):
            d = build_visual_direction(
                candidate(scene_id), section("driving", label="drive"), rhythm_alignment=.7,
                source_playback_rate=1.0, transition=.4, occurrence=1,
                shot_index_in_section=1, vector_intensity=intensity,
            )
            visible_effects = [e for e in d.vector_effects if e.visible]
            visible += len(visible_effects)
            amount += sum(e.amount for e in visible_effects)
        return visible, amount

    low_visible, low_amount = totals(.25)
    normal_visible, normal_amount = totals(1.0)
    assert normal_visible > low_visible
    assert normal_amount > low_amount


def test_motion_field_effects_carry_scene_motion_direction():
    direction = build_visual_direction(
        candidate(4), section("driving", label="drive"), rhythm_alignment=.7,
        source_playback_rate=1.0, transition=.4, occurrence=1,
        shot_index_in_section=1, vector_intensity=1.0,
    )
    flow = next(e for e in direction.vector_effects if e.kind == "flow_ribbons")
    assert flow.parameters["motion_x"] == .6
    assert flow.parameters["motion_y"] == -.25
