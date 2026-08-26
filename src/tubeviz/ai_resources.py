# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable
import math
import shutil

from .library import ClipLibrary, SceneCandidate


RASTER_EFFECTS = [
    "source-preserving color grade", "virtual camera push/pan", "optical-flow warp",
    "motion trails", "temporal echo", "temporal RGB displacement", "temporal smear",
    "depth parallax", "background warp", "recursive feedback", "source-derived bloom",
    "source-derived light streaks", "RGB displacement", "slit scan", "frame echo",
    "mirror corridor", "mask wipe", "solarize", "datamosh-like block displacement",
    "chroma delay", "VHS tracking", "vortex", "slice recursion", "kaleidoscope",
    "pixelation", "posterization", "scanlines", "vignette", "ripple",
]
VECTOR_EFFECTS = [
    "contours", "semantic outline", "flow ribbons", "flow particles", "vector echo",
    "perspective grid", "Delaunay fracture", "Voronoi", "portal", "motif glyph",
    "motion transplant", "vector displacement",
]
CODEC_EFFECTS = [
    "datamosh", "motion-vector drift", "motion-vector wave", "motion-vector jitter",
    "motion-vector spiral", "motion-vector shear", "motion-vector radial wave",
]
HERO_EFFECTS = ["subject echo", "flow melt", "depth burst", "time prism", "recursive portal"]
COMPOSITION_MODES = ["single source", "flow blend", "luma blend", "organic strips"]
EFFECT_FAMILIES = ["dream", "liquid", "analog", "fracture", "hyper", "prismatic", "cinematic"]


def _bucket_hue(hue: float) -> str:
    hue %= 360.0
    buckets = [
        (15, "red"), (45, "orange"), (70, "yellow"), (155, "green"),
        (195, "cyan"), (250, "blue"), (290, "violet"), (335, "magenta"), (360, "red"),
    ]
    for edge, name in buckets:
        if hue < edge:
            return name
    return "red"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _scene_tags(candidate: SceneCandidate) -> list[str]:
    out: list[str] = []
    ai = candidate.ai_description or {}
    for key in ("semantic_tags", "moods", "foreground", "background"):
        values = ai.get(key)
        if isinstance(values, list):
            out.extend(str(v).strip().lower() for v in values if str(v).strip())
    if candidate.term:
        out.append(candidate.term.strip().lower())
    return out


def compact_candidate(candidate: SceneCandidate, *, score: float | None = None) -> dict[str, Any]:
    f = candidate.visual_features or {}
    ai = candidate.ai_description or {}
    summary = str(ai.get("description") or ai.get("summary") or candidate.description or "").strip()
    palette: list[str] = []
    raw_palette = f.get("palette")
    if isinstance(raw_palette, list):
        palette = [str(v) for v in raw_palette[:5]]
    dominant_hue = f.get("dominant_hue")
    if not palette and dominant_hue is not None:
        palette = [_bucket_hue(_safe_float(dominant_hue) * (360.0 if _safe_float(dominant_hue) <= 1.0 else 1.0))]
    utility = {
        key: round(_safe_float(ai.get(key)), 3)
        for key in ("energy", "motion", "complexity", "continuity", "build_fit", "drop_fit", "ambient_fit")
        if key in ai
    }
    item: dict[str, Any] = {
        "scene_id": candidate.scene_id,
        "clip_id": candidate.clip_id,
        "scene_index": candidate.scene_index,
        "title": (candidate.title or "")[:140],
        "term": candidate.term or "",
        "duration": round(candidate.duration, 3),
        "description": summary[:360],
        "tags": _scene_tags(candidate)[:14],
        "motion": round(_safe_float(f.get("motion"), 0.5), 3),
        "complexity": round(_safe_float(f.get("complexity"), 0.5), 3),
        "brightness": round(_safe_float(f.get("brightness"), 0.5), 3),
        "palette": palette,
    }
    if utility:
        item["editing_utility"] = utility
    if score is not None:
        item["deterministic_score"] = round(float(score), 4)
    return item


