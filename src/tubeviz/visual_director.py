from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from .library import SceneCandidate
from .models import ColorDirection, Section, VectorEffect, VisualDirection


_VIBE_HUE = {
    "ambient": 205.0,
    "hypnotic": 275.0,
    "dark": 235.0,
    "heavy": 338.0,
    "driving": 192.0,
    "euphoric": 315.0,
    "fractured": 112.0,
    "groove": 28.0,
    "neutral": 210.0,
}

_EFFECT_FAMILY = {
    "ambient": "dream",
    "hypnotic": "liquid",
    "dark": "analog",
    "heavy": "fracture",
    "driving": "hyper",
    "euphoric": "prismatic",
    "fractured": "fracture",
    "groove": "liquid",
    "neutral": "cinematic",
}


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, float(value)))


def _shortest_hue_delta(source: float, target: float) -> float:
    return ((target - source + 180.0) % 360.0) - 180.0


def motion_target(section: Section) -> float:
    tempo = _clamp((section.local_tempo_bpm - 75.0) / 90.0)
    density = _clamp(section.onset_density / 0.70)
    target = 0.38 * section.energy + 0.27 * density + 0.20 * section.percussive_ratio + 0.15 * tempo
    if section.label == "breakdown":
        target *= 0.55
    elif section.label == "peak":
        target = min(1.0, target * 1.22)
    return _clamp(target)


def visual_match_score(candidate: SceneCandidate, section: Section) -> float:
    f = candidate.visual_features or {}
    if not f:
        return 0.0
    target_motion = motion_target(section)
    motion = float(f.get("motion", 0.0))
    complexity = float(f.get("complexity", 0.5))
    brightness = float(f.get("brightness", 0.5))
    saturation = float(f.get("saturation", 0.5))
    motion_match = 1.0 - abs(motion - target_motion)
    brightness_match = 1.0 - abs(brightness - section.brightness)
    desired_complexity = _clamp(0.20 + 0.72 * section.energy + 0.20 * section.noisiness)
    complexity_match = 1.0 - abs(complexity - desired_complexity)
    desired_saturation = _clamp(0.30 + 0.55 * section.energy + 0.15 * section.brightness)
    saturation_match = 1.0 - abs(saturation - desired_saturation)
    return _clamp(
        0.44 * motion_match
        + 0.20 * complexity_match
        + 0.18 * brightness_match
        + 0.18 * saturation_match
    )


def transition_score(
    previous: SceneCandidate | None,
    candidate: SceneCandidate,
    section: Section,
) -> float:
    if previous is None or not previous.visual_features or not candidate.visual_features:
        return 0.0
    a = previous.visual_features
    b = candidate.visual_features
    hue_delta = abs(_shortest_hue_delta(float(a.get("dominant_hue", 0)), float(b.get("dominant_hue", 0)))) / 180.0
    motion_delta = abs(float(a.get("motion", 0)) - float(b.get("motion", 0)))
    bright_delta = abs(float(a.get("brightness", .5)) - float(b.get("brightness", .5)))
    complexity_delta = abs(float(a.get("complexity", .5)) - float(b.get("complexity", .5)))
    contrast = _clamp(.34*hue_delta + .28*motion_delta + .20*bright_delta + .18*complexity_delta)

    # Builds/peaks/drops benefit from contrast; ambient/hypnotic passages prefer continuity.
    if section.label == "peak" or section.vibe in {"heavy", "fractured", "euphoric"}:
        return contrast
    if section.label == "build":
        return (contrast - .45) * .9
    if section.label == "breakdown" or section.vibe in {"ambient", "hypnotic"}:
        return 1.0 - 2.0 * contrast
    return 0.35 - abs(contrast - 0.35)


