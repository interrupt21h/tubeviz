# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    codec_name: str | None = None
    pixel_format: str | None = None
    sample_aspect_ratio: str | None = None
    format_name: str | None = None


@dataclass(frozen=True)
class PreparedMedia:
    path: Path
    transcoded: bool
    encoder: str | None
    reason: str
    info: MediaInfo


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
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name,width,height,avg_frame_rate,pix_fmt,sample_aspect_ratio",
            "-of", "json",
            str(path),
        ]
    )
    data = json.loads(completed.stdout)
    format_data = data.get("format") or {}
    duration = float(format_data.get("duration") or 0.0)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fps = _parse_ratio(video.get("avg_frame_rate"))
    return MediaInfo(
        duration=duration,
        width=int(video["width"]) if video.get("width") else None,
        height=int(video["height"]) if video.get("height") else None,
        fps=fps,
        codec_name=str(video.get("codec_name")) if video.get("codec_name") else None,
        pixel_format=str(video.get("pix_fmt")) if video.get("pix_fmt") else None,
        sample_aspect_ratio=(
            str(video.get("sample_aspect_ratio"))
            if video.get("sample_aspect_ratio") else None
        ),
        format_name=(
            str(format_data.get("format_name"))
            if format_data.get("format_name") else None
        ),
    )


