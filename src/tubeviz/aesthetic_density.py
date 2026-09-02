# SPDX-License-Identifier: Apache-2.0
"""Measure treatment density in a directed timeline.

These metrics intentionally describe visual *grammar* rather than renderer
implementation details.  They make it possible to regression-test whether a
source-first or Classic timeline has drifted back toward persistent effect
stacking even when every individual effect still renders correctly.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any


_EPSILON = 1e-6

_CREATIVE_FIELDS = (
    "flow_warp",
    "flow_trails",
    "flow_rgb",
    "temporal_echo",
    "temporal_rgb",
    "temporal_smear",
    "camera_energy",
    "depth_parallax",
    "depth_fog",
    "background_warp",
    "feedback",
    "local_symmetry",
    "texture_bloom",
    "texture_streaks",
    "palette_strength",
    "abstraction",
)

_CREATIVE_TEMPORAL_FIELDS = (
    "flow_trails",
    "temporal_echo",
    "temporal_rgb",
    "temporal_smear",
    "feedback",
    "history_inherit",
)

_LEGACY_EFFECT_FIELDS = (
    "feedback",
    "glitch",
    "noise",
    "pixelate",
    "rgb_split",
    "scanlines",
    "vignette",
    "ripple",
    "kaleidoscope",
    "tiles",
    "tunnel",
    "posterize",
    "edge",
    "strobe",
    "shutter",
    "slit_scan",
    "frame_echo",
    "mirror_corridor",
    "mask_wipe",
    "solarize",
    "datamosh",
    "block_displace",
    "chroma_delay",
    "vhs_tracking",
    "vortex",
    "motion_trails",
    "slice_recursion",
)


CLASSIC_032_DENSITY_LIMITS: dict[str, float] = {
    "creative_fx_fraction": 0.0,
    "hero_fraction": 0.0,
    "creative_temporal_fraction": 0.0,
    "max_visible_vector_families": 2.0,
}


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, Mapping):
            return dumped
    data = getattr(value, "__dict__", None)
    return data if isinstance(data, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _number(mapping: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(mapping.get(key, default) or 0.0)
    except (TypeError, ValueError):
        return default


def _any_active(mapping: Mapping[str, Any], fields: Sequence[str]) -> bool:
    return any(abs(_number(mapping, field)) > _EPSILON for field in fields)


def _vector_count(direction: Mapping[str, Any]) -> int:
    count = 0
    for effect in _sequence(direction.get("vector_effects", ())):
        item = _mapping(effect)
        if item.get("visible", True) and _number(item, "amount") > _EPSILON and _number(item, "opacity", 1.0) > _EPSILON:
            count += 1
    return count


def _codec_active(scene: Mapping[str, Any], direction: Mapping[str, Any]) -> bool:
    if any(_number(_mapping(effect), "amount") > _EPSILON for effect in _sequence(direction.get("codec_effects", ()))):
        return True
    materialization = _mapping(scene.get("codec_materialization"))
    return bool(materialization.get("materialized", False))


def _clean_runs(values: Sequence[bool]) -> list[int]:
    runs: list[int] = []
    current = 0
    for clean in values:
        if clean:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def measure_aesthetic_density(timeline: Any) -> dict[str, float | int]:
    """Return visual-treatment density metrics for a directed timeline.

    ``timeline`` may be a :class:`DirectedTimeline`, any compatible Pydantic
    model, or a decoded timeline dictionary.  Fractions are shot fractions in
    the inclusive range 0..1.
    """

    root = _mapping(timeline)
    scenes = list(_sequence(root.get("scene_plan", ())))
    if not scenes:
        return {
            "shots": 0,
            "creative_fx_fraction": 0.0,
            "hero_fraction": 0.0,
            "creative_temporal_fraction": 0.0,
            "vector_fraction": 0.0,
            "codec_fraction": 0.0,
            "layered_fraction": 0.0,
            "legacy_fx_fraction": 0.0,
            "clean_shot_fraction": 0.0,
            "mean_treatment_families": 0.0,
            "max_treatment_families": 0,
            "mean_visible_vector_families": 0.0,
            "max_visible_vector_families": 0,
            "mean_clean_run": 0.0,
            "max_clean_run": 0,
        }

    creative_count = hero_count = creative_temporal_count = 0
    vector_count = codec_count = layered_count = legacy_count = 0
    treatment_counts: list[int] = []
    vector_counts: list[int] = []
    clean_flags: list[bool] = []

    for raw_scene in scenes:
        scene = _mapping(raw_scene)
        direction = _mapping(scene.get("direction"))
        creative = _mapping(direction.get("creative"))
        transform = _mapping(scene.get("transform"))

        creative_active = _any_active(creative, _CREATIVE_FIELDS)
        hero_active = bool(creative.get("hero_kind")) and _number(creative, "hero_amount") > _EPSILON
        creative_temporal = _any_active(creative, _CREATIVE_TEMPORAL_FIELDS)
        visible_vectors = _vector_count(direction)
        codec_active = _codec_active(scene, direction)
        layered = bool(_sequence(scene.get("layers", ()))) and str(scene.get("composition_mode", "single")) != "single"
        legacy_active = _any_active(transform, _LEGACY_EFFECT_FIELDS)

        creative_count += int(creative_active)
        hero_count += int(hero_active)
        creative_temporal_count += int(creative_temporal)
        vector_count += int(visible_vectors > 0)
        codec_count += int(codec_active)
        layered_count += int(layered)
        legacy_count += int(legacy_active)
        vector_counts.append(visible_vectors)

        families = sum((
            creative_active,
            hero_active,
            creative_temporal,
            visible_vectors > 0,
            codec_active,
            layered,
            legacy_active,
        ))
        treatment_counts.append(int(families))
        clean_flags.append(families == 0)

    shot_count = len(scenes)
    runs = _clean_runs(clean_flags)
    fraction = lambda count: float(count) / shot_count
    return {
        "shots": shot_count,
        "creative_fx_fraction": fraction(creative_count),
        "hero_fraction": fraction(hero_count),
        "creative_temporal_fraction": fraction(creative_temporal_count),
        "vector_fraction": fraction(vector_count),
        "codec_fraction": fraction(codec_count),
        "layered_fraction": fraction(layered_count),
        "legacy_fx_fraction": fraction(legacy_count),
        "clean_shot_fraction": fraction(sum(clean_flags)),
        "mean_treatment_families": mean(treatment_counts),
        "max_treatment_families": max(treatment_counts),
        "mean_visible_vector_families": mean(vector_counts),
        "max_visible_vector_families": max(vector_counts),
        "mean_clean_run": mean(runs) if runs else 0.0,
        "max_clean_run": max(runs) if runs else 0,
    }


def classic_032_density_violations(report: Mapping[str, float | int]) -> list[str]:
    """Describe violations of the non-negotiable Classic 0.32 grammar limits."""

    violations: list[str] = []
    for metric, ceiling in CLASSIC_032_DENSITY_LIMITS.items():
        value = float(report.get(metric, 0.0))
        if value > ceiling + _EPSILON:
            violations.append(f"{metric}={value:.4g} exceeds Classic 0.32 ceiling {ceiling:.4g}")
    return violations