def _accent_alignment(
    accents: list[dict],
    *,
    source_offset: float,
    rate: float,
    shot_duration: float,
    beat_positions: list[float],
) -> float:
    if not accents or not beat_positions:
        return 0.0
    visual = []
    for item in accents:
        t = (float(item.get("time", 0.0)) - source_offset) / rate
        if 0 <= t <= shot_duration:
            visual.append((t, float(item.get("strength", 0.0))))
    if not visual:
        return 0.0
    tolerance = max(.055, min(.20, shot_duration / max(6.0, len(beat_positions)*7.0)))
    score = 0.0
    weight = 0.0
    for t, strength in visual:
        distance = min(abs(t - b) for b in beat_positions)
        local = max(0.0, 1.0 - distance / tolerance)
        score += local * max(.15, strength)
        weight += max(.15, strength)
    return _clamp(score / max(1e-8, weight))


def aligned_excerpt(
    candidate: SceneCandidate,
    *,
    shot_duration: float,
    beat_positions: list[float],
    seed_unit: float,
    min_scene_seconds: float,
    excerpt_max_seconds: float,
) -> tuple[float, float, float, float]:
    """Return absolute source start/end, playback rate and beat/motion alignment."""
    available = max(.05, candidate.duration)
    f = candidate.visual_features or {}
    accents = list(f.get("accents", []))
    rates = (0.88, 0.94, 1.0, 1.06, 1.12)
    target_source_span = min(
        available,
        max(min_scene_seconds, shot_duration),
        max(min_scene_seconds, excerpt_max_seconds),
    )

    candidate_offsets = {0.0, max(0.0, available - target_source_span)}
    travel = max(0.0, available - target_source_span)
    candidate_offsets.add(travel * seed_unit)
    for accent in accents[:20]:
        at = float(accent.get("time", 0.0))
        candidate_offsets.add(min(travel, max(0.0, at - target_source_span * .5)))

    best = (-1.0, 0.0, 1.0)
    for rate in rates:
        source_span = min(available, target_source_span * rate)
        max_offset = max(0.0, available - source_span)
        for offset in candidate_offsets:
            offset = min(max_offset, max(0.0, offset))
            align = _accent_alignment(
                accents,
                source_offset=offset,
                rate=rate,
                shot_duration=shot_duration,
                beat_positions=beat_positions,
            )
            # Slightly prefer rates close to 1 when alignment is equivalent.
            objective = align - abs(rate - 1.0) * .08
            if objective > best[0]:
                best = (objective, offset, rate)

    _, relative_start, rate = best
    source_span = min(available - relative_start, target_source_span * rate)
    relative_end = relative_start + max(.05, source_span)
    alignment = max(0.0, best[0] + abs(rate - 1.0) * .08)
    return (
        candidate.start_time + relative_start,
        candidate.start_time + relative_end,
        rate,
        _clamp(alignment),
    )


def _curve(*points: tuple[float, float]) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in points]


