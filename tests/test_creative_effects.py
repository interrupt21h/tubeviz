# SPDX-License-Identifier: Apache-2.0
from tubeviz.cli import build_parser
from tubeviz.creative_effects import promote_hero_effects, semantic_visual_profile
from tubeviz.library import SceneCandidate
from tubeviz.models import (
    CreativeEffectPlan,
    SceneSelection,
    Section,
    SectionAIDirection,
    SemanticVisualProfile,
    VisualDirection,
)
from tubeviz.visual_director import build_visual_direction


def candidate(scene_id: int = 1, *, description: str = "dancer beside neon water") -> SceneCandidate:
    return SceneCandidate(
        scene_id=scene_id,
        clip_id=scene_id,
        scene_index=0,
        start_time=0.0,
        end_time=12.0,
        duration=12.0,
        thumbnail_path=None,
        source_id=f"src-{scene_id}",
        title="cinematic night portrait",
        description=description,
        channel=None,
        normalized_path=f"originals/{scene_id}.webm",
        term="creative",
        term_rank=1,
        visual_features={
            "motion": .72,
            "complexity": .64,
            "visual_entropy": .58,
            "motion_direction_x": .55,
            "motion_direction_y": -.25,
            "brightness": .52,
            "saturation": .70,
            "dominant_hue": 210,
            "warmth": .35,
            "palette": ["#102040", "#30a0c0"],
        },
        ai_description={
            "summary": "A dancer in a neon-lit night scene beside moving water",
            "semantic_tags": ["person", "water", "night", "portrait"],
            "moods": ["kinetic", "dreamlike"],
        },
    )


def section(index: int = 0, **updates) -> Section:
    values = dict(
        index=index,
        start=index * 8.0,
        end=(index + 1) * 8.0,
        energy=.84,
        label="peak",
        brightness=.62,
        onset_density=.58,
        local_tempo_bpm=128,
        bass_weight=.70,
        percussive_ratio=.66,
        tonal_stability=.56,
        noisiness=.26,
        spectral_contrast=.58,
        vibe="driving",
        audio_semantic_confidence=.8,
    )
    values.update(updates)
    return Section(**values)


def direction(c: SceneCandidate, s: Section, **updates) -> VisualDirection:
    return build_visual_direction(
        c,
        s,
        rhythm_alignment=.8,
        source_playback_rate=1.0,
        transition=.5,
        occurrence=1,
        shot_index_in_section=0,
        **updates,
    )


def test_semantic_profile_protects_recognizable_subject_and_moves_saliency():
    c = candidate()
    profile = semantic_visual_profile(c)
    assert profile.person > .5
    assert profile.face > .5
    assert profile.water > .5
    assert profile.night > .5
    assert .22 <= profile.saliency_x <= .78
    assert profile.saliency_x > .5  # follows measured positive x motion
    assert profile.subject_radius > .25

    d = direction(c, section())
    assert d.creative.subject_preserve > .5
    assert d.creative.camera_target_x == profile.saliency_x
    assert d.creative.flow_warp > 0
    assert d.creative.temporal_echo > 0
    assert d.creative.depth_parallax > 0
    assert "camera_energy" in d.creative.automation


def test_storyboard_focal_point_guides_semantic_camera_target():
    c = candidate()
    c.ai_description["focal_point"] = {"x": .18, "y": .31}
    c.ai_description["subject_scale"] = .64
    profile = semantic_visual_profile(c)
    assert profile.saliency_x < .30
    assert profile.saliency_y < .40
    assert profile.subject_radius > .30


def test_creative_effects_can_be_disabled_without_losing_semantic_metadata():
    d = direction(candidate(), section(), creative_enabled=False)
    c = d.creative
    assert c.flow_warp == 0
    assert c.temporal_echo == 0
    assert c.camera_energy == 0
    assert c.feedback == 0
    assert c.palette_strength == 0
    assert c.hero_kind is None
    assert c.semantic.person > 0


def test_creative_intensity_scales_treatment():
    c = candidate()
    s = section()
    low = direction(c, s, creative_intensity=.35).creative
    high = direction(c, s, creative_intensity=1.6).creative
    assert high.flow_warp > low.flow_warp
    assert high.camera_energy > low.camera_energy
    assert high.feedback > low.feedback
    assert high.automation["flow_warp"][1][1] > low.automation["flow_warp"][1][1]


def test_ai_creative_trajectory_guides_section_curve_without_replacing_planner():
    c = candidate(description="abstract city architecture at night")
    baseline = direction(c, section(audio_semantic_confidence=.95)).creative
    ai = SectionAIDirection(
        desired_motion=.8,
        desired_complexity=.8,
        creative_trajectory={
            "camera_energy": [0.05, 1.0],
            "abstraction": [0.05, .95],
            "feedback": [0.02, .85],
        },
    )
    guided = direction(c, section(ai_direction=ai, audio_semantic_confidence=.95)).creative
    assert guided.automation["camera_energy"][-1][1] > baseline.automation["camera_energy"][-1][1]
    assert guided.automation["abstraction"][-1][1] > baseline.automation["abstraction"][-1][1]
    assert guided.automation["feedback"][-1][1] > baseline.automation["feedback"][-1][1]
    # Scene-derived constraints are still present even when the LLM contributes a curve.
    assert guided.semantic.person > 0
    assert guided.subject_preserve > 0


def test_hero_effects_are_sparse_spaced_and_deterministic():
    sections = {i: section(i) for i in range(24)}
    plan = []
    for i in range(36):
        sem = SemanticVisualProfile(abstract=.8, architecture=.6)
        creative = CreativeEffectPlan(
            flow_warp=.6,
            temporal_echo=.5,
            camera_energy=.7,
            feedback=.5,
            abstraction=.8,
            semantic=sem,
        )
        scene = SceneSelection(
            section_index=i % 24,
            time=i * 5.0,
            term="creative",
            clip_id=i + 1,
            scene_id=i + 1,
            scene_index=0,
            source_id=f"src-{i}",
            media_file=f"originals/{i}.webm",
            media_url=f"/media/originals/{i}.webm",
            start=0,
            end=4,
            duration=4,
            direction=VisualDirection(
                narrative_role="payoff",
                effect_family="fracture",
                creative=creative,
            ),
        )
        plan.append(scene)

    a = promote_hero_effects(plan, sections, track_duration=180.0)
    b = promote_hero_effects(plan, sections, track_duration=180.0)
    hero_a = [(s.time, s.direction.creative.hero_kind) for s in a if s.direction.creative.hero_kind]
    hero_b = [(s.time, s.direction.creative.hero_kind) for s in b if s.direction.creative.hero_kind]
    assert hero_a == hero_b
    assert 1 <= len(hero_a) <= 4
    assert all((hero_a[i + 1][0] - hero_a[i][0]) >= 10.0 for i in range(len(hero_a) - 1))


def test_cli_exposes_independent_creative_renderer_controls():
    parser = build_parser()
    args = parser.parse_args([
        "analyze", "song.mp3", "--no-creative-effects", "--creative-intensity", "1.35"
    ])
    assert args.creative_effects is False
    assert args.creative_intensity == 1.35
