# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote

from .models import DirectedTimeline, VideoTransform


class NativeRenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeRenderConfig:
    width: int = 1920
    height: int = 1080
    fps: float = 60.0
    crf: int = 18
    preset: str = "veryfast"
    video_codec: str = "libx264"
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_bitrate: str = "320k"
    binary: str | None = None
    build_dir: str | Path | None = None
    build_if_missing: bool = False
    keep_manifest: bool = False
    decoder_cache: int = 16
    threads: int = 0


def _encode_path(path: Path) -> str:
    return quote(str(path), safe="/-_.~")


def _transform_fields(transform: VideoTransform) -> list[str]:
    return [
        f"{transform.playback_rate:.9g}",
        "1" if transform.reverse else "0",
        "1" if transform.mirror else "0",
        f"{transform.brightness:.9g}",
        f"{transform.contrast:.9g}",
        f"{transform.saturation:.9g}",
        f"{transform.grayscale:.9g}",
        f"{transform.scanlines:.9g}",
        f"{transform.vignette:.9g}",
        f"{transform.pixelate:.9g}",
        f"{transform.rgb_split:.9g}",
        f"{transform.noise:.9g}",
        f"{transform.ripple:.9g}",
        f"{transform.vortex:.9g}",
        f"{transform.motion_trails:.9g}",
        f"{transform.frame_echo:.9g}",
        f"{transform.hue_degrees:.9g}",
    ]


def _resolve_media(
    library: Path,
    media_file: str,
    *,
    media_url: str | None = None,
    materialized: bool = False,
) -> Path:
    """Resolve a timeline media reference using tubeviz library conventions.

    Current timelines keep an explicit library-relative path (for example
    originals/foo.webm or normalized/foo.mp4) plus the browser mount URL. Older
    basename-only timelines remain supported. Native rendering has no HTTP mount,
    so it recreates those mappings explicitly.
    """
    raw = Path(media_file).expanduser()
    if raw.is_absolute():
        return raw.resolve()

    normalized = library / "normalized"
    originals = library / "originals"
    transforms = library / "transforms"
    codec_glitch = library / "codec-glitch"

    # Explicit relative paths from old/custom timelines remain supported.
    candidates: list[Path] = []
    parts = raw.parts
    if parts and parts[0] in {"normalized", "originals", "transforms", "codec-glitch"}:
        candidates.append(library / raw)

    # media_url is the authoritative browser mapping when present.
    if media_url:
        url_path = unquote(media_url.split("?", 1)[0].split("#", 1)[0])
        if url_path.startswith("/transforms/"):
            candidates.append(transforms / url_path.removeprefix("/transforms/"))
        elif url_path.startswith("/codec-glitch/"):
            candidates.append(codec_glitch / url_path.removeprefix("/codec-glitch/"))
        elif url_path.startswith("/media/"):
            candidates.append(normalized / url_path.removeprefix("/media/"))
        elif url_path.startswith("/originals/"):
            candidates.append(originals / url_path.removeprefix("/originals/"))

    # Current timeline convention.
    if materialized:
        candidates.extend([transforms / raw, normalized / raw, originals / raw])
    else:
        candidates.extend([normalized / raw, originals / raw, transforms / raw])

    # Last-resort legacy root-relative path.
    candidates.append(library / raw)

    seen: set[Path] = set()
    resolved_candidates: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        resolved_candidates.append(resolved)
        if resolved.is_file():
            return resolved

    # Return the conventionally expected path so callers can give a useful
    # error while also exposing all attempted locations when desired.
    return resolved_candidates[0] if resolved_candidates else (normalized / raw).resolve()