def _vector_effects(
    candidate: SceneCandidate,
    section: Section,
    *,
    family: str,
    occurrence: int,
    shot_index: int,
) -> list[VectorEffect]:
    """Schedule coherent vector geometry from music + visual fingerprint.

    All effects are deterministic from section/scene identity and are designed
    to either reveal structure already present in the footage or use vector
    geometry as a mask/displacement source rather than as unrelated decoration.
    """
    f = candidate.visual_features or {}
    motion = _clamp(float(f.get("motion", 0.0)))
    complexity = _clamp(float(f.get("complexity", 0.5)))
    entropy = _clamp(float(f.get("visual_entropy", 0.5)))
    energy = _clamp(section.energy)
    percussive = _clamp(section.percussive_ratio)
    seed = (
        candidate.scene_id * 1000003
        + section.index * 9176
        + shot_index * 137
        + occurrence * 1009
    ) & 0x7FFFFFFF

    out: list[VectorEffect] = []

    # Footage-derived edge topology. It is visible at moderate strength and can
    # become a displacement source during peaks.
    contour_amount = _clamp(.12 + .45*complexity + .22*energy)
    out.append(VectorEffect(
        kind="contours",
        amount=contour_amount,
        opacity=.12 + .32*contour_amount,
        count=int(18 + 54*complexity),
        line_width=.7 + 1.8*(1-complexity),
        seed=seed + 1,
        source="video_edges",
        displace=section.label == "peak" and energy > .72,
        automation={
            "amount": _curve((0, .18*contour_amount), (.55, .62*contour_amount), (.92, contour_amount), (1, .22*contour_amount)),
            "opacity": _curve((0, .06), (.65, .22+.24*energy), (1, .08)),
        },
    ))

    # Subject/semantic outline proxy: runtime saliency selects strong contours
    # near coherent high-contrast regions. This keeps the feature dependency-free
    # while providing a distinct subject-oriented vector layer; a future
    # segmentation backend can replace the source without changing the timeline.
    subject = _clamp(.08 + .28*complexity + .18*(1-entropy) + .18*energy)
    out.append(VectorEffect(
        kind="semantic_outline",
        amount=subject,
        opacity=.08 + .24*subject,
        count=int(12 + 30*subject),
        line_width=1.1 + 1.8*subject,
        seed=seed + 11,
        source="saliency_contours",
        automation={"amount": _curve((0, .12*subject), (.6, subject), (1, .18*subject))},
    ))

    # Optical-flow-like streamlines/ribbons. The scene fingerprint supplies the
    # global motion direction; runtime luminance gradients bend the field.
    flow_amount = _clamp(.08 + .52*motion + .24*energy)
    if motion > .08 or family in {"liquid", "hyper", "prismatic"}:
        out.append(VectorEffect(
            kind="flow_ribbons",
            amount=flow_amount,
            opacity=.10 + .30*flow_amount,
            count=int(10 + 30*(motion+entropy)/2),
            line_width=1.2 + 4.2*flow_amount,
            seed=seed + 2,
            source="motion_field",
            parameters={
                "motion_x": float(f.get("motion_direction_x", 0.0)),
                "motion_y": float(f.get("motion_direction_y", 0.0)),
            },
            automation={
                "amount": _curve((0, .20*flow_amount), (.45, .55*flow_amount), (.88, flow_amount), (1, .28*flow_amount)),
                "curl": _curve((0, .10), (.55, .25+.42*entropy), (1, .15+.25*energy)),
            },
        ))
        out.append(VectorEffect(
            kind="flow_particles",
            amount=_clamp(flow_amount*.82),
            opacity=.08 + .20*flow_amount,
            count=int(36 + 110*flow_amount),
            line_width=.8 + 1.4*flow_amount,
            seed=seed + 3,
            source="motion_field",
            parameters={
                "motion_x": float(f.get("motion_direction_x", 0.0)),
                "motion_y": float(f.get("motion_direction_y", 0.0)),
            },
            automation={
                "amount": _curve((0, .15*flow_amount), (.7, .75*flow_amount), (1, .25*flow_amount)),
            },
        ))

    # Pose/motion vector echo: actual edge structure from earlier frames is
    # retained as vector-like contour echoes.
    if family in {"dream", "liquid", "hyper", "prismatic"} or section.label == "breakdown":
        echo = _clamp(.10 + .42*(1-percussive) + .22*motion)
        out.append(VectorEffect(
            kind="vector_echo",
            amount=echo,
            opacity=.08 + .22*echo,
            count=6,
            line_width=1.0 + 1.8*echo,
            seed=seed + 4,
            source="edge_history",
            automation={"amount": _curve((0, .15*echo), (.5, echo), (1, .20*echo))},
        ))

    # Perspective geometry becomes part of the scene by using motion direction
    # to bias its vanishing point.
    if family in {"analog", "hyper", "cinematic"}:
        grid = _clamp(.08 + .32*energy + .20*section.brightness)
        out.append(VectorEffect(
            kind="perspective_grid",
            amount=grid,
            opacity=.06 + .18*grid,
            count=int(10 + 20*grid),
            line_width=.6 + 1.2*grid,
            seed=seed + 5,
            source="scene_motion",
            parameters={
                "motion_x": float(f.get("motion_direction_x", 0.0)),
                "motion_y": float(f.get("motion_direction_y", 0.0)),
            },
            automation={"amount": _curve((0, .15*grid), (.75, grid), (1, .24*grid))},
        ))

    # Delaunay-style fracture is a high-impact structural effect and can
    # displace texture fragments, not just draw triangle lines.
    if family in {"fracture", "hyper"} or section.label == "peak":
        fracture = _clamp(.18 + .55*energy + .28*section.noisiness)
        out.append(VectorEffect(
            kind="delaunay_fracture",
            amount=fracture,
            opacity=.10 + .28*fracture,
            count=int(18 + 42*fracture),
            line_width=.8 + 1.6*fracture,
            seed=seed + 6,
            source="video_features",
            displace=True,
            automation={
                "amount": _curve((0, .04), (.72, .20*fracture), (.94, fracture), (1, .08)),
                "explode": _curve((0, 0), (.8, .08), (.96, .75*fracture), (1, .12)),
            },
        ))

    # Voronoi cells use generated feature sites as masks/displacement boundaries.
    if family in {"fracture", "prismatic"}:
        voronoi = _clamp(.10 + .42*energy + .18*entropy)
        out.append(VectorEffect(
            kind="voronoi",
            amount=voronoi,
            opacity=.07 + .22*voronoi,
            count=int(12 + 28*voronoi),
            line_width=.8 + 1.1*voronoi,
            seed=seed + 7,
            source="video_features",
            displace=family == "fracture",
            automation={"amount": _curve((0, .12*voronoi), (.55, .48*voronoi), (.92, voronoi), (1, .16*voronoi))},
        ))

    # Portals reveal companion video layers using organic vector masks.
    if section.energy > .42:
        portal = _clamp(.08 + .38*energy + .15*section.tonal_stability)
        out.append(VectorEffect(
            kind="portal",
            amount=portal,
            opacity=.18 + .30*portal,
            count=1 + int(portal > .72),
            line_width=1.2 + 2.0*portal,
            seed=seed + 8,
            source="companion_video",
            automation={
                "amount": _curve((0, .02), (.35, .28*portal), (.72, portal), (1, .10)),
                "radius": _curve((0, .06), (.62, .28+.18*portal), (1, .10)),
            },
        ))

    # Recurring motif glyph is deterministic by motif occurrence/scene identity.
    # It is an abstract visual alphabet rather than arbitrary text.
    glyph = _clamp(.08 + .20*energy + .16*max(0, occurrence-1))
    out.append(VectorEffect(
        kind="motif_glyph",
        amount=glyph,
        opacity=.06 + .20*glyph,
        count=5 + (seed % 5),
        line_width=1.0 + 2.0*glyph,
        seed=seed + 9,
        source="motif",
        automation={
            "amount": _curve((0, .05), (.55, glyph), (1, .12)),
            "rotation": _curve((0, 0), (1, .4 + .8*energy)),
        },
    ))

    # Motion transplantation: when a companion layer is available the renderer
    # derives a temporal field from it and uses that field to warp the primary.
    if energy > .48 and (motion > .12 or family in {"hyper", "liquid", "fracture"}):
        transplant = _clamp(.08 + .38*energy + .25*motion)
        out.append(VectorEffect(
            kind="motion_transplant",
            amount=transplant,
            opacity=0.0,
            visible=False,
            displace=True,
            count=18,
            line_width=3.0,
            seed=seed + 12,
            source="companion_motion",
            automation={
                "amount": _curve((0, .04), (.55, .28*transplant), (.92, transplant), (1, .10))
            },
        ))

    # Vector geometry as an invisible displacement field. This is scheduled
    # separately so the visible vector overlay can remain subtle.
    if energy > .35:
        disp = _clamp(.10 + .42*energy + .22*section.bass_weight)
        out.append(VectorEffect(
            kind="vector_displacement",
            amount=disp,
            opacity=0.0,
            visible=False,
            displace=True,
            count=8 + int(22*disp),
            line_width=2.0 + 5.0*disp,
            seed=seed + 10,
            source="music_field",
            automation={
                "amount": _curve((0, .08*disp), (.7, .32*disp), (.94, disp), (1, .12*disp))
            },
        ))

    return out


