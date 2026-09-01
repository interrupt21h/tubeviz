# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import math
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from .semantic_compositing import (
    EntityTrack,
    SceneSemanticAnalysis,
    SemanticAssetStore,
    _open_segment,
    _resolve_device,
)


@dataclass(frozen=True)
class EntityDecompositionConfig:
    backend: str = "auto"
    mask_backend: str = "auto"
    detector_model: str = "IDEA-Research/grounding-dino-tiny"
    sam2_model: str = "facebook/sam2.1-hiera-small"
    labels: tuple[str, ...] = (
        "person", "dancer", "animal", "car", "vehicle", "building",
        "architecture", "sky", "water", "tree", "foreground object",
    )
    box_threshold: float = 0.30
    text_threshold: float = 0.25
    max_objects: int = 8
    min_area: float = 0.008
    device: str = "auto"


@dataclass(frozen=True)
class EntityDetection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]


def _canonical_label(label: str) -> str:
    value = label.lower().strip().rstrip(".")
    aliases = {
        "dancer": "person",
        "people": "person",
        "human": "person",
        "automobile": "car",
        "vehicle": "vehicle",
        "architecture": "building",
    }
    return aliases.get(value, value)


def _role_for_label(label: str, area: float, mean_depth: float) -> str:
    label = _canonical_label(label)
    if label in {"person", "animal"}:
        return "primary_subject" if area >= 0.025 else "subject"
    if label in {"car", "vehicle"}:
        return "moving_object"
    if label in {"sky", "water"}:
        return "background"
    if label in {"building", "tree"}:
        return "environment"
    if mean_depth >= 0.62:
        return "foreground"
    if mean_depth <= 0.32:
        return "background"
    return "object"


def _detect_grounding_dino(frame: np.ndarray, cfg: EntityDecompositionConfig) -> list[EntityDetection]:
    import torch
    from PIL import Image
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    device = _resolve_device(cfg.device)
    processor = AutoProcessor.from_pretrained(cfg.detector_model)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(cfg.detector_model).to(device).eval()
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    text = ". ".join(cfg.labels) + "."
    inputs = processor(images=image, text=text, return_tensors="pt")
    inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
    with torch.inference_mode():
        outputs = model(**inputs)
    target_sizes = torch.tensor([[frame.shape[0], frame.shape[1]]], device=device)
    kwargs = {
        "target_sizes": target_sizes,
        "box_threshold": cfg.box_threshold,
        "text_threshold": cfg.text_threshold,
    }
    try:
        result = processor.post_process_grounded_object_detection(
            outputs,
            inputs.get("input_ids"),
            **kwargs,
        )[0]
    except TypeError:
        result = processor.post_process_grounded_object_detection(outputs, **kwargs)[0]

    labels = result.get("text_labels", result.get("labels", []))
    detections: list[EntityDetection] = []
    h, w = frame.shape[:2]
    for score, label, box in zip(result["scores"], labels, result["boxes"]):
        if hasattr(label, "item") and not isinstance(label, str):
            label = str(label.item())
        label = _canonical_label(str(label))
        coords = [float(v) for v in box.detach().cpu().tolist()]
        x1, y1, x2, y2 = coords
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1) / max(1.0, float(w * h))
        if area < cfg.min_area:
            continue
        detections.append(EntityDetection(label, float(score.detach().cpu()), (x1, y1, x2, y2)))
    detections.sort(key=lambda item: item.confidence, reverse=True)
    return detections[: cfg.max_objects]


