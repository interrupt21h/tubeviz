# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass

from .semantic_compositing import EntityTrack, SceneSemanticAnalysis
from .semantic_materialize import SemanticEffect


@dataclass(frozen=True)
class SemanticDirectionInput:
    energy: float
    bass_weight: float
    percussive_ratio: float
    complexity: float = 0.5
    drop_probability: float = 0.0
    build_probability: float = 0.0
    transition: bool = False


def _primary_entity(analysis: SceneSemanticAnalysis) -> EntityTrack:
    ranked = sorted(
        analysis.entities,
        key=lambda entity: (
            entity.role != "primary_subject",
            entity.role not in {"subject", "moving_object", "foreground"},
            -entity.confidence,
            -entity.mean_area,
        ),
    )
    return ranked[0]


def direct_semantic_effects(
    analysis: SceneSemanticAnalysis,
    music: SemanticDirectionInput,
) -> tuple[SemanticEffect, ...]:
    """Choose sparse object/depth-aware treatments from scene + music features."""
    if not analysis.entities:
        return ()
    subject = _primary_entity(analysis)
    energy = max(0.0, min(1.0, music.energy))
    bass = max(0.0, min(1.0, music.bass_weight))
    percussion = max(0.0, min(1.0, music.percussive_ratio))
    complexity = max(0.0, min(1.0, music.complexity))
    motion = max(0.0, min(1.0, subject.motion))
    area = max(0.0, min(1.0, subject.mean_area))
    drop = max(0.0, min(1.0, music.drop_probability))
    build = max(0.0, min(1.0, music.build_probability))
    entity_count = len(analysis.entities)

    result: list[SemanticEffect] = []

    isolate = (0.38 + 0.42 * area) * (0.72 + 0.28 * (1.0 - energy))
    if area >= 0.025 and isolate >= 0.28:
        result.append(
            SemanticEffect(
                kind="subject_isolate",
                amount=min(0.92, isolate),
                background_blur=max(0.0, 0.18 + 0.32 * complexity),
                target_entity=subject.entity_id,
            )
        )

    echo = (0.42 * motion + 0.36 * percussion + 0.22 * drop) * energy
    if echo >= 0.24:
        result.append(
            SemanticEffect(
                kind="subject_echo",
                amount=min(1.0, echo),
                copies=3 + int(round(3 * drop)),
                spacing=0.025 + 0.055 * percussion,
                scale_step=0.018 + 0.045 * bass,
                hue_step=12.0 + 34.0 * complexity,
                target_entity=subject.entity_id,
            )
        )

    # Multi-object scenes get a semantic fragmentation treatment around builds/drops.
    split = (0.34 * energy + 0.30 * percussion + 0.24 * drop + 0.12 * build) * min(1.0, entity_count / 3.0)
    if entity_count >= 2 and split >= 0.30:
        result.append(
            SemanticEffect(
                kind="entity_split",
                amount=min(1.0, split),
                split_distance=0.035 + 0.09 * max(drop, percussion),
                rotation_step=2.0 + 8.0 * complexity,
                hue_step=10.0 + 42.0 * complexity,
            )
        )

    # Quieter or building passages can expose tracked contours instead of distorting
    # the entire image, which keeps effects attached to meaningful scene geometry.
    outline = (0.35 * build + 0.25 * complexity + 0.20 * (1.0 - energy)) * min(1.0, entity_count / 2.0)
    if entity_count >= 2 and outline >= 0.24 and split < 0.62:
        result.append(SemanticEffect(kind="entity_outline", amount=min(0.82, outline)))

    parallax = (0.24 + 0.54 * bass + 0.22 * energy) * (1.0 - 0.32 * motion)
    if parallax >= 0.26:
        result.append(
            SemanticEffect(
                kind="depth_parallax",
                amount=min(0.92, parallax),
                parallax_px=18.0 + 58.0 * bass + 24.0 * drop,
            )
        )

    # Keep treatment sparse. Strong multi-entity events displace generic parallax
    # rather than stacking every available effect simultaneously.
    if any(effect.kind == "entity_split" and effect.amount >= 0.58 for effect in result):
        result = [effect for effect in result if effect.kind != "depth_parallax"]
    return tuple(result[:4])
