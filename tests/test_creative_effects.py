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
    assert c.source_fidelity == 1.0
    assert c.style_version == 2
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
    assert high.source_fidelity < low.source_fidelity
    assert .66 <= high.source_fidelity <= .985
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


def test_music_color_bias_stays_source_relative_and_bounded():
    c = candidate()
    c.visual_features["dominant_hue"] = 118
    d = direction(c, section(vibe="euphoric"))
    assert -28.0 <= d.color.hue_shift_degrees <= 28.0
    delta = ((d.color.target_hue - 118 + 180) % 360) - 180
    assert abs(delta) <= 28.0
    # Euphoric used to force an absolute 315-degree target regardless of source.
    assert abs(((d.color.target_hue - 315 + 180) % 360) - 180) > 80


def test_browser_rgb_fx_use_real_channels_not_fixed_hue_overlays():
    from pathlib import Path
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "applyTrueRgbChannels" in js
    for old in (
        "hue-rotate(95deg)", "hue-rotate(-110deg)",
        "hue-rotate(115deg)", "hue-rotate(-125deg)",
        "hue-rotate(105deg)", "hue-rotate(-105deg)",
    ):
        assert old not in js
    assert "resetTemporalFxState" in js
    assert "source_fidelity" in js


def test_most_shots_keep_source_hue_exactly_and_active_grades_are_small():
    clean = 0
    active = 0
    for scene_id in range(1, 81):
        c = candidate(scene_id)
        d = direction(c, section(index=3), creative_intensity=1.0)
        if abs(d.color.hue_shift_degrees) < 1e-9:
            clean += 1
        else:
            active += 1
            assert abs(d.color.hue_shift_degrees) <= 14.0
    assert clean > active
    assert active > 0


def test_local_symmetry_and_palette_treatment_are_sparse():
    symmetry = 0
    palette = 0
    from dataclasses import replace
    for scene_id in range(1, 101):
        c = replace(
            candidate(scene_id, description="abstract architecture and geometric light"),
            title="abstract architecture",
            ai_description={"summary": "abstract architecture and geometric light", "semantic_tags": ["abstract", "architecture"]},
        )
        creative = direction(c, section(index=2), creative_intensity=1.0).creative
        symmetry += creative.local_symmetry > 0
        palette += creative.palette_strength > 0
    assert 0 < symmetry < 18
    assert 10 < palette < 45


def test_browser_mask_and_symmetry_grammars_are_not_universal_circles():
    from pathlib import Path
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "variant=Math.abs(sceneSeed)%4" in js
    assert "variant=Math.abs(Number(activeScene?.scene_id??0))%3" in js
    assert "fx.arc(width/2,height/2" not in js
    assert "case'time_prism':default" in js
    time_prism = js.split("case'time_prism':default", 1)[1].split("break;", 1)[0]
    assert "applyLocalSymmetryCreative" not in time_prism
