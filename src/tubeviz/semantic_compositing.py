# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import cv2
import numpy as np


ANALYSIS_VERSION = 1


@dataclass(frozen=True)
class SemanticAnalysisConfig:
    sample_fps: float = 12.0
    mask_size: int = 512
    depth_size: int = 518
    max_objects: int = 6
    min_object_fraction: float = 0.015
    foreground_threshold: float = 0.48
    mask_backend: str = "auto"
    depth_backend: str = "auto"
    sam2_model: str = "facebook/sam2.1-hiera-small"
    video_depth_encoder: str = "vits"
    video_depth_checkpoint: str | None = None
    device: str = "auto"


@dataclass(frozen=True)
class EntityTrack:
    entity_id: str
    label: str
    role: str
    confidence: float
    mean_area: float
    mean_center: tuple[float, float]
    motion: float
    mask_file: str


@dataclass(frozen=True)
class SceneSemanticAnalysis:
    version: int
    scene_id: int
    source_file: str
    start: float
    end: float
    fps: float
    width: int
    height: int
    frame_count: int
    mask_backend: str
    depth_backend: str
    entities: tuple[EntityTrack, ...] = field(default_factory=tuple)
    depth_file: str | None = None
    depth_near: float = 0.0
    depth_far: float = 1.0

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["entities"] = [asdict(item) for item in self.entities]
        return data