def build_resource_manifest(library: ClipLibrary, selector_config: Any, *, representative_limit: int = 18) -> dict[str, Any]:
    """Summarize the actual eligible library and renderer arsenal for the LLM director.

    The manifest is intentionally compact: it exposes corpus strengths/weaknesses and representative
    material without dumping thousands of scene rows into the whole-song prompt. Exact scene choices
    are handled later by the bounded edit-consultant pass.
    """
    library.initialize()
    candidates = library.scene_candidates(min_duration=max(0.0, float(getattr(selector_config, "min_scene_seconds", 0.0))))
    clips: dict[int, list[SceneCandidate]] = defaultdict(list)
    tags = Counter()
    terms = Counter()
    palettes = Counter()
    motion_bins = Counter()
    ai_count = 0
    feature_count = 0
    for c in candidates:
        clips[c.clip_id].append(c)
        if c.ai_description:
            ai_count += 1
        if c.visual_features:
            feature_count += 1
        tags.update(_scene_tags(c))
        if c.term:
            terms[c.term] += 1
        f = c.visual_features or {}
        motion = _safe_float(f.get("motion"), 0.5)
        motion_bins["low" if motion < 0.33 else "high" if motion >= 0.67 else "medium"] += 1
        hue = f.get("dominant_hue")
        if hue is not None:
            hv = _safe_float(hue)
            if hv <= 1.0:
                hv *= 360.0
            palettes[_bucket_hue(hv)] += 1

    representatives: list[dict[str, Any]] = []
    for clip_id, scenes in sorted(clips.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:representative_limit]:
        # Prefer the richest scene from each representative clip.
        scene = max(scenes, key=lambda c: (bool(c.ai_description), bool(c.visual_features), c.duration))
        item = compact_candidate(scene)
        item["scene_count"] = len(scenes)
        representatives.append(item)

    total = max(1, len(candidates))
    codec_mode = str(getattr(selector_config, "codec_glitch_mode", "off"))
    vector_enabled = bool(getattr(selector_config, "vector_effects", True))
    creative_enabled = bool(getattr(selector_config, "creative_effects", True)) and bool(getattr(selector_config, "transforms", True))
    codec_enabled = codec_mode != "off"

    return {
        "library": {
            "eligible_clips": len(clips),
            "eligible_scenes": len(candidates),
            "output_pool_note": "Only READY clips in the current output pool are represented.",
            "coverage": {
                "ai_described_scene_fraction": round(ai_count / total, 3),
                "visual_feature_scene_fraction": round(feature_count / total, 3),
            },
            "visual_worlds": [{"concept": k, "scenes": v} for k, v in tags.most_common(24)],
            "provenance_terms": [{"term": k, "scenes": v} for k, v in terms.most_common(18)],
            "motion_distribution": {k: round(v / total, 3) for k, v in motion_bins.items()},
            "palette_distribution": [{"color_family": k, "scenes": v} for k, v in palettes.most_common(10)],
            "representative_material": representatives,
        },
        "renderer": {
            "effect_families": EFFECT_FAMILIES,
            "raster_creative": RASTER_EFFECTS if creative_enabled else [],
            "vector": VECTOR_EFFECTS if vector_enabled else [],
            "codec": {
                "enabled": codec_enabled,
                "mode": codec_mode,
                "ffedit_on_path": bool(shutil.which("ffedit")),
                "effects": CODEC_EFFECTS if codec_enabled else [],
            },
            "hero": HERO_EFFECTS if creative_enabled else [],
            "composition_modes": COMPOSITION_MODES,
            "constraints": {
                "creative_enabled": creative_enabled,
                "vector_enabled": vector_enabled,
                "max_video_layers": int(getattr(selector_config, "max_video_layers", 1)),
                "source_fidelity_default": "high; source footage remains primary except sparse hero moments",
            },
        },
        "planning_contract": {
            "llm": "Choose the global visual arc and resource strategy from what actually exists.",
            "candidate_consultant": "May rank only bounded candidate scene IDs supplied later.",
            "deterministic_engine": "Owns beat-aligned cut times, hard duration/trim constraints, cooldowns, media validity and final execution.",
        },
    }
