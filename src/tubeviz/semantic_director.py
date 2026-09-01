# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass

from .semantic_compositing import SceneSemanticAnalysis
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


def direct_semantic_effects(
    analysis: SceneSemanticAnalysis,
    music: SemanticDirectionInput,
) -> tuple[SemanticEffect, ...]:
    """Choose a sparse semantic treatment from measured scene + music features.

    This intentionally returns deterministic primitives instead of running an LLM at
    render time. A timeline planner can serialize the returned values or materialize
    them immediately.
    """
    if not analysis.entities:
        return ()
    subject = analysis.entities[0]
    energy = max(0.0, min(1.0, music.energy))
    bass = max(0.0, min(1.0, music.bass_weight))
    percussion = max(0.0, min(1.0, music.percussive_ratio))
    motion = max(0.0, min(1.0, subject.motion))
    area = max(0.0, min(1.0, subject.mean_area))
    drop = max(0.0, min(1.0, music.drop_probability))

    result: list[SemanticEffect] = []

    # Subject protection/isolation is strongest for clear, sizable subjects and
    # quieter passages where keeping a stable focal plane reads as intentional.
    isolate = (0.38 + 0.42 * area) * (0.72 + 0.28 * (1.0 - energy))
    if area >= 0.035 and isolate >= 0.28:
        result.append(
            SemanticEffect(
                kind="subject_isolate",
                amount=min(0.92, isolate),
                background_blur=max(0.0, 0.18 + 0.32 * music.complexity),
            )
        )

    # Echoes work well when the tracked subject itself moves and the music has
    # transient energy. Drops deliberately increase copy count/spacing.
    echo = (0.42 * motion + 0.36 * percussion + 0.22 * drop) * energy
    if echo >= 0.24:
        result.append(
            SemanticEffect(
                kind="subject_echo",
                amount=min(1.0, echo),
                copies=3 + int(round(3 * drop)),
                spacing=0.025 + 0.055 * percussion,
                scale_step=0.018 + 0.045 * bass,
                hue_step=12.0 + 34.0 * music.complexity,
            )
        )

    # Depth parallax is useful across the whole energy range but should not dominate
    # fast-moving foreground subjects. Bass controls apparent camera displacement.
    parallax = (0.24 + 0.54 * bass + 0.22 * energy) * (1.0 - 0.32 * motion)
    if parallax >= 0.26:
        result.append(
            SemanticEffect(
                kind="depth_parallax",
                amount=min(0.92, parallax),
                parallax_px=18.0 + 58.0 * bass + 24.0 * drop,
            )
        )

    return tuple(result[:3])