class SemanticAssetStore:
    def __init__(self, library_root: str | Path):
        self.root = Path(library_root).expanduser().resolve() / "metadata" / "semantic_compositing"

    def scene_dir(self, scene_id: int) -> Path:
        return self.root / f"scene-{scene_id:08d}"

    def analysis_path(self, scene_id: int) -> Path:
        return self.scene_dir(scene_id) / "analysis.json"

    def load(self, scene_id: int) -> SceneSemanticAnalysis | None:
        path = self.analysis_path(scene_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        entities = tuple(EntityTrack(**row) for row in data.pop("entities", []))
        return SceneSemanticAnalysis(entities=entities, **data)

    def save(self, analysis: SceneSemanticAnalysis) -> Path:
        target = self.scene_dir(analysis.scene_id)
        target.mkdir(parents=True, exist_ok=True)
        path = target / "analysis.json"
        path.write_text(json.dumps(analysis.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path


def _resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _open_segment(path: Path, start: float, end: float, sample_fps: float) -> tuple[list[np.ndarray], float]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"unable to open video: {path}")
    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    step = max(1, int(round(source_fps / max(0.1, sample_fps))))
    first = max(0, int(math.floor(start * source_fps)))
    last = max(first + 1, int(math.ceil(end * source_fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    frames: list[np.ndarray] = []
    frame_index = first
    while frame_index < last:
        ok, frame = cap.read()
        if not ok:
            break
        if (frame_index - first) % step == 0:
            frames.append(frame)
        frame_index += 1
    cap.release()
    if not frames:
        raise RuntimeError(f"no frames decoded from {path} between {start:.3f}s and {end:.3f}s")
    return frames, source_fps / step


def _normalize_depth(depth: np.ndarray) -> np.ndarray:
    value = np.asarray(depth, dtype=np.float32)
    finite = value[np.isfinite(value)]
    if finite.size == 0:
        return np.zeros(value.shape, dtype=np.float32)
    lo, hi = np.percentile(finite, [2.0, 98.0])
    if hi <= lo + 1e-8:
        return np.zeros(value.shape, dtype=np.float32)
    return np.clip((value - lo) / (hi - lo), 0.0, 1.0)


def _classical_depth(frames: Sequence[np.ndarray], size: int) -> np.ndarray:
    """Cheap deterministic pseudo-depth fallback.

    This is deliberately not presented as metric depth. It produces a temporally
    smoothed saliency/spatial prior so semantic compositing remains usable without
    heavyweight ML dependencies.
    """
    result: list[np.ndarray] = []
    previous: np.ndarray | None = None
    for frame in frames:
        h, w = frame.shape[:2]
        scale = min(1.0, size / max(h, w))
        small = cv2.resize(frame, (max(2, round(w * scale)), max(2, round(h * scale))))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        detail = cv2.Laplacian(gray, cv2.CV_32F)
        detail = cv2.GaussianBlur(np.abs(detail), (0, 0), 4.0)
        yy, xx = np.mgrid[0:small.shape[0], 0:small.shape[1]].astype(np.float32)
        xx = xx / max(1, small.shape[1] - 1) - 0.5
        yy = yy / max(1, small.shape[0] - 1) - 0.5
        center = np.exp(-(xx * xx + yy * yy) / 0.32)
        estimate = _normalize_depth(0.58 * center + 0.42 * detail)
        estimate = cv2.resize(estimate, (w, h), interpolation=cv2.INTER_CUBIC)
        if previous is not None:
            estimate = 0.76 * previous + 0.24 * estimate
        previous = estimate
        result.append(estimate.astype(np.float32))
    return np.stack(result)


def _video_depth_anything(frames: Sequence[np.ndarray], cfg: SemanticAnalysisConfig) -> np.ndarray:
    import torch
    from video_depth_anything.video_depth import VideoDepthAnything

    encoder = cfg.video_depth_encoder
    model_configs = {
        "vits": {"encoder": "vits", "features": 64, "out_channels": [48, 96, 192, 384]},
        "vitl": {"encoder": "vitl", "features": 256, "out_channels": [256, 512, 1024, 1024]},
    }
    if encoder not in model_configs:
        raise ValueError(f"unsupported Video Depth Anything encoder: {encoder}")
    checkpoint = cfg.video_depth_checkpoint
    if not checkpoint:
        raise RuntimeError("video_depth_checkpoint is required for the video-depth-anything backend")
    device = _resolve_device(cfg.device)
    model = VideoDepthAnything(**model_configs[encoder])
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model = model.to(device).eval()
    rgb = [cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) for frame in frames]
    with torch.inference_mode():
        depth, _ = model.infer_video_depth(rgb, target_fps=cfg.sample_fps, input_size=cfg.depth_size, device=device, fp32=device == "cpu")
    return np.stack([_normalize_depth(item) for item in depth]).astype(np.float32)


def estimate_depth(frames: Sequence[np.ndarray], cfg: SemanticAnalysisConfig) -> tuple[np.ndarray, str]:
    backend = cfg.depth_backend
    if backend in {"auto", "video-depth-anything"}:
        try:
            return _video_depth_anything(frames, cfg), "video-depth-anything"
        except (ImportError, ModuleNotFoundError, RuntimeError, FileNotFoundError):
            if backend != "auto":
                raise
    return _classical_depth(frames, cfg.depth_size), "classical"


def _foreground_mask(frame: np.ndarray, depth: np.ndarray, threshold: float) -> np.ndarray:
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturation = hsv[..., 1].astype(np.float32) / 255.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    detail = _normalize_depth(cv2.GaussianBlur(np.abs(cv2.Laplacian(gray, cv2.CV_32F)), (0, 0), 2.5))
    score = 0.62 * depth + 0.22 * saturation + 0.16 * detail
    mask = (score >= threshold).astype(np.uint8) * 255
    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cleaned = np.zeros((h, w), dtype=np.uint8)
    min_area = max(64, int(h * w * 0.01))
    for idx in range(1, count):
        if stats[idx, cv2.CC_STAT_AREA] >= min_area:
            cleaned[labels == idx] = 255
    return cleaned


def _track_from_masks(masks: Sequence[np.ndarray]) -> EntityTrack:
    centers: list[tuple[float, float]] = []
    areas: list[float] = []
    for mask in masks:
        ys, xs = np.nonzero(mask > 127)
        if xs.size:
            centers.append((float(xs.mean() / mask.shape[1]), float(ys.mean() / mask.shape[0])))
            areas.append(float(xs.size / mask.size))
        elif centers:
            centers.append(centers[-1])
            areas.append(0.0)
        else:
            centers.append((0.5, 0.5))
            areas.append(0.0)
    motion = 0.0
    if len(centers) > 1:
        motion = float(np.mean([math.dist(a, b) for a, b in zip(centers, centers[1:])]))
    center = tuple(np.mean(np.asarray(centers), axis=0).tolist())
    area = float(np.mean(areas))
    return EntityTrack(
        entity_id="foreground-0",
        label="foreground subject",
        role="primary_subject",
        confidence=float(np.clip(0.45 + area * 1.5, 0.0, 0.92)),
        mean_area=area,
        mean_center=(float(center[0]), float(center[1])),
        motion=float(np.clip(motion * 4.0, 0.0, 1.0)),
        mask_file="foreground-0.npz",
    )


def _sam2_masks(frames: Sequence[np.ndarray], cfg: SemanticAnalysisConfig) -> tuple[list[np.ndarray], str]:
    from sam2.build_sam import build_sam2_video_predictor_hf

    device = _resolve_device(cfg.device)
    with tempfile.TemporaryDirectory(prefix="tubeviz-sam2-") as temp:
        frame_dir = Path(temp)
        for index, frame in enumerate(frames):
            cv2.imwrite(str(frame_dir / f"{index:06d}.jpg"), frame)
        predictor = build_sam2_video_predictor_hf(cfg.sam2_model, device=device)
        state = predictor.init_state(video_path=str(frame_dir), offload_video_to_cpu=device != "cuda")
        h, w = frames[0].shape[:2]
        points = np.asarray([[w * 0.5, h * 0.52]], dtype=np.float32)
        labels = np.asarray([1], dtype=np.int32)
        predictor.add_new_points_or_box(state, frame_idx=0, obj_id=1, points=points, labels=labels)
        by_frame: dict[int, np.ndarray] = {}
        for frame_idx, obj_ids, logits in predictor.propagate_in_video(state):
            if 1 in list(obj_ids):
                position = list(obj_ids).index(1)
                mask = (logits[position] > 0.0).detach().cpu().numpy().squeeze().astype(np.uint8) * 255
                by_frame[int(frame_idx)] = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
        masks = [by_frame.get(index, np.zeros((h, w), dtype=np.uint8)) for index in range(len(frames))]
        if not any(np.count_nonzero(mask) for mask in masks):
            raise RuntimeError("SAM 2 did not produce a usable foreground track")
        return masks, "sam2"


def estimate_masks(frames: Sequence[np.ndarray], depth: np.ndarray, cfg: SemanticAnalysisConfig) -> tuple[list[np.ndarray], str]:
    if cfg.mask_backend in {"auto", "sam2"}:
        try:
            return _sam2_masks(frames, cfg)
        except (ImportError, ModuleNotFoundError, RuntimeError, FileNotFoundError):
            if cfg.mask_backend != "auto":
                raise
    return [
        _foreground_mask(frame, depth[index], cfg.foreground_threshold)
        for index, frame in enumerate(frames)
    ], "classical"


def analyze_scene(
    library_root: str | Path,
    scene_id: int,
    source_file: str | Path,
    start: float,
    end: float,
    cfg: SemanticAnalysisConfig | None = None,
    *,
    force: bool = False,
) -> SceneSemanticAnalysis:
    cfg = cfg or SemanticAnalysisConfig()
    store = SemanticAssetStore(library_root)
    cached = store.load(scene_id)
    if cached is not None and cached.version == ANALYSIS_VERSION and not force:
        return cached
    frames, fps = _open_segment(Path(source_file), start, end, cfg.sample_fps)
    depth, depth_backend = estimate_depth(frames, cfg)
    masks, mask_backend = estimate_masks(frames, depth, cfg)
    scene_dir = store.scene_dir(scene_id)
    scene_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(scene_dir / "depth.npz", depth=depth.astype(np.float16))
    stack = np.stack(masks).astype(np.uint8)
    np.savez_compressed(scene_dir / "foreground-0.npz", mask=stack)
    track = _track_from_masks(masks)
    h, w = frames[0].shape[:2]
    analysis = SceneSemanticAnalysis(
        version=ANALYSIS_VERSION,
        scene_id=int(scene_id),
        source_file=str(Path(source_file).resolve()),
        start=float(start),
        end=float(end),
        fps=float(fps),
        width=int(w),
        height=int(h),
        frame_count=len(frames),
        mask_backend=mask_backend,
        depth_backend=depth_backend,
        entities=(track,),
        depth_file="depth.npz",
    )
    store.save(analysis)
    return analysis


def analyze_library_scene(library: Any, scene_id: int, cfg: SemanticAnalysisConfig | None = None, *, force: bool = False) -> SceneSemanticAnalysis:
    """Analyze a ClipLibrary scene without coupling this module to library internals."""
    with library.connect() as db:
        row = db.execute(
            """
            SELECT s.id, s.start_time, s.end_time, c.normalized_path, c.original_path
            FROM scenes s JOIN clips c ON c.id = s.clip_id WHERE s.id = ?
            """,
            (int(scene_id),),
        ).fetchone()
    if row is None:
        raise KeyError(f"scene {scene_id} does not exist")
    media = row["normalized_path"] or row["original_path"]
    if not media:
        raise RuntimeError(f"scene {scene_id} has no local media")
    path = Path(media)
    if not path.is_absolute():
        path = library.root / path
    return analyze_scene(library.root, int(scene_id), path, float(row["start_time"]), float(row["end_time"]), cfg, force=force)


def iter_scene_ids(library: Any, *, selected_only: bool = False) -> Iterator[int]:
    with library.connect() as db:
        if selected_only:
            rows = db.execute(
                """SELECT s.id FROM scenes s JOIN output_selection o ON o.clip_id=s.clip_id ORDER BY s.id"""
            ).fetchall()
        else:
            rows = db.execute("SELECT id FROM scenes ORDER BY id").fetchall()
    for row in rows:
        yield int(row["id"])