def _detect_classical(frame: np.ndarray, depth: np.ndarray, cfg: EntityDecompositionConfig) -> list[EntityDetection]:
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 70, 160)
    near = (depth >= np.quantile(depth, 0.62)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(cv2.bitwise_or(edges, near), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    candidates: list[EntityDetection] = []
    for idx in range(1, count):
        x, y, bw, bh, area_px = [int(v) for v in stats[idx]]
        area = area_px / max(1.0, float(w * h))
        if area < cfg.min_area or area > 0.72:
            continue
        score = float(np.clip(0.35 + area * 2.5, 0.0, 0.78))
        candidates.append(EntityDetection("foreground object", score, (float(x), float(y), float(x + bw), float(y + bh))))
    candidates.sort(key=lambda item: item.confidence, reverse=True)
    if not candidates:
        candidates.append(EntityDetection("foreground object", 0.4, (w * 0.22, h * 0.18, w * 0.78, h * 0.9)))
    return candidates[: cfg.max_objects]


def detect_entities(frame: np.ndarray, depth: np.ndarray, cfg: EntityDecompositionConfig) -> tuple[list[EntityDetection], str]:
    if cfg.backend in {"auto", "grounding-dino"}:
        try:
            detections = _detect_grounding_dino(frame, cfg)
            if detections:
                return detections, "grounding-dino"
        except (ImportError, ModuleNotFoundError, RuntimeError, OSError, ValueError):
            if cfg.backend == "grounding-dino":
                raise
    return _detect_classical(frame, depth, cfg), "classical"


def _box_mask(shape: tuple[int, int], box: tuple[float, float, float, float]) -> np.ndarray:
    h, w = shape
    x1, y1, x2, y2 = box
    x1i = max(0, min(w - 1, int(round(x1))))
    y1i = max(0, min(h - 1, int(round(y1))))
    x2i = max(x1i + 1, min(w, int(round(x2))))
    y2i = max(y1i + 1, min(h, int(round(y2))))
    mask = np.zeros((h, w), np.uint8)
    mask[y1i:y2i, x1i:x2i] = 255
    return mask


def _classical_track(frames: Sequence[np.ndarray], detection: EntityDetection) -> list[np.ndarray]:
    h, w = frames[0].shape[:2]
    x1, y1, x2, y2 = detection.box
    initial = _box_mask((h, w), detection.box)
    previous_gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
    previous_mask = initial
    masks = [initial]
    for frame in frames[1:]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(previous_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        ys, xs = np.nonzero(previous_mask > 127)
        if xs.size:
            dx = float(np.median(flow[ys, xs, 0]))
            dy = float(np.median(flow[ys, xs, 1]))
        else:
            dx = dy = 0.0
        matrix = np.float32([[1, 0, dx], [0, 1, dy]])
        warped = cv2.warpAffine(previous_mask, matrix, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
        masks.append(warped)
        previous_mask = warped
        previous_gray = gray
    return masks


def _sam2_tracks(frames: Sequence[np.ndarray], detections: Sequence[EntityDetection], cfg: EntityDecompositionConfig) -> list[list[np.ndarray]]:
    from sam2.build_sam import build_sam2_video_predictor_hf

    device = _resolve_device(cfg.device)
    h, w = frames[0].shape[:2]
    with tempfile.TemporaryDirectory(prefix="tubeviz-sam2-entities-") as temp:
        frame_dir = Path(temp)
        for index, frame in enumerate(frames):
            cv2.imwrite(str(frame_dir / f"{index:06d}.jpg"), frame)
        predictor = build_sam2_video_predictor_hf(cfg.sam2_model, device=device)
        state = predictor.init_state(video_path=str(frame_dir), offload_video_to_cpu=device != "cuda")
        for index, detection in enumerate(detections, 1):
            box = np.asarray(detection.box, dtype=np.float32)
            predictor.add_new_points_or_box(state, frame_idx=0, obj_id=index, box=box)
        result = [[np.zeros((h, w), np.uint8) for _ in frames] for _ in detections]
        for frame_idx, obj_ids, logits in predictor.propagate_in_video(state):
            ids = [int(value) for value in obj_ids]
            for object_index in range(len(detections)):
                obj_id = object_index + 1
                if obj_id not in ids:
                    continue
                position = ids.index(obj_id)
                mask = (logits[position] > 0.0).detach().cpu().numpy().squeeze().astype(np.uint8) * 255
                result[object_index][int(frame_idx)] = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
        return result


def track_entities(frames: Sequence[np.ndarray], detections: Sequence[EntityDetection], cfg: EntityDecompositionConfig) -> tuple[list[list[np.ndarray]], str]:
    if cfg.mask_backend in {"auto", "sam2"}:
        try:
            tracks = _sam2_tracks(frames, detections, cfg)
            if any(any(np.count_nonzero(mask) for mask in track) for track in tracks):
                return tracks, "sam2-multi"
        except (ImportError, ModuleNotFoundError, RuntimeError, OSError, ValueError):
            if cfg.mask_backend == "sam2":
                raise
    return [_classical_track(frames, detection) for detection in detections], "classical-flow"


def _track_metadata(
    detection: EntityDetection,
    masks: Sequence[np.ndarray],
    depth: np.ndarray,
    entity_id: str,
    mask_file: str,
) -> tuple[EntityTrack, dict[str, float | str]]:
    centers: list[tuple[float, float]] = []
    areas: list[float] = []
    depths: list[float] = []
    for index, mask in enumerate(masks):
        ys, xs = np.nonzero(mask > 127)
        if xs.size:
            centers.append((float(xs.mean() / mask.shape[1]), float(ys.mean() / mask.shape[0])))
            areas.append(float(xs.size / mask.size))
            depths.append(float(np.mean(depth[index][ys, xs])))
        else:
            centers.append(centers[-1] if centers else (0.5, 0.5))
            areas.append(0.0)
    motion = float(np.mean([math.dist(a, b) for a, b in zip(centers, centers[1:])])) if len(centers) > 1 else 0.0
    center = np.mean(np.asarray(centers), axis=0)
    area = float(np.mean(areas))
    mean_depth = float(np.mean(depths)) if depths else 0.5
    label = _canonical_label(detection.label)
    role = _role_for_label(label, area, mean_depth)
    track = EntityTrack(
        entity_id=entity_id,
        label=label,
        role=role,
        confidence=float(np.clip(detection.confidence, 0.0, 1.0)),
        mean_area=area,
        mean_center=(float(center[0]), float(center[1])),
        motion=float(np.clip(motion * 4.0, 0.0, 1.0)),
        mask_file=mask_file,
    )
    return track, {"mean_depth": mean_depth, "role": role, "label": label}


def decompose_scene_entities(
    library_root: str | Path,
    analysis: SceneSemanticAnalysis,
    cfg: EntityDecompositionConfig | None = None,
    *,
    force: bool = False,
) -> SceneSemanticAnalysis:
    cfg = cfg or EntityDecompositionConfig()
    store = SemanticAssetStore(library_root)
    scene_dir = store.scene_dir(analysis.scene_id)
    manifest_path = scene_dir / "entities.json"
    if manifest_path.exists() and len(analysis.entities) > 1 and not force:
        return analysis
    frames, _ = _open_segment(Path(analysis.source_file), analysis.start, analysis.end, analysis.fps)
    if not analysis.depth_file:
        raise RuntimeError(f"scene {analysis.scene_id} has no depth asset")
    depth = np.load(scene_dir / analysis.depth_file)["depth"].astype(np.float32)
    seed_depth = depth[0]
    detections, detector_backend = detect_entities(frames[0], seed_depth, cfg)
    tracks, tracker_backend = track_entities(frames, detections, cfg)

    entities: list[EntityTrack] = []
    manifest: dict[str, object] = {
        "version": 1,
        "detector_backend": detector_backend,
        "tracker_backend": tracker_backend,
        "entities": [],
    }
    for index, (detection, masks) in enumerate(zip(detections, tracks)):
        entity_id = f"entity-{index:02d}"
        mask_file = f"{entity_id}.npz"
        np.savez_compressed(scene_dir / mask_file, mask=np.stack(masks).astype(np.uint8))
        track, extra = _track_metadata(detection, masks, depth, entity_id, mask_file)
        if track.mean_area < cfg.min_area:
            continue
        entities.append(track)
        row = asdict(track)
        row.update(extra)
        row["box"] = list(detection.box)
        manifest["entities"].append(row)

    if not entities:
        return analysis
    entities.sort(key=lambda item: (item.role != "primary_subject", -item.confidence, -item.mean_area))
    updated = replace(analysis, entities=tuple(entities), mask_backend=tracker_backend)
    store.save(updated)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return updated