def _parse_ratio(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else None
    return float(value)


def _format_names(info: MediaInfo) -> set[str]:
    return {
        item.strip().lower()
        for item in (info.format_name or "").split(",")
        if item.strip()
    }


def is_browser_compatible(info: MediaInfo) -> tuple[bool, str]:
    """Return whether the source can safely be used directly by tubeviz.

    Native processing is FFmpeg-based and can consume far more formats than a
    browser.  Auto mode therefore only bypasses the compatibility proxy for
    codec/container combinations that modern Chromium playback handles
    reliably.  This keeps the browser preview usable without needlessly
    re-encoding ordinary YouTube H.264/VP9/AV1 media.
    """
    codec = (info.codec_name or "").lower()
    formats = _format_names(info)
    pixel = (info.pixel_format or "").lower()

    if not codec:
        return False, "video codec could not be identified"

    mp4_family = bool(formats & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
    webm_family = bool(formats & {"webm", "matroska"})

    if codec == "h264" and mp4_family:
        if pixel and pixel not in {"yuv420p", "yuvj420p", "nv12"}:
            return False, f"H.264 pixel format {pixel} needs a compatibility proxy"
        return True, "browser-compatible H.264/MP4 source"
    if codec in {"vp8", "vp9"} and webm_family:
        return True, f"browser-compatible {codec.upper()}/WebM source"
    if codec == "av1" and (mp4_family or webm_family):
        return True, "browser-compatible AV1 source"

    container = info.format_name or "unknown container"
    return False, f"{codec or 'unknown codec'} in {container} is not a direct-play compatibility target"


@lru_cache(maxsize=1)
def nvenc_usable() -> bool:
    """Check that this FFmpeg build can actually create an H.264 NVENC frame."""
    if shutil.which("ffmpeg") is None:
        return False
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:r=1:d=0.1",
        "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _parse_ffmpeg_time(value: str) -> float | None:
    try:
        hours, minutes, seconds = value.split(":", 2)
        return float(hours) * 3600.0 + float(minutes) * 60.0 + float(seconds)
    except (TypeError, ValueError):
        return None


def _run_ffmpeg_progress(
    command: list[str],
    *,
    duration: float,
    progress: Callable[[str], None] | None = None,
    label: str = "transcode",
) -> None:
    tail: deque[str] = deque(maxlen=120)
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    current_time = 0.0
    last_percent = -10.0
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        tail.append(line)
        if line.startswith("out_time="):
            parsed = _parse_ffmpeg_time(line.partition("=")[2])
            if parsed is not None:
                current_time = parsed
            continue
        if line != "progress=continue" and line != "progress=end":
            continue
        if progress is None:
            continue
        if duration > 0:
            percent = max(0.0, min(100.0, 100.0 * current_time / duration))
            if line == "progress=end":
                percent = 100.0
            if line == "progress=end" or percent - last_percent >= 2.0:
                progress(
                    f"  {label}: {current_time:.1f}s/{duration:.1f}s ({percent:.1f}%)"
                )
                last_percent = percent
        elif line == "progress=end":
            progress(f"  {label}: complete (100.0%)")

    returncode = process.wait()
    if returncode != 0:
        message = "\n".join(tail)
        raise MediaToolError(
            f"ffmpeg failed ({returncode}): {' '.join(command)}\n{message[-4000:]}"
        )


def _video_filters(
    info: MediaInfo,
    *,
    width: int,
    height: int,
    fps: int,
) -> list[str]:
    filters: list[str] = []
    width = max(0, int(width))
    height = max(0, int(height))
    fps = max(0, int(fps))

    if width and height:
        filters.extend([
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        ])
    elif width:
        filters.append(f"scale={width}:-2")
    elif height:
        filters.append(f"scale=-2:{height}")
    elif info.sample_aspect_ratio not in {None, "", "1:1", "1/1", "0:1"}:
        # Preserve display geometry while producing square pixels.
        filters.append("scale=trunc(iw*sar/2)*2:ih")

    if fps:
        filters.append(f"fps={fps}")
    if filters or info.sample_aspect_ratio not in {None, "", "1:1", "1/1", "0:1"}:
        filters.append("setsar=1")
    return filters


def normalize_video(
    source: Path,
    destination: Path,
    *,
    width: int = 0,
    height: int = 0,
    fps: int = 0,
    crf: int = 20,
    preset: str = "medium",
    keep_audio: bool = False,
    encoder: str = "auto",
    progress: Callable[[str], None] | None = None,
    source_info: MediaInfo | None = None,
) -> str:
    """Create an H.264/MP4 compatibility proxy and return the encoder used.

    width/height/fps default to zero, which preserves source geometry and frame
    rate.  ``encoder=auto`` prefers NVIDIA NVENC only when a live one-frame
    encode probe succeeds, and falls back to libx264 if an auto-selected NVENC
    transcode still fails at runtime.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".tmp.mp4")
    info = source_info or probe(source)
    filters = _video_filters(info, width=width, height=height, fps=fps)

    requested = str(encoder or "auto").strip().lower()
    if requested not in {"auto", "nvenc", "x264", "libx264", "h264_nvenc"}:
        raise ValueError("encoder must be one of: auto, nvenc, x264")

    if requested in {"nvenc", "h264_nvenc"}:
        if not nvenc_usable():
            raise MediaToolError("h264_nvenc was requested but no usable NVIDIA NVENC encoder was detected")
        encoders = ["h264_nvenc"]
    elif requested in {"x264", "libx264"}:
        encoders = ["libx264"]
    else:
        encoders = ["h264_nvenc", "libx264"] if nvenc_usable() else ["libx264"]

    last_error: Exception | None = None
    for index, selected_encoder in enumerate(encoders):
        temp.unlink(missing_ok=True)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source),
            "-map", "0:v:0",
        ]
        if filters:
            command += ["-vf", ",".join(filters)]
        if selected_encoder == "h264_nvenc":
            command += [
                "-c:v", "h264_nvenc",
                "-preset", "p4",
                "-cq", str(crf),
                "-b:v", "0",
            ]
        else:
            command += [
                "-c:v", "libx264",
                "-preset", preset,
                "-crf", str(crf),
            ]
        command += [
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]
        if keep_audio:
            command += ["-map", "0:a?", "-c:a", "aac", "-b:a", "160k"]
        else:
            command += ["-an"]
        command += [
            "-progress", "pipe:1",
            "-stats_period", "0.5",
            "-nostats",
            str(temp),
        ]
        try:
            if progress:
                progress(f"  transcode encoder: {selected_encoder}")
            _run_ffmpeg_progress(
                command,
                duration=info.duration,
                progress=progress,
                label="transcode",
            )
            temp.replace(destination)
            return selected_encoder
        except Exception as exc:
            last_error = exc
            temp.unlink(missing_ok=True)
            if requested == "auto" and selected_encoder == "h264_nvenc" and index + 1 < len(encoders):
                if progress:
                    progress(f"  transcode: NVENC failed; falling back to libx264: {exc}")
                continue
            raise
        finally:
            if destination.exists():
                temp.unlink(missing_ok=True)

    assert last_error is not None
    raise last_error


def prepare_media(
    source: Path,
    proxy_destination: Path,
    *,
    mode: str = "auto",
    width: int = 0,
    height: int = 0,
    fps: int = 0,
    crf: int = 20,
    preset: str = "medium",
    keep_audio: bool = False,
    encoder: str = "auto",
    progress: Callable[[str], None] | None = None,
    force: bool = False,
) -> PreparedMedia:
    """Choose direct source media or create a compatibility proxy.

    ``auto`` reuses browser-compatible source media directly. ``source`` always
    reuses the original and is useful for native-only workflows. ``normalize``
    forces a compatibility proxy for users who need the old homogeneous-media
    behavior.
    """
    selected_mode = str(mode or "auto").strip().lower()
    if selected_mode not in {"auto", "source", "normalize"}:
        raise ValueError("media preparation mode must be one of: auto, source, normalize")

    info = probe(source)
    compatible, reason = is_browser_compatible(info)
    if selected_mode == "source":
        return PreparedMedia(
            path=source,
            transcoded=False,
            encoder=None,
            reason="source mode requested; using downloaded media directly",
            info=info,
        )
    if selected_mode == "auto" and compatible:
        return PreparedMedia(
            path=source,
            transcoded=False,
            encoder=None,
            reason=reason,
            info=info,
        )

    transcode_reason = (
        "normalization explicitly requested"
        if selected_mode == "normalize"
        else reason
    )
    if proxy_destination.is_file() and not force:
        return PreparedMedia(
            path=proxy_destination,
            transcoded=False,
            encoder=None,
            reason=f"reusing cached compatibility proxy; {transcode_reason}",
            info=info,
        )
    used_encoder = normalize_video(
        source,
        proxy_destination,
        width=width,
        height=height,
        fps=fps,
        crf=crf,
        preset=preset,
        keep_audio=keep_audio,
        encoder=encoder,
        progress=progress,
        source_info=info,
    )
    return PreparedMedia(
        path=proxy_destination,
        transcoded=True,
        encoder=used_encoder,
        reason=transcode_reason,
        info=info,
    )


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
