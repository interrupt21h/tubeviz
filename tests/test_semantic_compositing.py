from __future__ import annotations

import numpy as np

from tubeviz.semantic_compositing import EntityTrack, SceneSemanticAnalysis, SemanticAnalysisConfig, estimate_depth, estimate_masks
from tubeviz.semantic_director import SemanticDirectionInput, direct_semantic_effects
from tubeviz.semantic_materialize import SemanticEffect, apply_effect, mask_transition


def _frame() -> np.ndarray:
    frame = np.zeros((72, 96, 3), dtype=np.uint8)
    frame[:, :] = (24, 36, 52)
    frame[18:58, 32:66] = (40, 180, 235)
    return frame


def _analysis(motion: float = 0.7) -> SceneSemanticAnalysis:
    return SceneSemanticAnalysis(
        version=1,
        scene_id=7,
        source_file="sample.mp4",
        start=0.0,
        end=2.0,
        fps=12.0,
        width=96,
        height=72,
        frame_count=24,
        mask_backend="classical",
        depth_backend="classical",
        entities=(
            EntityTrack(
                entity_id="foreground-0",
                label="foreground subject",
                role="primary_subject",
                confidence=0.82,
                mean_area=0.20,
                mean_center=(0.5, 0.5),
                motion=motion,
                mask_file="foreground-0.npz",
            ),
        ),
        depth_file="depth.npz",
    )


def test_classical_analysis_fallback_produces_temporal_assets() -> None:
    frames = [_frame(), np.roll(_frame(), 3, axis=1), np.roll(_frame(), 6, axis=1)]
    cfg = SemanticAnalysisConfig(mask_backend="classical", depth_backend="classical")
    depth, depth_backend = estimate_depth(frames, cfg)
    masks, mask_backend = estimate_masks(frames, depth, cfg)
    assert depth_backend == "classical"
    assert mask_backend == "classical"
    assert depth.shape == (3, 72, 96)
    assert len(masks) == 3
    assert all(mask.shape == (72, 96) for mask in masks)
    assert np.isfinite(depth).all()
    assert float(depth.min()) >= 0.0
    assert float(depth.max()) <= 1.0


def test_semantic_primitives_preserve_shape_and_change_pixels() -> None:
    frame = _frame()
    mask = np.zeros((72, 96), dtype=np.float32)
    mask[18:58, 32:66] = 1.0
    depth = np.tile(np.linspace(0.0, 1.0, 96, dtype=np.float32), (72, 1))
    for kind in ("subject_isolate", "subject_echo", "depth_parallax"):
        out = apply_effect(frame, mask, depth, SemanticEffect(kind=kind, amount=0.8))
        assert out.shape == frame.shape
        assert out.dtype == np.uint8
        assert np.any(out != frame)


def test_mask_transition_reveals_incoming_scene() -> None:
    a = np.zeros((32, 40, 3), dtype=np.uint8)
    b = np.full((32, 40, 3), 255, dtype=np.uint8)
    mask = np.zeros((32, 40), dtype=np.float32)
    mask[:, 10:30] = 1.0
    early = mask_transition(a, b, mask, 0.05)
    late = mask_transition(a, b, mask, 1.0)
    assert float(early.mean()) < float(late.mean())
    assert float(late.mean()) > 245.0


def test_director_uses_motion_transients_and_bass() -> None:
    effects = direct_semantic_effects(
        _analysis(),
        SemanticDirectionInput(
            energy=0.92,
            bass_weight=0.88,
            percussive_ratio=0.84,
            complexity=0.7,
            drop_probability=0.9,
        ),
    )
    kinds = {effect.kind for effect in effects}
    assert "subject_echo" in kinds
    assert "depth_parallax" in kinds
    assert len(effects) <= 3
