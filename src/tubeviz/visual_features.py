# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np


@dataclass(frozen=True)
class VisualFeatureConfig:
    width: int = 160
    height: int = 90
    fps: float = 6.0
    max_frames: int = 180
    accent_quantile: float = 0.78


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.asarray(rgb, dtype=np.float32) / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    mx = np.max(x, axis=-1)
    mn = np.min(x, axis=-1)
    delta = mx - mn
    h = np.zeros_like(mx)
    mask = delta > 1e-6
    rc = np.divide(g - b, delta, out=np.zeros_like(delta), where=mask)
    gc = np.divide(b - r, delta, out=np.zeros_like(delta), where=mask)
    bc = np.divide(r - g, delta, out=np.zeros_like(delta), where=mask)
    h = np.where((mx == r) & mask, np.mod(rc, 6.0), h)
    h = np.where((mx == g) & mask, gc + 2.0, h)
    h = np.where((mx == b) & mask, bc + 4.0, h)
    h = np.mod(h / 6.0, 1.0)
    s = np.divide(delta, mx, out=np.zeros_like(delta), where=mx > 1e-6)
    return h, s, mx


def _circular_hue(h: np.ndarray, weight: np.ndarray) -> float:
    angle = h * (2.0 * np.pi)
    w = np.asarray(weight, dtype=np.float64)
    x = float(np.sum(np.cos(angle) * w))
    y = float(np.sum(np.sin(angle) * w))
    if abs(x) + abs(y) < 1e-9:
        return 0.0
    return float((math.degrees(math.atan2(y, x)) + 360.0) % 360.0)


