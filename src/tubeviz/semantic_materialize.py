# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from .semantic_compositing import SceneSemanticAnalysis, SemanticAssetStore


@dataclass(frozen=True)
class SemanticEffect:
    kind: str
    amount: float = 1.0
    copies: int = 4
    spacing: float = 0.055
    scale_step: float = 0.035
    hue_step: float = 22.0
    parallax_px: float = 44.0
    background_blur: float = 0.0
    transition_softness: float = 0.08


def _load_assets(library_root: str | Path, analysis: SceneSemanticAnalysis) -> tuple[np.ndarray, np.ndarray]:
    scene_dir = SemanticAssetStore(library_root).scene_dir(analysis.scene_id)
    if not analysis.entities:
        raise RuntimeError(f"scene {analysis.scene_id} has no semantic entities")
    masks = np.load(scene_dir / analysis.entities[0].mask_file)["mask"].astype(np.float32) / 255.0
    if not analysis.depth_file:
        raise RuntimeError(f"scene {analysis.scene_id} has no depth asset")
    depth = np.load(scene_dir / analysis.depth_file)["depth"].astype(np.float32)
    return masks, depth


def _sample_asset(stack: np.ndarray, progress: float, size: tuple[int, int]) -> np.ndarray:
    index = min(len(stack) - 1, max(0, int(round(progress * (len(stack) - 1)))))
    asset = stack[index]
    if asset.shape[::-1] != size:
        asset = cv2.resize(asset, size, interpolation=cv2.INTER_LINEAR)
    return np.clip(asset, 0.0, 1.0)


def _alpha_blend(base: np.ndarray, layer: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    a = np.clip(alpha, 0.0, 1.0)[..., None]
    return np.clip(base.astype(np.float32) * (1.0 - a) + layer.astype(np.float32) * a, 0, 255).astype(np.uint8)


def _shift_hue(frame: np.ndarray, degrees: float) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0].astype(np.int16)
    hsv[..., 0] = ((h + int(round(degrees / 2.0))) % 180).astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def subject_isolate(frame: np.ndarray, mask: np.ndarray, amount: float, background_blur: float = 0.0) -> np.ndarray:
    amount = float(np.clip(amount, 0.0, 1.0))
    if amount <= 0.0:
        return frame
    background = frame
    if background_blur > 0.0:
        sigma = max(0.1, background_blur * 24.0)
        background = cv2.GaussianBlur(frame, (0, 0), sigma)
    else:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        background = cv2.addWeighted(frame, 1.0 - 0.72 * amount, gray, 0.72 * amount, 0)
    alpha = cv2.GaussianBlur(mask, (0, 0), 2.2)
    return _alpha_blend(background, frame, alpha * amount)


def subject_echo(
    frame: np.ndarray,
    mask: np.ndarray,
    amount: float,
    *,
    copies: int = 4,
    spacing: float = 0.055,
    scale_step: float = 0.035,
    hue_step: float = 22.0,
) -> np.ndarray:
    amount = float(np.clip(amount, 0.0, 1.0))
    h, w = frame.shape[:2]
    result = frame.copy()
    subject = frame.copy()
    center = (w * 0.5, h * 0.5)
    for copy_index in range(max(1, copies), 0, -1):
        phase = copy_index / max(1, copies)
        scale = 1.0 + scale_step * copy_index * amount
        offset = spacing * copy_index * amount
        dx = int(round(w * offset * np.cos(copy_index * 2.1)))
        dy = int(round(h * offset * np.sin(copy_index * 1.7)))
        matrix = cv2.getRotationMatrix2D(center, 0.0, scale)
        matrix[:, 2] += (dx, dy)
        warped_subject = cv2.warpAffine(subject, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT101)
        warped_mask = cv2.warpAffine(mask, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        warped_subject = _shift_hue(warped_subject, hue_step * copy_index * amount)
        alpha = warped_mask * amount * (0.30 * (1.0 - 0.55 * phase))
        result = _alpha_blend(result, warped_subject, alpha)
    return result


def depth_parallax(frame: np.ndarray, depth: np.ndarray, amount: float, max_shift_px: float = 44.0) -> np.ndarray:
    amount = float(np.clip(amount, 0.0, 1.0))
    if amount <= 0.0:
        return frame
    h, w = frame.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    centered = np.clip(depth - 0.5, -0.5, 0.5)
    shift = centered * float(max_shift_px) * amount
    phase = amount * np.pi * 2.0
    map_x = xx - shift * np.cos(phase * 0.35)
    map_y = yy - shift * 0.42 * np.sin(phase * 0.5 + 0.8)
    return cv2.remap(frame, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT101)


def mask_transition(frame_a: np.ndarray, frame_b: np.ndarray, mask: np.ndarray, progress: float, softness: float = 0.08) -> np.ndarray:
    progress = float(np.clip(progress, 0.0, 1.0))
    softness = max(1e-3, float(softness))
    blurred = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), max(0.8, softness * 18.0))
    threshold = 1.12 - progress * 1.24
    alpha = np.clip((blurred - threshold + softness) / (2.0 * softness), 0.0, 1.0)
    global_alpha = np.clip((progress - 0.65) / 0.35, 0.0, 1.0)
    alpha = np.maximum(alpha, global_alpha)
    return _alpha_blend(frame_a, frame_b, alpha)


