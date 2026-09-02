# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable

from .library import SceneCandidate
from .models import CreativeEffectPlan, SceneSelection, Section, SemanticVisualProfile


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, float(value)))


def _stable_unit(value: str) -> float:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def _curve(*points: tuple[float, float]) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in points]


def _effect_key(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("_", " ").replace("-", " ").split())


def _density_gate(seed: float, probability: float, density: float, *, preferred: bool = False) -> bool:
    """Deterministic occurrence gate whose probability, not amplitude, scales.

    A density of 1 preserves the v0.33.6-era probability. Higher density makes
    the same effect vocabulary appear more often without making every active
    instance stronger. AI preference is a modest probability nudge, never a
    command to force a destructive effect on every shot.
    """
    p = max(0.0, min(0.94, float(probability) * max(0.0, float(density)) * (1.55 if preferred else 1.0)))
    return seed >= 1.0 - p


_SEMANTIC_WORDS: dict[str, tuple[str, ...]] = {
    "person": ("person", "people", "human", "man", "woman", "girl", "boy", "dancer", "crowd", "performer", "portrait"),
    "face": ("face", "facial", "portrait", "close-up", "closeup", "headshot"),
    "water": ("water", "ocean", "sea", "river", "lake", "wave", "underwater", "rain", "waterfall"),
    "sky": ("sky", "cloud", "sunset", "sunrise", "stars", "space", "moon"),
    "nature": ("nature", "forest", "tree", "mountain", "flower", "plant", "field", "desert", "wildlife", "landscape"),
    "architecture": ("architecture", "building", "city", "urban", "street", "bridge", "tunnel", "interior", "industrial", "warehouse"),
    "vehicle": ("car", "vehicle", "train", "plane", "aircraft", "motorcycle", "bike", "driving", "road"),
    "text": ("text", "caption", "subtitle", "title card", "logo", "signage", "screen", "interface", "ui"),
    "abstract": ("abstract", "pattern", "geometry", "fractal", "psychedelic", "animation", "surreal", "generative"),
    "night": ("night", "dark", "neon", "club", "rave", "nightlife", "city lights"),
}


def _semantic_text(candidate: SceneCandidate) -> tuple[str, list[str]]:
    ai = candidate.ai_description or {}
    tags = [str(v).strip().lower() for v in ai.get("semantic_tags", []) if str(v).strip()]
    moods = [str(v).strip().lower() for v in ai.get("moods", []) if str(v).strip()]
    foreground = [str(v).strip().lower() for v in ai.get("foreground", []) if str(v).strip()] if isinstance(ai.get("foreground"), list) else []
    background = [str(v).strip().lower() for v in ai.get("background", []) if str(v).strip()] if isinstance(ai.get("background"), list) else []
    summary = str(ai.get("summary") or "")
    fields = [summary, candidate.title or "", candidate.description or "", *tags, *moods, *foreground, *background]
    return " ".join(fields).lower(), (tags + moods + foreground + background)[:20]


def _score_words(text: str, words: Iterable[str]) -> float:
    hits = sum(1 for word in words if word in text)
    if hits <= 0:
        return 0.0
    return _clamp(0.45 + 0.22 * hits)