def build_visual_direction(
    candidate: SceneCandidate,
    section: Section,
    *,
    rhythm_alignment: float,
    source_playback_rate: float,
    transition: float,
    occurrence: int,
    shot_index_in_section: int,
    vector_enabled: bool = True,
    vector_intensity: float = 1.0,
) -> VisualDirection:
    f = candidate.visual_features or {}
    source_hue = float(f.get("dominant_hue", 0.0)) % 360.0
    base_target = _VIBE_HUE.get(section.vibe, _VIBE_HUE["neutral"])
    # Evolve hue with harmonic/structural location rather than a static LUT.
    target_hue = (
        base_target
        + section.index * 17.0
        + shot_index_in_section * 5.0
        + max(0, occurrence - 1) * 23.0
    ) % 360.0
    hue_shift = _shortest_hue_delta(source_hue, target_hue)

    saturation_scale = _clamp(
        .82 + .75 * section.energy + .25 * section.brightness,
        .55, 1.85
    )
    contrast_scale = _clamp(.90 + .50 * section.energy + .18 * section.noisiness, .75, 1.75)
    brightness_scale = _clamp(.82 + .36 * section.brightness + .16 * section.energy, .68, 1.38)
    chroma = _clamp(.06 + .55*section.energy + .30*section.noisiness)
    family = _EFFECT_FAMILY.get(section.vibe, "cinematic")

    narrative_role = "develop"
    if shot_index_in_section == 0 and occurrence == 1:
        narrative_role = "introduce"
    elif occurrence > 1:
        narrative_role = "mutate"
    if section.label == "peak":
        narrative_role = "payoff"

    e = _clamp(section.energy)
    tension = _clamp(
        .40*section.energy + .22*section.onset_density + .18*section.noisiness
        + .20*section.percussive_ratio
    )
    # Continuous curves rather than on/off effect selection.
    automation = {
        "hue": _curve((0, hue_shift*.35), (.55, hue_shift*.72), (1, hue_shift)),
        "saturation": _curve((0, 1.0), (.5, saturation_scale), (1, saturation_scale*(1.0+.10*tension))),
        "spectral_warp": _curve((0, .08*e), (.65, .20+.36*tension), (.92, .58*tension), (1, .12*e)),
        "chromatic": _curve((0, .04*e), (.72, .22*chroma), (.94, .72*chroma), (1, .10*e)),
        "feedback": _curve((0, .05), (.55, .08+.32*(1-section.percussive_ratio)), (1, .04+.18*e)),
        "flow": _curve((0, .08+.12*e), (.5, .18+.34*e), (1, .10+.20*e)),
        "glitch": _curve((0, .02), (.72, .08+.28*section.noisiness), (.96, .55*section.noisiness), (1, .04)),
        "bloom": _curve((0, .02), (.75, .08+.22*e), (.96, .55*e), (1, .08)),
    }

    return VisualDirection(
        rhythm_alignment=rhythm_alignment,
        transition_score=_clamp(transition, -1.0, 1.0),
        source_playback_rate=source_playback_rate,
        motion_match=visual_match_score(candidate, section),
        motion=_clamp(float(f.get("motion", 0.0))),
        complexity=_clamp(float(f.get("complexity", 0.0))),
        visual_entropy=_clamp(float(f.get("visual_entropy", 0.0))),
        effect_family=family,
        narrative_role=narrative_role,
        color=ColorDirection(
            source_hue=source_hue,
            target_hue=target_hue,
            hue_shift_degrees=_clamp(hue_shift, -180, 180),
            saturation_scale=saturation_scale,
            contrast_scale=contrast_scale,
            brightness_scale=brightness_scale,
            chromatic_aberration=chroma,
            warmth=_clamp(float(f.get("warmth", .5))),
            palette=list(f.get("palette", []))[:5],
        ),
        automation=automation,
        vector_effects=(
            [
                effect.model_copy(
                    update={
                        "amount": _clamp(effect.amount * vector_intensity),
                        "opacity": _clamp(effect.opacity * min(1.5, vector_intensity)),
                    }
                )
                for effect in _vector_effects(
                    candidate,
                    section,
                    family=family,
                    occurrence=occurrence,
                    shot_index=shot_index_in_section,
                )
            ]
            if vector_enabled and vector_intensity > 0
            else []
        ),
    )