def apply_effect(frame: np.ndarray, mask: np.ndarray, depth: np.ndarray, effect: SemanticEffect) -> np.ndarray:
    kind = effect.kind.replace("-", "_").lower()
    if kind == "subject_isolate":
        return subject_isolate(frame, mask, effect.amount, effect.background_blur)
    if kind == "subject_echo":
        return subject_echo(
            frame,
            mask,
            effect.amount,
            copies=effect.copies,
            spacing=effect.spacing,
            scale_step=effect.scale_step,
            hue_step=effect.hue_step,
        )
    if kind == "depth_parallax":
        return depth_parallax(frame, depth, effect.amount, effect.parallax_px)
    raise ValueError(f"unknown semantic effect: {effect.kind}")


def materialize_scene(
    library_root: str | Path,
    analysis: SceneSemanticAnalysis,
    output: str | Path,
    effects: Iterable[SemanticEffect],
    *,
    fps: float | None = None,
    codec: str = "mp4v",
) -> Path:
    masks, depths = _load_assets(library_root, analysis)
    cap = cv2.VideoCapture(analysis.source_file)
    if not cap.isOpened():
        raise RuntimeError(f"unable to open {analysis.source_file}")
    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_frame = max(0, int(round(analysis.start * source_fps)))
    end_frame = max(start_frame + 1, int(round(analysis.end * source_fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    target_fps = float(fps or source_fps)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*codec), target_fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"unable to create output video: {output}")
    effects = tuple(effects)
    frame_no = start_frame
    duration_frames = max(1, end_frame - start_frame)
    while frame_no < end_frame:
        ok, frame = cap.read()
        if not ok:
            break
        progress = (frame_no - start_frame) / max(1, duration_frames - 1)
        mask = _sample_asset(masks, progress, (width, height))
        depth = _sample_asset(depths, progress, (width, height))
        rendered = frame
        for effect in effects:
            rendered = apply_effect(rendered, mask, depth, effect)
        writer.write(rendered)
        frame_no += 1
    writer.release()
    cap.release()
    return output


def materialize_mask_transition(
    library_root: str | Path,
    analysis: SceneSemanticAnalysis,
    incoming_file: str | Path,
    output: str | Path,
    *,
    softness: float = 0.08,
    codec: str = "mp4v",
) -> Path:
    masks, _ = _load_assets(library_root, analysis)
    first = cv2.VideoCapture(analysis.source_file)
    second = cv2.VideoCapture(str(incoming_file))
    if not first.isOpened() or not second.isOpened():
        first.release(); second.release()
        raise RuntimeError("unable to open one or both transition inputs")
    fps = float(first.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(first.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(first.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_frame = max(0, int(round(analysis.start * fps)))
    end_frame = max(start_frame + 1, int(round(analysis.end * fps)))
    first.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*codec), fps, (width, height))
    if not writer.isOpened():
        first.release(); second.release()
        raise RuntimeError(f"unable to create output video: {output}")
    count = max(1, end_frame - start_frame)
    index = 0
    while index < count:
        ok_a, a = first.read()
        ok_b, b = second.read()
        if not ok_a or not ok_b:
            break
        if b.shape[:2] != (height, width):
            b = cv2.resize(b, (width, height), interpolation=cv2.INTER_CUBIC)
        progress = index / max(1, count - 1)
        mask = _sample_asset(masks, progress, (width, height))
        writer.write(mask_transition(a, b, mask, progress, softness))
        index += 1
    writer.release(); first.release(); second.release()
    return output