def semantic_visual_profile(candidate: SceneCandidate) -> SemanticVisualProfile:
    text, tags = _semantic_text(candidate)
    f = candidate.visual_features or {}
    values = {name: _score_words(text, words) for name, words in _SEMANTIC_WORDS.items()}

    # Without a heavyweight runtime segmentation model, use the scene's measured
    # visual statistics to place a stable saliency target.  Directional motion nudges
    # framing toward where the scene is naturally travelling instead of always zooming
    # into the geometric centre.
    mx = _clamp(float(f.get("motion_direction_x", 0.0)), -1.0, 1.0)
    my = _clamp(float(f.get("motion_direction_y", 0.0)), -1.0, 1.0)
    complexity = _clamp(float(f.get("complexity", 0.5)))
    entropy = _clamp(float(f.get("visual_entropy", 0.5)))
    seed = f"semantic:{candidate.scene_id}:{candidate.source_id}"
    jitter_x = (_stable_unit(seed + ":x") - 0.5) * (0.10 + 0.08 * entropy)
    jitter_y = (_stable_unit(seed + ":y") - 0.5) * (0.08 + 0.06 * entropy)
    saliency_x = _clamp(0.5 + 0.12 * mx + jitter_x, 0.22, 0.78)
    saliency_y = _clamp(0.48 + 0.10 * my + jitter_y, 0.20, 0.76)

    # Storyboard AI v2 may provide an actual image-derived focal point.  Blend it
    # with measured motion rather than trusting either source absolutely: the AI
    # anchors the meaningful subject while optical flow keeps framing alive.
    focal = (candidate.ai_description or {}).get("focal_point")
    if isinstance(focal, dict):
        try:
            fx = _clamp(float(focal.get("x", saliency_x)), 0.08, 0.92)
            fy = _clamp(float(focal.get("y", saliency_y)), 0.08, 0.92)
            saliency_x = _clamp(0.72 * fx + 0.28 * saliency_x, 0.10, 0.90)
            saliency_y = _clamp(0.72 * fy + 0.28 * saliency_y, 0.10, 0.90)
        except (TypeError, ValueError):
            pass

    if values["person"] > 0.2 or values["face"] > 0.2:
        # Portrait/people footage benefits from a slightly higher target and a wider
        # protected region so temporal effects wrap around a recognizable subject.
        saliency_y = _clamp(saliency_y - 0.08, 0.18, 0.68)
    subject_radius = _clamp(
        0.22 + 0.14 * max(values["person"], values["face"]) + 0.08 * (1.0 - complexity),
        0.16,
        0.46,
    )
    try:
        subject_scale = _clamp(float((candidate.ai_description or {}).get("subject_scale", 0.0)))
    except (TypeError, ValueError):
        subject_scale = 0.0
    if subject_scale > 0:
        subject_radius = _clamp(0.65 * subject_radius + 0.35 * (0.13 + 0.40 * math.sqrt(subject_scale)), 0.14, 0.52)
    return SemanticVisualProfile(
        tags=tags,
        saliency_x=saliency_x,
        saliency_y=saliency_y,
        subject_radius=subject_radius,
        **values,
    )