def _palette(rgb: np.ndarray, count: int = 5) -> list[str]:
    # Quantized RGB palette: deterministic, cheap, and dependency-free.
    pixels = rgb.reshape(-1, 3).astype(np.uint8)
    if len(pixels) > 30000:
        step = max(1, len(pixels) // 30000)
        pixels = pixels[::step]
    bins = (pixels // 32).astype(np.int16)
    keys = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
    unique, counts = np.unique(keys, return_counts=True)
    order = np.argsort(counts)[::-1][:count]
    out: list[str] = []
    for idx in order:
        key = int(unique[idx])
        r = ((key // 64) % 8) * 32 + 16
        g = ((key // 8) % 8) * 32 + 16
        b = (key % 8) * 32 + 16
        out.append(f"#{r:02x}{g:02x}{b:02x}")
    return out


def _entropy(gray: np.ndarray) -> float:
    hist, _ = np.histogram(gray, bins=32, range=(0, 255))
    p = hist.astype(np.float64)
    p /= max(1.0, p.sum())
    p = p[p > 0]
    return float(np.clip(-(p * np.log2(p)).sum() / 5.0, 0.0, 1.0))


def _extract_frames(
    media: Path,
    *,
    start: float,
    end: float,
    cfg: VisualFeatureConfig,
) -> np.ndarray:
    duration = max(0.05, end - start)
    fps = min(cfg.fps, max(1.0, cfg.max_frames / duration))
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.6f}",
        "-t", f"{duration:.6f}",
        "-i", str(media),
        "-vf", f"fps={fps:.6f},scale={cfg.width}:{cfg.height}:flags=fast_bilinear",
        "-frames:v", str(cfg.max_frames),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip() or "ffmpeg frame extraction failed")
    frame_bytes = cfg.width * cfg.height * 3
    n = len(proc.stdout) // frame_bytes
    if n <= 0:
        raise RuntimeError("ffmpeg returned no visual-analysis frames")
    data = np.frombuffer(proc.stdout[: n * frame_bytes], dtype=np.uint8)
    return data.reshape(n, cfg.height, cfg.width, 3).copy()


def analyze_scene_visuals(
    media: str | Path,
    *,
    start: float,
    end: float,
    config: VisualFeatureConfig | None = None,
) -> dict:
    cfg = config or VisualFeatureConfig()
    path = Path(media).expanduser().resolve()
    frames = _extract_frames(path, start=start, end=end, cfg=cfg)
    f = frames.astype(np.float32)
    gray = 0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]

    brightness_curve = gray.mean(axis=(1, 2)) / 255.0
    h, sat, val = _rgb_to_hsv(frames)
    saturation_curve = sat.mean(axis=(1, 2))

    gx = np.abs(np.diff(gray, axis=2)).mean(axis=(1, 2)) / 255.0
    gy = np.abs(np.diff(gray, axis=1)).mean(axis=(1, 2)) / 255.0
    complexity_curve = np.clip((gx + gy) * 2.5, 0.0, 1.0)

    if len(frames) > 1:
        diff = np.abs(np.diff(gray, axis=0)) / 255.0
        motion = diff.mean(axis=(1, 2))
        motion = np.concatenate([[motion[0]], motion])
    else:
        motion = np.zeros(1, dtype=np.float32)

    # Approximate camera/global motion using luminance center-of-mass drift.
    yy, xx = np.mgrid[0:cfg.height, 0:cfg.width]
    weights = gray + 3.0
    sums = weights.sum(axis=(1, 2))
    cx = (weights * xx).sum(axis=(1, 2)) / sums
    cy = (weights * yy).sum(axis=(1, 2)) / sums
    dx = np.diff(cx, prepend=cx[0]) / max(1.0, cfg.width)
    dy = np.diff(cy, prepend=cy[0]) / max(1.0, cfg.height)

    motion_norm = motion / max(1e-6, float(np.quantile(motion, 0.95)) if len(motion) else 1.0)
    motion_norm = np.clip(motion_norm, 0.0, 1.0)
    threshold = float(np.quantile(motion_norm, cfg.accent_quantile)) if len(motion_norm) else 1.0
    accents: list[dict] = []
    duration = max(0.05, end - start)
    frame_dt = duration / max(1, len(frames))
    for i in range(1, max(1, len(motion_norm) - 1)):
        left = motion_norm[i - 1] if i else 0.0
        right = motion_norm[i + 1] if i + 1 < len(motion_norm) else 0.0
        if motion_norm[i] >= threshold and motion_norm[i] >= left and motion_norm[i] >= right:
            accents.append({
                "time": float(min(duration, i * frame_dt)),
                "strength": float(motion_norm[i]),
            })

    # Cut/flash rate: very strong inter-frame changes.
    high_cut = float(np.quantile(motion_norm, 0.92)) if len(motion_norm) else 1.0
    cut_count = int(np.count_nonzero(motion_norm >= high_cut)) if high_cut > 0 else 0

    # Palette/hue over all sampled frames.
    hh, ss, _ = _rgb_to_hsv(frames)
    hue = _circular_hue(hh, np.maximum(ss, 0.04))
    warmth = float(np.clip(((f[..., 0].mean() - f[..., 2].mean()) / 255.0 + 1.0) * 0.5, 0.0, 1.0))

    # Motion entropy: how uneven/unpredictable motion strength is.
    if len(motion_norm) > 2:
        hist, _ = np.histogram(motion_norm, bins=16, range=(0, 1))
        p = hist / max(1, hist.sum())
        p = p[p > 0]
        motion_entropy = float(np.clip(-(p * np.log2(p)).sum() / 4.0, 0.0, 1.0))
    else:
        motion_entropy = 0.0

    return {
        "version": 1,
        "sample_frames": int(len(frames)),
        "sample_fps": float(len(frames) / duration),
        "brightness": float(np.mean(brightness_curve)),
        "brightness_variance": float(np.var(brightness_curve)),
        "saturation": float(np.mean(saturation_curve)),
        "dominant_hue": hue,
        "warmth": warmth,
        "complexity": float(np.mean(complexity_curve)),
        "visual_entropy": _entropy(gray),
        "motion": float(np.mean(motion_norm)),
        "motion_peak": float(np.max(motion_norm)),
        "motion_entropy": motion_entropy,
        "motion_direction_x": float(np.clip(np.mean(dx) * 18.0, -1.0, 1.0)),
        "motion_direction_y": float(np.clip(np.mean(dy) * 18.0, -1.0, 1.0)),
        "cut_rate": float(cut_count / duration),
        "accents": accents[:32],
        "palette": _palette(frames, 5),
    }


def index_scene_visual_features(
    library,
    *,
    clip_id: int | None = None,
    force: bool = False,
    config: VisualFeatureConfig | None = None,
    progress: Callable[[str], None] = print,
) -> int:
    cfg = config or VisualFeatureConfig()
    scenes = library.scene_candidates(clip_id=clip_id, respect_trim=False)
    existing = library.scene_visual_feature_ids()
    indexed = 0
    for candidate in scenes:
        if candidate.scene_id in existing and not force:
            continue
        media = library.root / candidate.normalized_path
        if not media.is_file():
            continue
        try:
            features = analyze_scene_visuals(
                media,
                start=candidate.start_time,
                end=candidate.end_time,
                config=cfg,
            )
            library.store_scene_visual_features(candidate.scene_id, features)
            indexed += 1
            if indexed % 25 == 0:
                progress(f"  visual features: {indexed} scenes")
        except Exception as exc:
            progress(f"  visual feature warning scene={candidate.scene_id}: {exc}")
    if indexed:
        progress(f"Visual feature index complete: {indexed} scenes")
    return indexed