def _media_resolution_candidates(
    library: Path,
    media_file: str,
    *,
    media_url: str | None = None,
    materialized: bool = False,
) -> list[Path]:
    """Debug helper mirroring _resolve_media's lookup order."""
    raw = Path(media_file).expanduser()
    if raw.is_absolute():
        return [raw.resolve()]
    candidates: list[Path] = []
    if raw.parts and raw.parts[0] in {"normalized", "originals", "transforms", "codec-glitch"}:
        candidates.append(library / raw)
    if media_url:
        url_path = unquote(media_url.split("?", 1)[0].split("#", 1)[0])
        if url_path.startswith("/transforms/"):
            candidates.append(library / "transforms" / url_path.removeprefix("/transforms/"))
        elif url_path.startswith("/codec-glitch/"):
            candidates.append(library / "codec-glitch" / url_path.removeprefix("/codec-glitch/"))
        elif url_path.startswith("/media/"):
            candidates.append(library / "normalized" / url_path.removeprefix("/media/"))
        elif url_path.startswith("/originals/"):
            candidates.append(library / "originals" / url_path.removeprefix("/originals/"))
    if materialized:
        candidates.extend([library / "transforms" / raw, library / "normalized" / raw, library / "originals" / raw])
    else:
        candidates.extend([library / "normalized" / raw, library / "originals" / raw, library / "transforms" / raw])
    candidates.append(library / raw)
    result: list[Path] = []
    seen: set[Path] = set()
    for item in candidates:
        resolved = item.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _cue_fields(cue) -> tuple[float, str, float, float, float, float] | None:
    supported = {
        "beat_warp",
        "video_edit_beat_warp",
        "video_edit_ripple",
        "video_edit_chroma_delay",
        "video_edit_vortex",
        "energy_bloom",
        "harmonic_warp",
    }
    if cue.action not in supported:
        return None
    p = cue.parameters
    return (
        float(cue.time),
        cue.action,
        float(p.get("amount", 0.0)),
        float(p.get("low", 0.0)),
        float(p.get("mid", 0.0)),
        float(p.get("high", 0.0)),
    )


def _curve_sample(points: list[tuple[float, float]], progress: float, fallback: float) -> float:
    if not points:
        return float(fallback)
    pts = sorted((float(x), float(y)) for x, y in points)
    if progress <= pts[0][0]:
        return pts[0][1]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        if progress <= bx:
            q = (progress - ax) / max(1e-9, bx - ax)
            return ay + (by - ay) * q
    return pts[-1][1]


def _native_vector_effects(scene):
    effects = list(scene.direction.vector_effects)
    if not effects:
        return []
    family = scene.direction.effect_family or "cinematic"
    priority = {
        "dream": ["vector_echo", "contours", "portal", "semantic_outline"],
        "liquid": ["flow_ribbons", "vector_echo", "portal", "flow_particles"],
        "analog": ["perspective_grid", "contours", "semantic_outline"],
        "fracture": ["delaunay_fracture", "voronoi", "portal"],
        "hyper": ["flow_ribbons", "delaunay_fracture", "flow_particles", "perspective_grid"],
        "prismatic": ["portal", "voronoi", "flow_ribbons"],
        "cinematic": ["semantic_outline", "contours", "perspective_grid", "portal"],
    }.get(family, ["contours"])
    hidden = [effect for effect in effects if not effect.visible]
    visible = [effect for effect in effects if effect.visible]
    order = {kind: index for index, kind in enumerate(priority)}
    visible.sort(key=lambda effect: order.get(effect.kind, 99))
    budget = 2 if scene.direction.narrative_role == "payoff" else 1
    return visible[:budget] + hidden


def _vector_fields(effect) -> list[str]:
    amount_curve = effect.automation.get("amount", [])
    samples = [
        _curve_sample(amount_curve, p, effect.amount)
        for p in (0.0, 1/3, 2/3, 1.0)
    ]
    explode = max(
        (float(y) for _, y in effect.automation.get("explode", [])),
        default=0.0,
    )
    radius = max(
        (float(y) for _, y in effect.automation.get("radius", [])),
        default=0.0,
    )
    params = effect.parameters or {}
    return [
        "VEC",
        effect.kind,
        f"{effect.amount:.9g}",
        f"{effect.opacity:.9g}",
        str(int(effect.seed)),
        str(int(effect.count)),
        f"{effect.line_width:.9g}",
        "1" if effect.visible else "0",
        "1" if effect.displace else "0",
        f"{float(params.get('motion_x', 0.0)):.9g}",
        f"{float(params.get('motion_y', 0.0)):.9g}",
        *(f"{value:.9g}" for value in samples),
        f"{explode:.9g}",
        f"{radius:.9g}",
    ]