def build_creative_effect_plan(
    candidate: SceneCandidate,
    section: Section,
    *,
    family: str,
    narrative_role: str,
    occurrence: int,
    shot_index: int,
    shot_progress: float,
    intensity: float = 1.0,
    density: float = 1.0,
    preferred_effects: Iterable[str] = (),
) -> CreativeEffectPlan:
    """Create a coherent shot treatment from music, motion, palette and semantics.

    This is deliberately a *state* planner, not a random filter chooser.  Every
    scalar is a ceiling and the automation curves determine how the effect develops
    through the shot.  Strong transformations remain sparse and semantic constraints
    preserve faces/people/text more aggressively than abstract or landscape footage.
    """
    f = candidate.visual_features or {}
    sem = semantic_visual_profile(candidate)
    intensity = _clamp(intensity, 0.0, 2.0)
    effect_density = max(0.0, min(2.5, float(density)))
    preferred = {_effect_key(v) for v in preferred_effects if str(v).strip()}
    if intensity <= 1e-6:
        return CreativeEffectPlan(style_version=3, semantic=sem, source_fidelity=1.0)
    energy = _clamp(section.energy)
    density = _clamp(section.onset_density / 0.70)
    bass = _clamp(section.bass_weight)
    percussive = _clamp(section.percussive_ratio)
    tonal = _clamp(section.tonal_stability)
    noisy = _clamp(section.noisiness)
    motion = _clamp(float(f.get("motion", 0.0)))
    complexity = _clamp(float(f.get("complexity", 0.5)))
    entropy = _clamp(float(f.get("visual_entropy", 0.5)))
    trajectory = section.trajectory
    anticipation = _clamp(trajectory.anticipation if trajectory else 0.0)
    withholding = _clamp(trajectory.withholding if trajectory else 0.0)
    contrast_target = _clamp(trajectory.target_contrast if trajectory else 0.35)
    target_motion = _clamp(trajectory.target_motion if trajectory else energy)
    target_complexity = _clamp(trajectory.target_complexity if trajectory else energy)
    ai = section.ai_direction
    if ai is not None:
        target_motion = _clamp(0.55 * target_motion + 0.45 * ai.desired_motion)
        target_complexity = _clamp(0.55 * target_complexity + 0.45 * ai.desired_complexity)

    def ai_pair(name: str) -> tuple[float, float] | None:
        if ai is None:
            return None
        values = ai.creative_trajectory.get(name)
        if not isinstance(values, list) or len(values) < 2:
            return None
        try:
            return (_clamp(float(values[0])), _clamp(float(values[1])))
        except (TypeError, ValueError):
            return None

    mutation = _clamp((occurrence - 1) / 3.0)
    payoff = 1.0 if narrative_role == "payoff" else (0.45 if section.label == "peak" else 0.0)
    build = 1.0 if section.label == "build" else anticipation
    phrase_drive = _clamp(0.30 * energy + 0.20 * density + 0.16 * bass + 0.14 * target_motion + 0.10 * build + 0.10 * payoff)
    abstraction = _clamp(
        0.06 + 0.30 * target_complexity + 0.18 * noisy + 0.15 * mutation + 0.18 * payoff - 0.25 * withholding
    )

    # Source fidelity is deliberately high by default.  It is the renderer-level
    # contract that real footage keeps its own color identity and recognizable
    # texture until the music earns a stronger transformation.  Semantic subjects
    # and withholding raise fidelity; abstraction/payoff/mutation lower it modestly.
    source_fidelity = _clamp(
        0.965
        - 0.085 * abstraction
        - 0.045 * payoff
        - 0.025 * mutation
        + 0.045 * max(sem.person, sem.face, sem.text)
        + 0.04 * withholding,
        0.84, 0.985,
    )

    # Semantic protection: recognisable subjects and text are allowed to move with
    # the camera but are shielded from the harshest spatial destruction.
    subject_weight = max(sem.person, sem.face)
    semantic_fragility = _clamp(0.72 * subject_weight + 0.82 * sem.text)
    subject_preserve = _clamp(0.18 + 0.72 * semantic_fragility + 0.14 * (1.0 - entropy))
    destructive_scale = _clamp(1.0 - 0.56 * semantic_fragility, 0.34, 1.0)

    family_flow = 1.35 if family in {"liquid", "hyper"} else (0.82 if family in {"cinematic", "dream"} else 1.0)
    flow_warp = _clamp((0.05 + 0.50 * motion + 0.20 * energy + 0.10 * sem.water) * family_flow * destructive_scale)
    flow_trails = _clamp(0.04 + 0.34 * motion + 0.28 * tonal + 0.15 * energy + 0.12 * sem.water)
    flow_rgb = _clamp((0.02 + 0.22 * motion + 0.25 * max(0.0, energy - 0.45) + 0.16 * noisy) * destructive_scale)

    temporal_echo = _clamp(0.05 + 0.28 * tonal + 0.18 * motion + 0.16 * (1.0 - percussive) + 0.16 * mutation)
    temporal_rgb = _clamp((0.02 + 0.28 * energy + 0.18 * noisy + 0.10 * mutation) * destructive_scale)
    temporal_smear = _clamp((0.03 + 0.35 * motion + 0.18 * tonal + 0.12 * payoff) * destructive_scale)

    camera_energy = _clamp(0.10 + 0.42 * phrase_drive + 0.20 * density + 0.15 * payoff - 0.18 * withholding)
    # Pan *with* measured motion to make source footage feel intentionally filmed.
    camera_drift_x = _clamp(float(f.get("motion_direction_x", 0.0)) * (0.35 + 0.55 * camera_energy), -1.0, 1.0)
    camera_drift_y = _clamp(float(f.get("motion_direction_y", 0.0)) * (0.25 + 0.45 * camera_energy), -1.0, 1.0)

    depth_semantic = max(sem.architecture, sem.nature, sem.person, sem.sky)
    depth_parallax = _clamp(0.04 + 0.28 * depth_semantic + 0.20 * complexity + 0.16 * (1.0 - motion))
    depth_fog = _clamp((0.02 + 0.22 * sem.nature + 0.18 * sem.sky + 0.12 * (1.0 - section.brightness)) * (1.0 - 0.65 * subject_weight))
    background_warp = _clamp((0.04 + 0.35 * flow_warp + 0.16 * abstraction) * (0.65 + 0.35 * subject_preserve))

    feedback = _clamp(0.03 + 0.30 * tonal + 0.20 * flow_trails + 0.18 * build + 0.14 * mutation - 0.18 * withholding)
    feedback_scale = 0.002 + 0.011 * _clamp(feedback + 0.30 * payoff)
    feedback_rotation = (-1.0 if _stable_unit(f"creative:{candidate.scene_id}:rot") < 0.5 else 1.0) * (0.04 + 0.42 * feedback)

    # Local symmetry is intentionally sparse and moved to the semantic focal point;
    # a portrait should not become a permanent centered kaleidoscope.
    symmetry_gate = _stable_unit(f"creative:{candidate.scene_id}:{section.index}:{shot_index}:sym")
    # Symmetry is a rare accent.  Earlier versions always left a non-zero symmetry
    # floor, which made circular/portal-looking masks appear on a large fraction of
    # shots.  Only a small deterministic subset can schedule it now.
    symmetry_preferred = any(v in preferred for v in {"local symmetry", "kaleidoscope", "recursive portal"})
    if _density_gate(symmetry_gate, 0.08, effect_density, preferred=symmetry_preferred):
        local_symmetry = _clamp(
            (0.05 + 0.18 * tonal + 0.18 * sem.abstract + 0.08 * mutation + 0.10 * payoff)
            * (1.0 - 0.78 * subject_weight)
        )
    else:
        local_symmetry = 0.0
    symmetry_segments = 3 + int(round(5 * _clamp(0.35 * tonal + 0.35 * complexity + 0.30 * abstraction)))

    texture_bloom = _clamp(0.04 + 0.32 * section.brightness + 0.20 * energy + 0.12 * sem.night)
    texture_streaks = _clamp(0.02 + 0.30 * motion + 0.20 * sem.night + 0.12 * sem.architecture + 0.10 * payoff)
    palette_gate = _stable_unit(f"creative:{candidate.scene_id}:{section.index}:{shot_index}:palette")
    palette_probability = 0.36 if payoff >= 0.5 else 0.28
    palette_preferred = any(v in preferred for v in {"palette propagation", "source preserving color grade", "source-preserving color grade"})
    palette_strength = (
        _clamp(0.04 + 0.18 * contrast_target + 0.12 * energy + 0.08 * (1.0 - entropy))
        if _density_gate(palette_gate, palette_probability, effect_density, preferred=palette_preferred)
        else 0.0
    )

    # The AI director/consultant can recommend specific members of the known
    # effect arsenal. Recommendations alter the deterministic planner's emphasis
    # but remain bounded by semantic subject protection and user intensity.
    def wants(*names: str) -> bool:
        keys = {_effect_key(name) for name in names}
        return bool(preferred.intersection(keys))

    def emphasize(value: float, floor: float = 0.12, gain: float = 1.28) -> float:
        return _clamp(max(value * gain, floor))

    if wants("optical-flow warp", "optical flow warp", "flow warp"):
        flow_warp = emphasize(flow_warp, .16)
    if wants("motion trails", "flow trails"):
        flow_trails = emphasize(flow_trails, .16)
    if wants("rgb displacement", "motion-following rgb", "flow rgb"):
        flow_rgb = emphasize(flow_rgb, .12)
    if wants("temporal echo", "frame echo"):
        temporal_echo = emphasize(temporal_echo, .16)
    if wants("temporal rgb displacement", "temporal rgb", "chroma delay"):
        temporal_rgb = emphasize(temporal_rgb, .14)
    if wants("temporal smear", "slit scan"):
        temporal_smear = emphasize(temporal_smear, .14)
    if wants("depth parallax", "depth burst"):
        depth_parallax = emphasize(depth_parallax, .16)
    if wants("background warp"):
        background_warp = emphasize(background_warp, .14)
    if wants("recursive feedback", "feedback"):
        feedback = emphasize(feedback, .14)
    if wants("source-derived bloom", "bloom"):
        texture_bloom = emphasize(texture_bloom, .16)
    if wants("source-derived light streaks", "light streaks"):
        texture_streaks = emphasize(texture_streaks, .14)

    # One dominant creative accent per normal shot. Camera motion and semantic
    # subject metadata are structural and remain available underneath; visible
    # treatment families compete for a sparse budget instead of all carrying
    # non-zero values into the renderer at once.
    preferred_boost = {
        "flow": 0.30 if wants("optical-flow warp", "optical flow warp", "flow warp") else 0.0,
        "temporal": 0.30 if wants("motion trails", "flow trails", "temporal echo", "frame echo", "temporal smear") else 0.0,
        "depth": 0.30 if wants("depth parallax", "depth burst", "background warp") else 0.0,
        "light": 0.30 if wants("source-derived bloom", "bloom", "source-derived light streaks", "light streaks") else 0.0,
        "feedback": 0.30 if wants("recursive feedback", "feedback") else 0.0,
        "color": 0.26 if wants("palette propagation", "source preserving color grade", "source-preserving color grade") else 0.0,
        "symmetry": 0.30 if wants("local symmetry", "kaleidoscope", "recursive portal") else 0.0,
    }
    # Explicit AI trajectory channels count as intent, but still compete for the
    # same one-family budget rather than enabling several renderers in parallel.
    if ai_pair("flow") is not None:
        preferred_boost["flow"] += .18
    if ai_pair("temporal") is not None:
        preferred_boost["temporal"] += .18
    if ai_pair("depth") is not None:
        preferred_boost["depth"] += .18
    if ai_pair("feedback") is not None:
        preferred_boost["feedback"] += .18
    if ai_pair("palette") is not None:
        preferred_boost["color"] += .18

    accent_scores = {
        "flow": .48 * motion + .24 * energy + .18 * sem.water + preferred_boost["flow"],
        "temporal": .34 * tonal + .24 * motion + .18 * (1 - percussive) + .12 * mutation + preferred_boost["temporal"],
        "depth": .34 * depth_semantic + .22 * complexity + .16 * (1 - motion) + preferred_boost["depth"],
        "light": .30 * section.brightness + .22 * energy + .18 * sem.night + preferred_boost["light"],
        "feedback": .32 * tonal + .24 * build + .16 * mutation + preferred_boost["feedback"],
        "color": .26 * contrast_target + .20 * energy + .14 * (1 - entropy) + preferred_boost["color"],
        "symmetry": .30 * sem.abstract + .28 * tonal + .18 * payoff + preferred_boost["symmetry"],
    }
    allowed = ["flow", "temporal", "depth", "light", "feedback", "color"]
    if effect_density >= 1.35:
        allowed.append("symmetry")
    ranked = sorted(allowed, key=lambda name: (-accent_scores[name], name))
    accent_probability = _clamp(.10 + .30 * min(1.0, effect_density) + .12 * build + .12 * payoff)
    accent_gate = _stable_unit(f"creative:{candidate.scene_id}:{section.index}:{shot_index}:accent")
    selected_accents: set[str] = set()
    if ranked and (accent_gate < accent_probability or any(preferred_boost[name] >= .30 for name in ranked)):
        selected_accents.add(ranked[0])
    # Two simultaneous creative families are reserved for exceptional, explicitly
    # dense payoff moments. Even Experimental does not get this routinely.
    if (
        len(ranked) > 1
        and effect_density >= 1.65
        and payoff > .5
        and _stable_unit(f"creative:{candidate.scene_id}:{section.index}:{shot_index}:accent2") < .16
    ):
        selected_accents.add(ranked[1])

    if "flow" not in selected_accents:
        flow_warp = 0.0
        flow_rgb = 0.0
        background_warp = 0.0
    if "temporal" not in selected_accents:
        flow_trails = 0.0
        temporal_echo = 0.0
        temporal_rgb = 0.0
        temporal_smear = 0.0
    if "depth" not in selected_accents:
        depth_parallax = 0.0
        depth_fog = 0.0
    if "light" not in selected_accents:
        texture_bloom = 0.0
        texture_streaks = 0.0
    if "feedback" not in selected_accents:
        feedback = 0.0
    if "color" not in selected_accents:
        palette_strength = 0.0
    if "symmetry" not in selected_accents:
        local_symmetry = 0.0

    # Shot-progress curves.  Effects ramp and release rather than living at a
    # constant strength. Builds escalate, payoffs front-load impact, and withholding
    # deliberately creates visual headroom before a drop.
    if payoff > 0.5:
        shape = ((0.0, 0.38), (0.08, 1.0), (0.28, 0.72), (0.72, 0.42), (1.0, 0.16))
    elif section.label == "build" or anticipation > 0.35:
        shape = ((0.0, 0.12), (0.42, 0.28), (0.76, 0.62), (0.94, 1.0), (1.0, 0.35))
    elif section.label == "breakdown":
        shape = ((0.0, 0.20), (0.35, 0.50), (0.72, 0.38), (1.0, 0.18))
    else:
        shape = ((0.0, 0.22), (0.34, 0.52), (0.76, 0.68), (1.0, 0.22))

    def shaped(value: float, floor: float = 0.0, trajectory_key: str | None = None) -> list[tuple[float, float]]:
        pair = ai_pair(trajectory_key) if trajectory_key else None
        ai_weight = (.18 + .42 * section.audio_semantic_confidence) if pair else 0.0
        out: list[tuple[float, float]] = []
        for p, q in shape:
            deterministic = _clamp(floor + value * q)
            if pair is None:
                out.append((p, deterministic))
                continue
            language_target = pair[0] + (pair[1] - pair[0]) * p
            out.append((p, _clamp(deterministic * (1.0-ai_weight) + language_target * ai_weight)))
        return _curve(*out)

    automation = {
        "flow_warp": shaped(flow_warp, trajectory_key="flow"),
        "flow_trails": shaped(flow_trails, trajectory_key="flow"),
        "flow_rgb": shaped(flow_rgb, trajectory_key="flow"),
        "temporal_echo": shaped(temporal_echo, trajectory_key="temporal"),
        "temporal_rgb": shaped(temporal_rgb, trajectory_key="temporal"),
        "temporal_smear": shaped(temporal_smear, trajectory_key="temporal"),
        "camera_energy": shaped(camera_energy, 0.03, "camera_energy"),
        "depth_parallax": shaped(depth_parallax, trajectory_key="depth"),
        "background_warp": shaped(background_warp, trajectory_key="depth"),
        "feedback": shaped(feedback, trajectory_key="feedback"),
        "local_symmetry": shaped(local_symmetry, trajectory_key="abstraction"),
        "texture_bloom": shaped(texture_bloom, trajectory_key="palette"),
        "texture_streaks": shaped(texture_streaks, trajectory_key="palette"),
        "palette_strength": shaped(palette_strength, 0.02, "palette"),
        "abstraction": shaped(abstraction, trajectory_key="abstraction"),
    }

    # Creative intensity is a global ceiling.  Preserve semantic/camera target
    # metadata while scaling every visible treatment and its trajectory.  Values
    # above 1 intentionally become more assertive but remain model-clamped.
    def scaled(value: float) -> float:
        return _clamp(value * intensity)

    flow_warp = scaled(flow_warp)
    flow_trails = scaled(flow_trails)
    flow_rgb = scaled(flow_rgb)
    temporal_echo = scaled(temporal_echo)
    temporal_rgb = scaled(temporal_rgb)
    temporal_smear = scaled(temporal_smear)
    camera_energy = scaled(camera_energy)
    depth_parallax = scaled(depth_parallax)
    depth_fog = scaled(depth_fog)
    background_warp = scaled(background_warp)
    feedback = scaled(feedback)
    local_symmetry = scaled(local_symmetry)
    texture_bloom = scaled(texture_bloom)
    texture_streaks = scaled(texture_streaks)
    palette_strength = scaled(palette_strength)
    abstraction = scaled(abstraction)
    feedback_scale *= min(1.75, intensity)
    feedback_rotation *= min(1.75, intensity)
    # Intensity scales the *distance from source* rather than directly replacing
    # source color.  Low creative intensity converges toward pristine footage;
    # aggressive values can lower fidelity, but still retain a substantial anchor.
    source_fidelity = _clamp(
        1.0 - (1.0 - source_fidelity) * max(0.20, min(1.60, intensity)),
        0.76, 0.992,
    )
    automation = {
        key: [(p, scaled(v)) for p, v in curve]
        for key, curve in automation.items()
    }

    return CreativeEffectPlan(
        style_version=3,
        flow_warp=flow_warp,
        flow_trails=flow_trails,
        flow_rgb=flow_rgb,
        temporal_echo=temporal_echo,
        temporal_rgb=temporal_rgb,
        temporal_smear=temporal_smear,
        camera_energy=camera_energy,
        camera_target_x=sem.saliency_x,
        camera_target_y=sem.saliency_y,
        camera_drift_x=camera_drift_x,
        camera_drift_y=camera_drift_y,
        depth_parallax=depth_parallax,
        depth_fog=depth_fog,
        subject_preserve=subject_preserve,
        background_warp=background_warp,
        feedback=feedback,
        feedback_scale=feedback_scale,
        feedback_rotation=feedback_rotation,
        local_symmetry=local_symmetry,
        symmetry_segments=symmetry_segments,
        texture_bloom=texture_bloom,
        texture_streaks=texture_streaks,
        palette_strength=palette_strength,
        source_fidelity=source_fidelity,
        abstraction=abstraction,
        semantic=sem,
        automation=automation,
    )


