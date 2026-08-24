# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    fps: float | None


class MediaToolError(RuntimeError):
    pass


def require_media_tools() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise MediaToolError(f"required executable(s) not found in PATH: {', '.join(missing)}")


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise MediaToolError(f"command failed ({completed.returncode}): {' '.join(command)}\n{message[-4000:]}")
    return completed


def probe(path: Path) -> MediaInfo:
    completed = run_checked(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,width,height,avg_frame_rate",
            "-of", "json",
            str(path),
        ]
    )
    data = json.loads(completed.stdout)
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fps = _parse_ratio(video.get("avg_frame_rate"))
    return MediaInfo(
        duration=duration,
        width=int(video["width"]) if video.get("width") else None,
        height=int(video["height"]) if video.get("height") else None,
        fps=fps,
    )


def _parse_ratio(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else None
    return float(value)


def normalize_video(
    source: Path,
    destination: Path,
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    crf: int = 20,
    preset: str = "medium",
    keep_audio: bool = False,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".tmp.mp4")
    filtergraph = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps},setsar=1"
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-map", "0:v:0",
        "-vf", filtergraph,
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if keep_audio:
        command += ["-map", "0:a?", "-c:a", "aac", "-b:a", "160k"]
    else:
        command += ["-an"]
    command.append(str(temp))
    try:
        run_checked(command)
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)


_SHOWINFO_TIME = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def detect_scene_boundaries(path: Path, *, threshold: float = 0.40, min_scene_seconds: float = 1.0) -> list[float]:
    if not 0.0 < threshold < 1.0:
        raise ValueError("scene threshold must be between 0 and 1")

    completed = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "info",
            "-i", str(path),
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-an", "-f", "null", "-",
        ],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise MediaToolError(completed.stderr[-4000:])

    times = [float(match.group(1)) for match in _SHOWINFO_TIME.finditer(completed.stderr)]
    boundaries = [0.0]
    for time_value in sorted(set(times)):
        if time_value - boundaries[-1] >= min_scene_seconds:
            boundaries.append(time_value)
    return boundaries


def make_thumbnail(
    source: Path,
    destination: Path,
    time_seconds: float,
    *,
    width: int = 480,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{max(0.0, time_seconds):.3f}",
            "-i", str(source),
            "-frames:v", "1",
            "-vf", f"scale={width}:-2",
            "-q:v", "3",
            str(destination),
        ]
    )
