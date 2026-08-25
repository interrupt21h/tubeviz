# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from .library import SceneCandidate
from .models import CodecEffect, ColorDirection, Section, VectorEffect, VisualDirection
from .choreography import shot_trajectory


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
    if section.ai_direction is not None:
        confidence = .30 + .45 * section.audio_semantic_confidence
        target = target * (1.0 - confidence) + section.ai_direction.desired_motion * confidence
    return _clamp(target)


def visual_match_score(candidate: SceneCandidate, section: Section) -> float:
    f = candidate.visual_features or {}
    if not f:
        return 0.0
    target_motion = motion_target(section)
    raster_motion = float(f.get("motion", 0.0))
    codec_motion = f.get("codec_motion")
    motion = (0.72 * raster_motion + 0.28 * float(codec_motion)) if codec_motion is not None else raster_motion
    complexity = float(f.get("complexity", 0.5))
    brightness = float(f.get("brightness", 0.5))
    saturation = float(f.get("saturation", 0.5))
    motion_match = 1.0 - abs(motion - target_motion)
    brightness_match = 1.0 - abs(brightness - section.brightness)
    desired_complexity = _clamp(0.20 + 0.72 * section.energy + 0.20 * section.noisiness)
    if section.ai_direction is not None:
        w = .25 + .40 * section.audio_semantic_confidence
        desired_complexity = _clamp(desired_complexity * (1-w) + section.ai_direction.desired_complexity * w)
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
    if section.ai_direction is not None:
        continuity = section.ai_direction.continuity
        # +1 means "this transition satisfies the director". High continuity
        # rewards similarity; low continuity rewards deliberate contrast.
        desired_contrast = 1.0 - continuity
        ai_transition = 1.0 - 2.0 * abs(contrast - desired_contrast)
        base_weight = .25 + .35 * section.audio_semantic_confidence
    else:
        ai_transition = None
        base_weight = 0.0

    # Builds/peaks/drops benefit from contrast; ambient/hypnotic passages prefer continuity.
    if section.label == "peak" or section.vibe in {"heavy", "fractured", "euphoric"}:
        base = contrast
    elif section.label == "build":
        base = (contrast - .45) * .9
    elif section.label == "breakdown" or section.vibe in {"ambient", "hypnotic"}:
        base = 1.0 - 2.0 * contrast
    else:
        base = 0.35 - abs(contrast - 0.35)
    if ai_transition is not None:
        base = base * (1.0-base_weight) + ai_transition * base_weight
    return _clamp(base, -1.0, 1.0)


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
    # When FFglitch codec-motion indexing is available, merge macroblock motion
    # peaks with decoded-image accents. Codec motion often reveals camera/object
    # movement that simple luminance differencing understates.
    for item in f.get("codec_motion_accents", []):
        accents.append({
            "time": float(item.get("time", 0.0)),
            "strength": min(1.0, .35 + .65*float(item.get("strength", 0.0))),
        })
    accents.sort(key=lambda item: float(item.get("time", 0.0)))
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
    """Schedule a sparse, coherent vector scene graph.

    v0.24 deliberately treats visible vector geometry as punctuation rather than
    a permanent overlay. At most one visible family is normally active and two
    are allowed only at high-energy peaks. Displacement-only effects do not
    count against that budget.
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
    motion_params = {
        "motion_x": float(f.get("motion_direction_x", 0.0)),
        "motion_y": float(f.get("motion_direction_y", 0.0)),
    }

    visible: list[VectorEffect] = []
    hidden: list[VectorEffect] = []

    contour_amount = _clamp(.08 + .30 * complexity + .15 * energy)
    contour = VectorEffect(
        kind="contours",
        amount=contour_amount,
        opacity=.055 + .15 * contour_amount,
        count=int(7 + 11 * complexity),
        line_width=1.0 + .8 * (1 - complexity),
        seed=seed + 1,
        source="connected_video_contours",
        parameters={"min_arc": 12.0, "max_paths": 10},
        automation={
            "amount": _curve((0, .05 * contour_amount), (.60, .42 * contour_amount), (.91, contour_amount), (1, .10 * contour_amount)),
            "opacity": _curve((0, .02), (.70, .08 + .10 * energy), (1, .025)),
        },
    )

    subject = _clamp(.06 + .22 * complexity + .20 * (1 - entropy) + .10 * energy)
    semantic = VectorEffect(
        kind="semantic_outline",
        amount=subject,
        opacity=.05 + .13 * subject,
        count=int(4 + 7 * subject),
        line_width=1.2 + .7 * subject,
        seed=seed + 11,
        source="salient_connected_contours",
        parameters={"min_arc": 16.0, "max_paths": 6},
        automation={"amount": _curve((0, .04), (.62, subject), (1, .08))},
    )

    flow_amount = _clamp(.06 + .42 * motion + .20 * energy)
    flow = VectorEffect(
        kind="flow_ribbons",
        amount=flow_amount,
        opacity=.055 + .18 * flow_amount,
        count=int(7 + 11 * (motion + entropy) / 2),
        line_width=1.1 + 2.0 * flow_amount,
        seed=seed + 2,
        source="local_optical_flow",
        parameters=motion_params,
        automation={
            "amount": _curve((0, .08 * flow_amount), (.48, .46 * flow_amount), (.88, flow_amount), (1, .12 * flow_amount)),
            "curl": _curve((0, .06), (.55, .12 + .22 * entropy), (1, .08 + .15 * energy)),
        },
    )
    particles = VectorEffect(
        kind="flow_particles",
        amount=_clamp(flow_amount * .68),
        opacity=.04 + .11 * flow_amount,
        count=int(18 + 32 * flow_amount),
        line_width=.7 + .8 * flow_amount,
        seed=seed + 3,
        source="local_optical_flow",
        parameters=motion_params,
        automation={"amount": _curve((0, .05), (.72, .55 * flow_amount), (1, .10))},
    )

    echo_amount = _clamp(.07 + .30 * (1 - percussive) + .16 * motion)
    echo = VectorEffect(
        kind="vector_echo",
        amount=echo_amount,
        opacity=.045 + .12 * echo_amount,
        count=4,
        line_width=.9 + .8 * echo_amount,
        seed=seed + 4,
        source="connected_contour_history",
        automation={"amount": _curve((0, .05), (.52, echo_amount), (1, .08))},
    )

    grid_amount = _clamp(.06 + .24 * energy + .12 * section.brightness)
    grid = VectorEffect(
        kind="perspective_grid",
        amount=grid_amount,
        opacity=.035 + .10 * grid_amount,
        count=int(8 + 10 * grid_amount),
        line_width=.65 + .65 * grid_amount,
        seed=seed + 5,
        source="scene_motion",
        parameters=motion_params,
        automation={"amount": _curve((0, .04), (.78, grid_amount), (1, .08))},
    )

    fracture_amount = _clamp(.12 + .48 * energy + .20 * section.noisiness)
    fracture = VectorEffect(
        kind="delaunay_fracture",
        amount=fracture_amount,
        opacity=.06 + .17 * fracture_amount,
        count=int(14 + 24 * fracture_amount),
        line_width=.8 + .8 * fracture_amount,
        seed=seed + 6,
        source="video_features",
        displace=True,
        automation={
            "amount": _curve((0, .02), (.76, .12 * fracture_amount), (.95, fracture_amount), (1, .05)),
            "explode": _curve((0, 0), (.84, .04), (.97, .66 * fracture_amount), (1, .06)),
        },
    )
    voronoi_amount = _clamp(.08 + .34 * energy + .14 * entropy)
    voronoi = VectorEffect(
        kind="voronoi",
        amount=voronoi_amount,
        opacity=.045 + .12 * voronoi_amount,
        count=int(11 + 18 * voronoi_amount),
        line_width=.75 + .55 * voronoi_amount,
        seed=seed + 7,
        source="video_features",
        displace=family == "fracture",
        automation={"amount": _curve((0, .03), (.60, .32 * voronoi_amount), (.94, voronoi_amount), (1, .06))},
    )

    portal_amount = _clamp(.06 + .30 * energy + .10 * section.tonal_stability)
    portal = VectorEffect(
        kind="portal",
        amount=portal_amount,
        opacity=.12 + .22 * portal_amount,
        count=1,
        line_width=1.1 + 1.2 * portal_amount,
        seed=seed + 8,
        source="companion_video",
        automation={
            "amount": _curve((0, .01), (.38, .18 * portal_amount), (.74, portal_amount), (1, .06)),
            "radius": _curve((0, .05), (.64, .24 + .14 * portal_amount), (1, .08)),
        },
    )

    glyph_amount = _clamp(.05 + .14 * energy + .12 * max(0, occurrence - 1))
    glyph = VectorEffect(
        kind="motif_glyph",
        amount=glyph_amount,
        opacity=.035 + .10 * glyph_amount,
        count=5 + (seed % 4),
        line_width=.9 + 1.0 * glyph_amount,
        seed=seed + 9,
        source="motif",
        automation={
            "amount": _curve((0, .02), (.58, glyph_amount), (1, .05)),
            "rotation": _curve((0, 0), (1, .28 + .52 * energy)),
        },
    )

    # Family-specific visible vocabulary. This prevents the old situation where
    # contours, semantic edges, ribbons, particles, grids, portals and glyphs
    # were all drawn over the same shot.
    family_candidates: dict[str, list[VectorEffect]] = {
        "dream": [echo, contour, portal],
        "liquid": [flow, echo, portal],
        "analog": [grid, contour],
        "fracture": [fracture, voronoi],
        "hyper": [flow, fracture, particles],
        "prismatic": [portal, voronoi, flow],
        "cinematic": [semantic if entropy < .62 else contour, grid, portal],
    }
    candidates = family_candidates.get(family, [contour])

    # Roughly one quarter of non-peak shots stay completely clean; low-energy
    # passages stay clean even more often. Visual contrast makes vector moments
    # feel intentional rather than like a permanent filter.
    clean_period = 2 if energy < .45 else 4
    clean_shot = section.label != "peak" and ((seed // 97 + shot_index) % clean_period == 0)
    visible_budget = 0 if clean_shot else (2 if section.label == "peak" and energy > .76 else 1)

    # A motif glyph is a callback punctuation mark, not a continuously visible
    # logo. Permit it only at the first shot of a returning motif/peak.
    if shot_index == 0 and (occurrence > 1 or section.label == "peak") and visible_budget > 0:
        candidates = [glyph, *candidates]

    for effect in candidates:
        if len(visible) >= visible_budget:
            break
        if effect.kind in {"flow_ribbons", "flow_particles"} and motion < .10 and family not in {"liquid", "hyper"}:
            continue
        visible.append(effect)

    # Invisible deformation can remain active underneath clean footage because
    # it doesn't create a forest of lines.
    if energy > .45 and (motion > .12 or family in {"hyper", "liquid", "fracture"}):
        transplant = _clamp(.06 + .30 * energy + .20 * motion)
        hidden.append(VectorEffect(
            kind="motion_transplant",
            amount=transplant,
            opacity=0.0,
            visible=False,
            displace=True,
            count=14,
            line_width=3.0,
            seed=seed + 12,
            source="companion_motion",
            automation={"amount": _curve((0, .03), (.58, .22 * transplant), (.93, transplant), (1, .07))},
        ))

    if energy > .30:
        disp = _clamp(.06 + .31 * energy + .16 * section.bass_weight)
        hidden.append(VectorEffect(
            kind="vector_displacement",
            amount=disp,
            opacity=0.0,
            visible=False,
            displace=True,
            count=8 + int(14 * disp),
            line_width=2.0 + 3.0 * disp,
            seed=seed + 10,
            source="music_field",
            automation={"amount": _curve((0, .04 * disp), (.72, .25 * disp), (.95, disp), (1, .07 * disp))},
        ))

    return visible + hidden


def _codec_effects(
    candidate: SceneCandidate,
    section: Section,
    *,
    mode: str,
    intensity: float,
    occurrence: int,
    shot_index: int,
    narrative_role: str,
) -> list[CodecEffect]:
    """Schedule sparse codec-space effects for FFglitch materialization.

    Codec effects are intentionally much rarer than raster/vector treatments.
    Their perceptual value comes from the transition into and out of true
    prediction/motion-vector corruption.
    """
    mode = (mode or "off").lower()
    if mode == "off" or intensity <= 0:
        return []
    intensity = _clamp(intensity, 0.0, 1.5)
    f = candidate.visual_features or {}
    motion = float(f.get("codec_motion", f.get("motion", 0.0)))
    mx = float(f.get("codec_motion_direction_x", f.get("motion_direction_x", 0.0)))
    my = float(f.get("codec_motion_direction_y", f.get("motion_direction_y", 0.0)))
    angle = math.atan2(my, mx if abs(mx) > 1e-6 else 1e-6)
    energy = _clamp(section.energy)
    density = _clamp(section.onset_density / .75)
    tension = _clamp(.46*energy + .24*density + .18*section.noisiness + .12*section.bass_weight)
    seed = (candidate.scene_id * 2654435761 + section.index*4099 + shot_index*131 + occurrence*17) & 0x7fffffff
    peak = section.label == "peak" or narrative_role == "payoff"
    build = section.label == "build"
    breakdown = section.label == "breakdown"

    if mode == "subtle":
        gate = peak or build or (section.vibe in {"fractured", "heavy"} and energy > .70)
    elif mode == "musical":
        gate = peak or build or narrative_role == "mutate" or (section.vibe in {"fractured", "heavy", "driving"} and energy > .68)
    else:  # aggressive
        gate = energy > .42 or narrative_role in {"mutate", "payoff"}
    if not gate or breakdown and mode != "aggressive":
        return []

    scale = {"subtle": .48, "musical": .78, "aggressive": 1.10}.get(mode, .78) * intensity
    out: list[CodecEffect] = []

    # The first effect follows scene motion so the codec treatment inherits the
    # existing camera/object direction rather than being generic corruption.
    if build:
        out.append(CodecEffect(
            kind="mv_drift" if motion < .35 else "mv_wave",
            amount=_clamp((.18+.32*tension)*scale, 0, 1.25),
            start=.36, end=.98, attack=.24, release=.06, angle=angle,
            pulse=2.0, seed=seed+1, limit=72,
        ))
    elif peak:
        primary = "mv_explode" if section.bass_weight >= .48 else "mv_spiral"
        out.append(CodecEffect(
            kind=primary,
            amount=_clamp((.34+.46*tension)*scale, 0, 1.35),
            start=.02, end=.42, attack=.025, release=.16,
            pulse=1.0, seed=seed+2, limit=112,
        ))
        # A short feedback/mosh tail lets prediction errors smear after impact.
        if mode != "subtle":
            out.append(CodecEffect(
                kind="datamosh",
                amount=_clamp((.20+.36*energy+.14*motion)*scale, 0, 1.20),
                start=.28, end=.82, attack=.08, release=.18,
                pulse=2.0, seed=seed+3, limit=128,
            ))
    elif section.vibe == "fractured":
        out.append(CodecEffect(
            kind="mv_jitter",
            amount=_clamp((.20+.42*section.noisiness+.18*density)*scale, 0, 1.25),
            start=.18, end=.90, attack=.12, release=.14,
            pulse=4.0, seed=seed+4, limit=96,
        ))
    elif narrative_role == "mutate":
        out.append(CodecEffect(
            kind="mv_spiral" if motion > .3 else "mv_shear",
            amount=_clamp((.18+.32*tension)*scale, 0, 1.10),
            start=.22, end=.84, attack=.16, release=.16,
            pulse=1.5, seed=seed+5, limit=88,
        ))
    elif mode == "aggressive":
        out.append(CodecEffect(
            kind="mv_radial_wave",
            amount=_clamp((.14+.30*tension)*scale, 0, 1.0),
            start=.25, end=.90, attack=.15, release=.12,
            pulse=2.5, seed=seed+6, limit=80,
        ))

    # Cap vocabulary per shot: true codec glitches become noisy very quickly.
    return out[:2]


def build_visual_direction(
    candidate: SceneCandidate,
    section: Section,
    *,
    rhythm_alignment: float,
    source_playback_rate: float,
    transition: float,
    occurrence: int,
    shot_index_in_section: int,
    shot_progress: float = 0.5,
    vector_enabled: bool = True,
    vector_intensity: float = 1.0,
    codec_glitch_mode: str = "off",
    codec_glitch_intensity: float = 0.65,
) -> VisualDirection:
    f = candidate.visual_features or {}
    source_hue = float(f.get("dominant_hue", 0.0)) % 360.0
    base_target = _VIBE_HUE.get(section.vibe, _VIBE_HUE["neutral"])
    if section.ai_direction is not None and section.ai_direction.target_hue is not None:
        w = .28 + .42 * section.audio_semantic_confidence
        # Circular shortest-path interpolation.
        delta = _shortest_hue_delta(base_target, section.ai_direction.target_hue)
        base_target = (base_target + delta*w) % 360.0
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
    if section.ai_direction is not None and section.ai_direction.effect_family in {"dream","liquid","analog","fracture","hyper","prismatic","cinematic"}:
        if section.audio_semantic_confidence >= .18:
            family = section.ai_direction.effect_family

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
    trajectory = shot_trajectory(section, shot_progress)
    # Phrase-aware trajectory adds anticipation and payoff without replacing the
    # underlying audio-reactive curves. A pre-drop withholding window deliberately
    # reduces visual clutter so the subsequent impact has somewhere to go.
    withhold = trajectory["withhold"]
    impact = trajectory["impact"]
    tension = _clamp(tension * (1.0 - .30*withhold) + .22*trajectory["density"] + .18*impact)
    saturation_scale = _clamp(saturation_scale * (1.0 - .18*withhold) * (1.0 + .14*impact), .50, 2.0)
    contrast_scale = _clamp(contrast_scale * (1.0 + .18*trajectory["contrast"] + .22*impact - .16*withhold), .70, 2.0)
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

    if withhold > .0:
        for key in ("spectral_warp", "chromatic", "feedback", "flow", "glitch", "bloom"):
            automation[key] = [(p, _clamp(v * (1.0 - .62*withhold))) for p, v in automation[key]]
    if impact > .0:
        for key, gain in (("spectral_warp", .36), ("chromatic", .42), ("glitch", .34), ("bloom", .50)):
            automation[key] = [(p, _clamp(v + gain*impact*(1.0-abs(.16-p)))) for p, v in automation[key]]

    ai_vector_scale = section.ai_direction.vector_intensity if section.ai_direction is not None else 1.0
    ai_codec_scale = section.ai_direction.codec_intensity if section.ai_direction is not None else 1.0
    trajectory_fx_scale = max(.20, 1.0 + .30*trajectory["density"] + .45*impact - .58*withhold)

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
                        "amount": _clamp(effect.amount * vector_intensity * ai_vector_scale * trajectory_fx_scale),
                        "opacity": _clamp(effect.opacity * min(1.5, vector_intensity * ai_vector_scale * trajectory_fx_scale)),
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
        codec_effects=_codec_effects(
            candidate, section, mode=codec_glitch_mode,
            intensity=codec_glitch_intensity * ai_codec_scale * trajectory_fx_scale, occurrence=occurrence,
            shot_index=shot_index_in_section, narrative_role=narrative_role,
        ),
    )