def _hero_score(selection: SceneSelection, section: Section) -> float:
    c = selection.direction.creative
    role = selection.direction.narrative_role
    role_score = {"payoff": 1.0, "mutate": 0.70, "introduce": 0.35, "develop": 0.42}.get(role, 0.35)
    section_score = 1.0 if section.label == "peak" else (0.78 if section.label == "build" else 0.30)
    semantic_interest = max(
        c.semantic.person, c.semantic.water, c.semantic.architecture,
        c.semantic.nature, c.semantic.abstract, c.semantic.night,
    )
    ai_hero = section.ai_direction.hero_frequency if section.ai_direction is not None else 1.0
    return _clamp(
        0.31 * role_score + 0.25 * section_score + 0.20 * section.energy
        + 0.13 * c.abstraction + 0.11 * semantic_interest
        + 0.08 * (max(0.0, min(2.5, ai_hero)) - 1.0)
    )


def _hero_kind(selection: SceneSelection) -> str:
    c = selection.direction.creative
    family = selection.direction.effect_family
    if c.semantic.person > 0.55 or c.semantic.face > 0.45:
        return "subject_echo"
    if c.semantic.water > 0.45 or family == "liquid":
        return "flow_melt"
    if c.semantic.architecture > 0.45 or c.semantic.nature > 0.45:
        return "depth_burst"
    if family in {"fracture", "hyper", "analog"}:
        return "time_prism"
    if family in {"dream", "prismatic"}:
        return "recursive_portal"
    return "time_prism"


