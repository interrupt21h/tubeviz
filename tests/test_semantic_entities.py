from __future__ import annotations

import numpy as np

from tubeviz.semantic_compositing import EntityTrack, SceneSemanticAnalysis
from tubeviz.semantic_director import SemanticDirectionInput, direct_semantic_effects
from tubeviz.semantic_entities import (
    EntityDecompositionConfig,
    EntityDetection,
    _classical_track,
    _role_for_label,
    detect_entities,
)
from tubeviz.semantic_materialize import entity_outline, entity_split


def _analysis(*entities: EntityTrack) -> SceneSemanticAnalysis:
    return SceneSemanticAnalysis(
        version=1,
        scene_id=1,
        source_file="/tmp/source.mp4",
        start=0.0,
        end=2.0,
        fps=12.0,
        width=64,
        height=48,
        frame_count=24,
        mask_backend="classical-flow",
        depth_backend="classical",
        entities=tuple(entities),
        depth_file="depth.npz",
    )


def _entity(entity_id: str, label: str, role: str, *, motion: float, area: float) -> EntityTrack:
    return EntityTrack(
        entity_id=entity_id,
        label=label,
        role=role,
        confidence=0.9,
        mean_area=area,
        mean_center=(0.5, 0.5),
        motion=motion,
        mask_file=f"{entity_id}.npz",
    )


def test_semantic_roles_are_label_aware() -> None:
    assert _role_for_label("person", 0.12, 0.8) == "primary_subject"
    assert _role_for_label("car", 0.08, 0.7) == "moving_object"
    assert _role_for_label("sky", 0.50, 0.1) == "background"
    assert _role_for_label("building", 0.30, 0.3) == "environment"


def test_classical_detector_and_tracker_work_without_ml() -> None:
    frame = np.zeros((64, 96, 3), dtype=np.uint8)
    frame[18:52, 34:66] = 255
    depth = np.zeros((64, 96), dtype=np.float32)
    depth[18:52, 34:66] = 1.0
    cfg = EntityDecompositionConfig(backend="classical", mask_backend="classical", min_area=0.004)
    detections, backend = detect_entities(frame, depth, cfg)
    assert backend == "classical"
    assert detections
    frames = [frame, np.roll(frame, 2, axis=1), np.roll(frame, 4, axis=1)]
    masks = _classical_track(frames, detections[0])
    assert len(masks) == 3
    assert all(mask.shape == frame.shape[:2] for mask in masks)
    assert np.count_nonzero(masks[0]) > 0


def test_entity_split_and_outline_are_mask_scoped() -> None:
    frame = np.zeros((64, 96, 3), dtype=np.uint8)
    frame[:, :] = (20, 40, 80)
    frame[18:50, 25:48] = (220, 180, 80)
    frame[10:34, 58:82] = (60, 220, 180)
    mask_a = np.zeros((64, 96), dtype=np.float32)
    mask_b = np.zeros((64, 96), dtype=np.float32)
    mask_a[18:50, 25:48] = 1.0
    mask_b[10:34, 58:82] = 1.0
    entities = [
        (_entity("person-0", "person", "primary_subject", motion=0.8, area=0.12), mask_a),
        (_entity("car-0", "car", "moving_object", motion=0.5, area=0.10), mask_b),
    ]
    split = entity_split(frame, entities, 0.9)
    outlined = entity_outline(frame, entities, 0.8)
    assert split.shape == frame.shape
    assert outlined.shape == frame.shape
    assert np.any(split != frame)
    assert np.any(outlined != frame)


def test_director_uses_multi_entity_fragmentation_on_drop() -> None:
    analysis = _analysis(
        _entity("person-0", "person", "primary_subject", motion=0.85, area=0.15),
        _entity("car-0", "car", "moving_object", motion=0.6, area=0.11),
        _entity("building-0", "building", "environment", motion=0.05, area=0.30),
    )
    effects = direct_semantic_effects(
        analysis,
        SemanticDirectionInput(
            energy=0.95,
            bass_weight=0.9,
            percussive_ratio=0.9,
            complexity=0.8,
            drop_probability=1.0,
            build_probability=0.2,
        ),
    )
    kinds = {effect.kind for effect in effects}
    assert "entity_split" in kinds
    targeted = [effect for effect in effects if effect.kind in {"subject_isolate", "subject_echo"}]
    assert targeted
    assert all(effect.target_entity == "person-0" for effect in targeted)