def _hex_rgb(value: str | None) -> tuple[int, int, int]:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return (128, 160, 220)
    try:
        return tuple(int(raw[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (128, 160, 220)


def _creative_curve_channel(c, key: str, fallback: float) -> tuple[float, list[float]]:
    points = c.automation.get(key, [])
    samples = [_curve_sample(points, p, fallback) for p in (0.0, 1/3, 2/3, 1.0)]
    peak = max([float(fallback), *samples, 1e-6])
    return peak, [max(0.0, min(1.0, value / peak)) for value in samples]


def _creative_fields(scene) -> list[str]:
    c = scene.direction.creative
    # Browser automation is absolute per-channel intensity.  Native receives each
    # channel's peak plus a normalized four-sample envelope so it can reproduce
    # different AI/director trajectories instead of applying one generic curve to
    # every effect.  Fields 33..36 retain the abstraction envelope as a compact
    # backwards-compatible common envelope; the channel-specific arrays follow it.
    channel_names = (
        "flow_warp", "flow_trails", "flow_rgb",
        "temporal_echo", "temporal_rgb", "temporal_smear",
        "camera_energy", "depth_parallax", "background_warp",
        "feedback", "local_symmetry", "texture_bloom",
        "texture_streaks", "palette_strength", "abstraction",
    )
    channels = {
        name: _creative_curve_channel(c, name, float(getattr(c, name)))
        for name in channel_names
    }
    palette = scene.direction.color.palette
    pr, pg, pb = _hex_rgb(palette[0] if palette else None)
    palette_peak = channels["palette_strength"][0] if palette else 0.0
    fields = [
        "CREATIVE",
        f"{channels['flow_warp'][0]:.9g}",
        f"{channels['flow_trails'][0]:.9g}",
        f"{channels['flow_rgb'][0]:.9g}",
        f"{channels['temporal_echo'][0]:.9g}",
        f"{channels['temporal_rgb'][0]:.9g}",
        f"{channels['temporal_smear'][0]:.9g}",
        f"{channels['camera_energy'][0]:.9g}",
        f"{c.camera_target_x:.9g}",
        f"{c.camera_target_y:.9g}",
        f"{c.camera_drift_x:.9g}",
        f"{c.camera_drift_y:.9g}",
        f"{channels['depth_parallax'][0]:.9g}",
        f"{c.depth_fog:.9g}",
        f"{c.subject_preserve:.9g}",
        f"{c.semantic.subject_radius:.9g}",
        f"{channels['background_warp'][0]:.9g}",
        f"{channels['feedback'][0]:.9g}",
        f"{c.feedback_scale:.9g}",
        f"{c.feedback_rotation:.9g}",
        f"{channels['local_symmetry'][0]:.9g}",
        str(int(c.symmetry_segments)),
        f"{channels['texture_bloom'][0]:.9g}",
        f"{channels['texture_streaks'][0]:.9g}",
        f"{palette_peak:.9g}",
        str(pr), str(pg), str(pb),
        c.hero_kind or "-",
        f"{c.hero_amount:.9g}",
        f"{c.hero_start:.9g}",
        f"{c.hero_end:.9g}",
        f"{channels['abstraction'][0]:.9g}",
        *(f"{value:.9g}" for value in channels["abstraction"][1]),
    ]
    for name in channel_names[:-1]:
        fields.extend(f"{value:.9g}" for value in channels[name][1])
    # v0.33.5 appends renderer-level source fidelity and the one authoritative
    # post-composite color grade.  Older native manifests remain valid because
    # these fields are strictly appended after the v0.33 curve payload.
    color = scene.direction.color
    fields.extend([
        f"{c.source_fidelity:.9g}",
        f"{color.hue_shift_degrees:.9g}",
        f"{color.saturation_scale:.9g}",
        f"{color.contrast_scale:.9g}",
        f"{color.brightness_scale:.9g}",
    ])
    return fields


def write_native_manifest(
    timeline: DirectedTimeline,
    library: str | Path,
    destination: str | Path,
) -> Path:
    library_path = Path(library).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# tubeviz native render manifest v1",
        f"META\t{timeline.track.duration:.9f}",
    ]

    plan = sorted(timeline.scene_plan, key=lambda item: item.time)
    for index, scene in enumerate(plan):
        timeline_end = (
            plan[index + 1].time
            if index + 1 < len(plan)
            else timeline.track.duration
        )
        primary_path = _resolve_media(
            library_path,
            scene.media_file,
            media_url=scene.media_url,
            materialized=scene.transform.materialized,
        )
        if not primary_path.is_file():
            attempted = _media_resolution_candidates(
                library_path,
                scene.media_file,
                media_url=scene.media_url,
                materialized=scene.transform.materialized,
            )
            raise NativeRenderError(
                "native render media missing for "
                f"{scene.source_id}: {scene.media_file}; tried: "
                + ", ".join(str(path) for path in attempted)
            )
        fields = [
            "SHOT",
            f"{scene.time:.9f}",
            f"{timeline_end:.9f}",
            f"{scene.crossfade_seconds:.9f}",
            _encode_path(primary_path),
            f"{scene.start:.9f}",
            f"{scene.end:.9f}",
            f"{scene.opacity:.9f}",
            *_transform_fields(scene.transform),
        ]
        lines.append("\t".join(fields))

        for layer in scene.layers:
            layer_path = _resolve_media(
                library_path,
                layer.media_file,
                media_url=layer.media_url,
                materialized=layer.transform.materialized,
            )
            if not layer_path.is_file():
                attempted = _media_resolution_candidates(
                    library_path,
                    layer.media_file,
                    media_url=layer.media_url,
                    materialized=layer.transform.materialized,
                )
                raise NativeRenderError(
                    "native render layer media missing for "
                    f"{layer.source_id}: {layer.media_file}; tried: "
                    + ", ".join(str(path) for path in attempted)
                )
            fields = [
                "LAYER",
                _encode_path(layer_path),
                f"{layer.start:.9f}",
                f"{layer.end:.9f}",
                f"{layer.opacity:.9f}",
                layer.blend_mode,
                *_transform_fields(layer.transform),
            ]
            lines.append("\t".join(fields))

        lines.append("\t".join(_creative_fields(scene)))

        for effect in _native_vector_effects(scene):
            lines.append("\t".join(_vector_fields(effect)))

    for cue in timeline.cues:
        fields = _cue_fields(cue)
        if fields is None:
            continue
        t, action, amount, low, mid, high = fields
        lines.append(
            "\t".join(
                [
                    "CUE",
                    f"{t:.9f}",
                    action,
                    f"{amount:.9f}",
                    f"{low:.9f}",
                    f"{mid:.9f}",
                    f"{high:.9f}",
                ]
            )
        )

    destination.write_text("\n".join(lines) + "\n")
    return destination


def native_source_dir() -> Path:
    """Return the single canonical native-renderer source tree.

    Native C++ sources live under ``tubeviz/native_src`` so the editable
    checkout and installed wheel use exactly the same files. Keeping one
    source tree prevents the former top-level ``native/`` copy from drifting
    away from the packaged renderer.
    """
    source = Path(__file__).resolve().parent / "native_src"
    if source.exists():
        return source
    raise NativeRenderError(
        "native renderer sources are not available in this installation; "
        "reinstall tubeviz from a complete source distribution"
    )


def default_native_build_dir() -> Path:
    return Path.home() / ".cache" / "tubeviz" / "native-build"


def build_native_renderer(
    *,
    build_dir: str | Path | None = None,
    clean: bool = False,
    jobs: int | None = None,
    progress: Callable[[str], None] = print,
) -> Path:
    if shutil.which("cmake") is None:
        raise NativeRenderError("cmake was not found in PATH")
    source = native_source_dir()
    build = Path(build_dir or default_native_build_dir()).expanduser().resolve()
    if clean and build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True, exist_ok=True)

    configure = [
        "cmake",
        "-S",
        str(source),
        "-B",
        str(build),
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    progress("Native configure: " + " ".join(configure))
    rc = subprocess.run(configure).returncode
    if rc != 0:
        raise NativeRenderError(
            "native CMake configure failed. Install FFmpeg development packages "
            "(libavformat/libavcodec/libavutil/libswscale), pkg-config, CMake, and a C++20 compiler."
        )

    command = ["cmake", "--build", str(build), "--config", "Release"]
    if jobs:
        command += ["-j", str(jobs)]
    progress("Native build: " + " ".join(command))
    rc = subprocess.run(command).returncode
    if rc != 0:
        raise NativeRenderError("native C++ build failed")

    candidates = [
        build / "tubeviz-native-render",
        build / "Release" / "tubeviz-native-render",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise NativeRenderError(f"native build completed but renderer binary was not found under {build}")


def find_native_renderer(
    explicit: str | Path | None = None,
    *,
    build_dir: str | Path | None = None,
) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_binary = os.environ.get("TUBEVIZ_NATIVE_RENDERER")
    if env_binary:
        candidates.append(Path(env_binary).expanduser())
    which = shutil.which("tubeviz-native-render")
    if which:
        candidates.append(Path(which))
    build = Path(build_dir or default_native_build_dir()).expanduser()
    candidates += [
        build / "tubeviz-native-render",
        build / "Release" / "tubeviz-native-render",
    ]
    source_build = Path(__file__).resolve().parents[2] / "build" / "native"
    candidates += [source_build / "tubeviz-native-render"]

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def native_doctor(
    *,
    binary: str | Path | None = None,
    build_dir: str | Path | None = None,
) -> dict[str, object]:
    renderer = find_native_renderer(binary, build_dir=build_dir)
    pkg_config = shutil.which("pkg-config")
    library_names = ["libavformat", "libavcodec", "libavutil", "libswscale", "libplacebo"]
    libraries: dict[str, str | None] = {name: None for name in library_names}
    if pkg_config:
        for library in library_names:
            result = subprocess.run(
                [pkg_config, "--modversion", library],
                text=True,
                capture_output=True,
            )
            libraries[library] = result.stdout.strip() if result.returncode == 0 else None
    return {
        "renderer": str(renderer) if renderer else None,
        "cmake": shutil.which("cmake"),
        "cxx": shutil.which("c++") or shutil.which("g++") or shutil.which("clang++"),
        "pkg_config": pkg_config,
        "libraries": libraries,
        "build_dir": str(Path(build_dir or default_native_build_dir()).expanduser()),
        "source_dir": str(native_source_dir()),
    }


def _raw_ffmpeg_command(
    *,
    output: Path,
    audio: Path | None,
    duration: float,
    config: NativeRenderConfig,
) -> list[str]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{config.width}x{config.height}",
        "-framerate",
        f"{config.fps:g}",
        "-i",
        "pipe:0",
    ]
    if audio is not None:
        command += ["-i", str(audio)]
    command += ["-map", "0:v:0"]
    if audio is not None:
        command += ["-map", "1:a:0"]
    command += ["-c:v", config.video_codec]
    if config.video_codec.endswith("_nvenc"):
        preset_map = {
            "ultrafast": "p1",
            "superfast": "p2",
            "veryfast": "p3",
            "faster": "p4",
            "fast": "p4",
            "medium": "p5",
            "slow": "p6",
            "slower": "p7",
            "veryslow": "p7",
        }
        command += [
            "-preset",
            preset_map.get(config.preset, config.preset),
            "-rc",
            "vbr",
            "-cq",
            str(config.crf),
            "-b:v",
            "0",
        ]
    else:
        command += [
            "-preset",
            config.preset,
            "-crf",
            str(config.crf),
        ]
    command += [
        "-pix_fmt",
        config.pixel_format,
        "-fps_mode",
        "cfr",
    ]
    if audio is not None:
        command += ["-c:a", config.audio_codec, "-b:a", config.audio_bitrate, "-shortest"]
    command += ["-t", f"{duration:.6f}", "-metadata", "comment=Rendered by tubeviz native"]
    if output.suffix.lower() in {".mp4", ".m4v", ".mov"}:
        command += ["-movflags", "+faststart"]
    command.append(str(output))
    return command


def render_timeline_native(
    timeline_path: str | Path,
    *,
    library_path: str | Path,
    output_path: str | Path,
    audio_path: str | Path | None = None,
    config: NativeRenderConfig | None = None,
    progress: Callable[[str], None] = print,
) -> Path:
    cfg = config or NativeRenderConfig()
    if shutil.which("ffmpeg") is None:
        raise NativeRenderError("ffmpeg was not found in PATH")

    timeline_path = Path(timeline_path).expanduser().resolve()
    library_path = Path(library_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timeline = DirectedTimeline.model_validate_json(timeline_path.read_text())
    if not timeline.scene_plan:
        raise NativeRenderError("timeline contains no scene plan")

    if audio_path:
        audio = Path(audio_path).expanduser().resolve()
        if not audio.exists():
            raise NativeRenderError(f"audio file not found: {audio}")
    else:
        source = Path(timeline.track.source).expanduser()
        audio = source.resolve() if source.exists() else None

    binary = find_native_renderer(cfg.binary, build_dir=cfg.build_dir)
    if binary is None and cfg.build_if_missing:
        binary = build_native_renderer(build_dir=cfg.build_dir, progress=progress)
    if binary is None:
        raise NativeRenderError(
            "tubeviz-native-render was not found. Run `tubeviz native build`, "
            "set TUBEVIZ_NATIVE_RENDERER, or pass --native-binary."
        )

    tmp_context = tempfile.TemporaryDirectory(prefix="tubeviz-native-")
    tmp_dir = Path(tmp_context.name)
    manifest = tmp_dir / "render.manifest.tsv"
    write_native_manifest(timeline, library_path, manifest)
    if cfg.keep_manifest:
        kept = output_path.with_suffix(output_path.suffix + ".native-manifest.tsv")
        shutil.copy2(manifest, kept)
        progress(f"Native manifest: {kept}")

    native_command = [
        str(binary),
        "--manifest",
        str(manifest),
        "--width",
        str(cfg.width),
        "--height",
        str(cfg.height),
        "--fps",
        f"{cfg.fps:g}",
        "--decoder-cache",
        str(max(4, cfg.decoder_cache)),
        "--threads",
        str(max(0, cfg.threads)),
    ]
    encoder_command = _raw_ffmpeg_command(
        output=output_path,
        audio=audio,
        duration=timeline.track.duration,
        config=cfg,
    )

    progress(
        f"Native render: {cfg.width}x{cfg.height} {cfg.fps:g}fps "
        f"{timeline.track.duration:.2f}s, shots={len(timeline.scene_plan)}"
    )
    progress(
        f"Native renderer: {binary} "
        f"(decoder-cache={cfg.decoder_cache}, threads={'auto' if cfg.threads == 0 else cfg.threads})"
    )
    progress(
        f"Native encoder: {cfg.video_codec} preset={cfg.preset} crf={cfg.crf}"
    )

    native = subprocess.Popen(
        native_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert native.stdout is not None and native.stderr is not None
    encoder = subprocess.Popen(
        encoder_command,
        stdin=native.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    native.stdout.close()

    native_errors: list[str] = []
    started = time.monotonic()

    def read_native_stderr() -> None:
        for raw in iter(native.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            if line.startswith("PROGRESS\t"):
                parts = line.split("\t")
                if len(parts) >= 3:
                    done, total = int(parts[1]), int(parts[2])
                    elapsed = max(1e-6, time.monotonic() - started)
                    rate = done / elapsed
                    eta = (total - done) / rate if rate > 0 else 0.0
                    progress(
                        f"  native frame {done}/{total} "
                        f"({done / total * 100:5.1f}%) {rate:.1f} fps ETA {eta:.0f}s"
                    )
            else:
                native_errors.append(line)
                progress("  native: " + line)

    thread = threading.Thread(target=read_native_stderr, daemon=True)
    thread.start()

    encoder_stderr = b""
    try:
        encoder_stderr = encoder.communicate()[1] or b""
        native_rc = native.wait()
        thread.join(timeout=2)
        if native_rc != 0:
            raise NativeRenderError(
                f"native renderer exited with status {native_rc}: "
                + "; ".join(native_errors[-8:])
            )
        if encoder.returncode != 0:
            raise NativeRenderError(
                f"ffmpeg encoder exited with status {encoder.returncode}: "
                + encoder_stderr.decode("utf-8", errors="replace")
            )
    finally:
        if native.poll() is None:
            native.terminate()
        if encoder.poll() is None:
            encoder.terminate()
        tmp_context.cleanup()

    elapsed = time.monotonic() - started
    progress(f"Native render complete: {output_path} in {elapsed:.1f}s")
    return output_path