def promote_hero_effects(
    plan: list[SceneSelection],
    sections: dict[int, Section],
    *,
    track_duration: float,
    frequency: float = 1.0,
) -> list[SceneSelection]:
    """Promote musically spaced high-impact hero treatments.

    Frequency is independent of hero amplitude. At 1.0 the target remains about
    one event per 48 seconds; higher settings create more punctuation while still
    enforcing temporal spacing and deterministic eligibility.
    """
    if not plan:
        return plan
    frequency = max(0.0, min(2.5, float(frequency)))
    if frequency <= 1e-6:
        return plan
    ai_values = [
        section.ai_direction.hero_frequency
        for section in sections.values()
        if section.ai_direction is not None
    ]
    ai_scale = sum(ai_values) / len(ai_values) if ai_values else 1.0
    effective_frequency = max(0.0, min(3.5, frequency * ai_scale))
    target = max(1, min(14, int(round(track_duration * effective_frequency / 48.0))))
    target = min(target, max(1, len(plan) // 5)) if len(plan) >= 5 else min(1, len(plan))
    candidates: list[tuple[float, int]] = []
    for index, selection in enumerate(plan):
        section = sections.get(selection.section_index)
        if section is None:
            continue
        creative = selection.direction.creative
        if bool((selection.ai_director or {}).get("hold")):
            continue
        if creative.hero_kind and creative.hero_amount > 0.01:
            continue
        if max(
            creative.flow_warp, creative.temporal_echo, creative.camera_energy,
            creative.depth_parallax, creative.feedback, creative.local_symmetry,
            creative.texture_bloom, creative.palette_strength, creative.abstraction,
        ) <= 1e-6:
            continue
        score = _hero_score(selection, section)
        # Deterministic tiny jitter prevents every track from selecting exactly
        # the same ordinal shots when scores tie.
        score += 0.035 * _stable_unit(f"hero:{selection.scene_id}:{selection.time:.3f}")
        if score >= 0.47:
            candidates.append((score, index))
    candidates.sort(reverse=True)

    chosen: list[int] = []
    min_spacing = max(4.0, 10.0 / max(0.75, effective_frequency ** 0.55))
    for _, idx in candidates:
        t = plan[idx].time
        if any(abs(t - plan[other].time) < min_spacing for other in chosen):
            continue
        chosen.append(idx)
        if len(chosen) >= target:
            break

    updated = list(plan)
    for idx in chosen:
        selection = updated[idx]
        section = sections[selection.section_index]
        creative = selection.direction.creative
        kind = _hero_kind(selection)
        score = _hero_score(selection, section)
        amount = _clamp(0.58 + 0.34 * score)
        if section.label == "build":
            start, end = 0.62, 0.99
        elif selection.direction.narrative_role == "payoff" or section.label == "peak":
            start, end = 0.01, 0.42
        else:
            start, end = 0.34, 0.78
        creative = creative.model_copy(update={
            "hero_kind": kind,
            "hero_amount": amount,
            "hero_start": start,
            "hero_end": end,
        })
        direction = selection.direction.model_copy(update={"creative": creative})
        updated[idx] = selection.model_copy(update={"direction": direction})
    return updated


def apply_temporal_persistence(
    plan: list[SceneSelection],
    sections: dict[int, Section],
    *,
    persistence: float = 1.0,
) -> list[SceneSelection]:
    """Annotate cuts that may intentionally inherit previous-frame history.

    v0.33.5 reset feedback/delay state at every ordinary cut. This restores
    controlled continuity without bringing back uncontrolled smear: related motifs,
    compatible effect families, high-continuity sections and explicit AI requests
    can carry history across a cut, while unrelated scenes still reset cleanly.
    """
    if not plan:
        return plan
    global_persistence = max(0.0, min(2.5, float(persistence)))
    out = list(plan)
    first = out[0]
    first_creative = first.direction.creative.model_copy(update={"history_inherit": 0.0})
    out[0] = first.model_copy(update={"direction": first.direction.model_copy(update={"creative": first_creative})})

    temporal_heroes = {"flow_melt", "subject_echo", "time_prism", "recursive_portal"}
    for index in range(1, len(out)):
        current = out[index]
        previous = out[index - 1]
        section = sections.get(current.section_index)
        if section is None:
            continue
        ai_scale = section.ai_direction.temporal_persistence if section.ai_direction is not None else 1.0
        local = max(0.0, min(3.0, global_persistence * ai_scale))
        director_advice = current.ai_director or {}
        advice = current.ai_consultant or {}
        history_mode = str(director_advice.get("history_mode") or advice.get("history_mode") or "auto").lower()
        if history_mode == "reset" or local <= 1e-6:
            inherit = 0.0
        else:
            c = current.direction.creative
            temporal_energy = max(c.temporal_echo, c.temporal_rgb, c.temporal_smear, c.flow_trails, c.feedback)
            relation = 0.08
            if current.section_index == previous.section_index:
                relation += 0.24
            if current.motif_id and current.motif_id == previous.motif_id:
                relation += 0.28
            if current.direction.effect_family == previous.direction.effect_family:
                relation += 0.20
            if current.direction.narrative_role in {"mutate", "payoff"}:
                relation += 0.09
            if section.ai_direction is not None:
                relation += 0.16 * section.ai_direction.continuity
            if c.hero_kind in temporal_heroes:
                relation += 0.38
            relation = _clamp(relation)
            if history_mode == "inherit":
                inherit = _clamp(0.42 + 0.18 * min(2.0, local) + 0.24 * temporal_energy + 0.12 * relation)
            else:
                probability = _clamp((0.10 + 0.42 * relation + 0.18 * temporal_energy) * min(2.25, local))
                gate = _stable_unit(f"history:{current.scene_id}:{current.time:.3f}:{previous.scene_id}")
                inherit = (
                    _clamp(0.18 + 0.34 * relation + 0.22 * temporal_energy + 0.10 * max(0.0, local - 1.0))
                    if gate < probability else 0.0
                )
        creative = current.direction.creative.model_copy(update={"history_inherit": inherit})
        out[index] = current.model_copy(update={"direction": current.direction.model_copy(update={"creative": creative})})
    return out
