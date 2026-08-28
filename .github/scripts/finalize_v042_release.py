#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1))


def prepend_once(path: str, marker: str, content: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if marker in text:
        return
    target.write_text(content.rstrip() + "\n\n" + text.lstrip())


# Package/native release version.
replace_once("pyproject.toml", 'version = "0.41.0"', 'version = "0.42.0"')
replace_once("src/tubeviz/__init__.py", '__version__ = "0.41.0"', '__version__ = "0.42.0"')
replace_once(
    "src/tubeviz/native_src/src/main.cpp",
    'tubeviz-native-render 0.41.0',
    'tubeviz-native-render 0.42.0',
)

# Native encoder resolution + performance telemetry presentation.
replace_once(
    "src/tubeviz/native_render.py",
    "from dataclasses import dataclass\n",
    "from dataclasses import dataclass, replace\n",
)
replace_once(
    "src/tubeviz/native_render.py",
    '    video_codec: str = "libx264"\n',
    '    video_codec: str = "auto"\n',
)
replace_once(
    "src/tubeviz/native_render.py",
    "\ndef _raw_ffmpeg_command(\n",
    r'''
def _ffmpeg_encoder_usable(encoder: str, *, timeout: float = 8.0) -> bool:
    """Return True only when FFmpeg can actually initialize the encoder.

    Listing an encoder is not sufficient on NVIDIA/WSL systems: FFmpeg may be
    compiled with NVENC while the runtime driver/device is unavailable.  Encode
    one tiny raw frame so auto-selection reflects the machine that will render.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    frame = bytes(64 * 64 * 3)
    command = [
        ffmpeg,
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", "64x64", "-framerate", "1", "-i", "pipe:0",
        "-frames:v", "1", "-an", "-c:v", encoder,
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            command,
            input=frame,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=max(1.0, timeout),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _resolve_native_video_codec(requested: str | None) -> str:
    codec = (requested or "auto").strip()
    if codec != "auto":
        return codec
    return "h264_nvenc" if _ffmpeg_encoder_usable("h264_nvenc") else "libx264"


def _raw_ffmpeg_command(
''',
)
replace_once(
    "src/tubeviz/native_render.py",
    '    command += ["-c:v", config.video_codec]\n    if config.video_codec.endswith("_nvenc"):\n',
    '    video_codec = "libx264" if config.video_codec == "auto" else config.video_codec\n'
    '    command += ["-c:v", video_codec]\n'
    '    if video_codec.endswith("_nvenc"):\n',
)
replace_once(
    "src/tubeviz/native_render.py",
    '    encoder_command = _raw_ffmpeg_command(\n        output=output_path,\n        audio=audio,\n        duration=timeline.track.duration,\n        config=cfg,\n    )\n',
    '    encoder_codec = _resolve_native_video_codec(cfg.video_codec)\n'
    '    encoder_config = replace(cfg, video_codec=encoder_codec)\n'
    '    encoder_command = _raw_ffmpeg_command(\n'
    '        output=output_path,\n'
    '        audio=audio,\n'
    '        duration=timeline.track.duration,\n'
    '        config=encoder_config,\n'
    '    )\n',
)
replace_once(
    "src/tubeviz/native_render.py",
    '        f"Native encoder: {cfg.video_codec} preset={cfg.preset} crf={cfg.crf}"\n',
    '        f"Native encoder: {encoder_codec} preset={cfg.preset} crf={cfg.crf}"\n'
    '        + (" (auto-selected)" if cfg.video_codec == "auto" else "")\n',
)
replace_once(
    "src/tubeviz/native_render.py",
    '    native_errors: list[str] = []\n    started = time.monotonic()\n',
    '    native_errors: list[str] = []\n'
    '    native_perf: dict[str, str] = {}\n'
    '    started = time.monotonic()\n',
)
replace_once(
    "src/tubeviz/native_render.py",
    '                    progress(\n'
    '                        f"  native frame {done}/{total} "\n'
    '                        f"({done / total * 100:5.1f}%) {rate:.1f} fps ETA {eta:.0f}s"\n'
    '                    )\n'
    '            else:\n'
    '                native_errors.append(line)\n'
    '                progress("  native: " + line)\n',
    '                    progress(\n'
    '                        f"  native frame {done}/{total} "\n'
    '                        f"({done / total * 100:5.1f}%) {rate:.1f} fps ETA {eta:.0f}s"\n'
    '                    )\n'
    '            elif line.startswith("PERF\\t"):\n'
    '                metrics: dict[str, str] = {}\n'
    '                for field in line.split("\\t")[1:]:\n'
    '                    if "=" in field:\n'
    '                        key, value = field.split("=", 1)\n'
    '                        metrics[key] = value\n'
    '                native_perf.update(metrics)\n'
    '                ordered = ("resident", "fallback", "decode_ms", "map_ms", "compose_ms", "fx_ms", "download_ms", "cpu_ms", "pipe_ms")\n'
    '                summary = []\n'
    '                for key in ordered:\n'
    '                    if key not in metrics:\n'
    '                        continue\n'
    '                    label = key.removesuffix("_ms")\n'
    '                    suffix = "ms" if key.endswith("_ms") else ""\n'
    '                    summary.append(f"{label}={metrics[key]}{suffix}")\n'
    '                progress("  native perf: " + " ".join(summary))\n'
    '            else:\n'
    '                native_errors.append(line)\n'
    '                progress("  native: " + line)\n',
)
replace_once(
    "src/tubeviz/native_render.py",
    '    elapsed = time.monotonic() - started\n    progress(f"Native render complete: {output_path} in {elapsed:.1f}s")\n',
    '    elapsed = time.monotonic() - started\n'
    '    if native_perf:\n'
    '        progress(\n'
    '            "Native perf final: "\n'
    '            + " ".join(f"{key}={value}" for key, value in native_perf.items())\n'
    '        )\n'
    '    progress(f"Native render complete: {output_path} in {elapsed:.1f}s")\n',
)
replace_once(
    "src/tubeviz/native_render.py",
    '    return {\n        "renderer": str(renderer) if renderer else None,\n',
    '    nvenc_usable = _ffmpeg_encoder_usable("h264_nvenc") if ffmpeg else False\n'
    '    return {\n'
    '        "renderer": str(renderer) if renderer else None,\n',
)
replace_once(
    "src/tubeviz/native_render.py",
    '        "cuda_decode_advertised": "cuda" in hwaccels,\n        "vulkan_effects_buildable": libraries.get("libplacebo") is not None,\n',
    '        "cuda_decode_advertised": "cuda" in hwaccels,\n'
    '        "nvenc_encode_usable": nvenc_usable,\n'
    '        "default_video_encoder": "h264_nvenc" if nvenc_usable else "libx264",\n'
    '        "vulkan_effects_buildable": libraries.get("libplacebo") is not None,\n',
)

# Shared CLI codec is now an explicit override. Backend-specific defaults stay
# compatible: browser -> libx264, native -> auto probe.
replace_once(
    "src/tubeviz/cli.py",
    '    render.add_argument("--video-codec", default="libx264")\n',
    '    render.add_argument(\n'
    '        "--video-codec",\n'
    '        default=None,\n'
    '        help="Explicit encoder override; native defaults to auto/NVENC when usable, browser defaults to libx264",\n'
    '    )\n',
)
replace_once(
    "src/tubeviz/cli.py",
    '                    preset=args.native_preset,\n                    video_codec=args.video_codec,\n',
    '                    preset=args.native_preset,\n                    video_codec=args.video_codec or "auto",\n',
)
replace_once(
    "src/tubeviz/cli.py",
    '                    preset=args.preset,\n                    video_codec=args.video_codec,\n',
    '                    preset=args.preset,\n                    video_codec=args.video_codec or "libx264",\n',
)

# Replace stale implementation-shape tests with release-level behavior tests.
(ROOT / "tests/test_native_performance.py").write_text(r'''# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import tubeviz.native_render as native_render
from tubeviz.cli import build_parser
from tubeviz.native_render import NativeRenderConfig, _raw_ffmpeg_command, _resolve_native_video_codec


def test_native_defaults_use_fast_encoder_and_cache():
    cfg = NativeRenderConfig()
    assert cfg.preset == "veryfast"
    assert cfg.video_codec == "auto"
    assert cfg.decoder_cache == 16
    assert cfg.threads == 0
    assert cfg.gpu == "auto"
    assert cfg.hwdecode == "auto"


def test_native_render_cli_exposes_performance_controls():
    args = build_parser().parse_args([
        "render", "timeline.json",
        "--backend", "native",
        "--native-preset", "superfast",
        "--native-decoder-cache", "24",
        "--native-threads", "8",
        "--native-gpu", "vulkan",
        "--native-hwdecode", "cuda",
    ])
    assert args.video_codec is None
    assert args.native_preset == "superfast"
    assert args.native_decoder_cache == 24
    assert args.native_threads == 8
    assert args.native_gpu == "vulkan"
    assert args.native_hwdecode == "cuda"


def test_native_source_has_lazy_avframe_fast_path_and_lru():
    root = Path("src/tubeviz/native_src")
    decoder = (root / "src/decoder.cpp").read_text()
    renderer = (root / "src/renderer.cpp").read_text()
    cmake = (root / "CMakeLists.txt").read_text()
    effects = (root / "src/effects.cpp").read_text()

    assert "const AVFrame* Decoder::avframe_at" in decoder
    assert "return held_frame_;" in decoder
    assert "if (!rgb_valid_) convert_held_frame();" in decoder
    assert "SWS_FAST_BILINEAR" in decoder
    assert "decoder_cache_limit_" in renderer
    assert "warm_shot" in renderer
    assert "OpenMP" in cmake
    assert "#pragma omp parallel for" in effects


def test_native_ffmpeg_default_command_has_safe_unresolved_auto_fallback():
    command = _raw_ffmpeg_command(
        output=Path("/tmp/out.mp4"),
        audio=None,
        duration=1.0,
        config=NativeRenderConfig(),
    )
    joined = " ".join(command)
    assert "-c:v libx264" in joined
    assert "-preset veryfast" in joined


def test_native_auto_encoder_prefers_usable_nvenc(monkeypatch):
    monkeypatch.setattr(native_render, "_ffmpeg_encoder_usable", lambda encoder: encoder == "h264_nvenc")
    assert _resolve_native_video_codec("auto") == "h264_nvenc"
    assert _resolve_native_video_codec(None) == "h264_nvenc"
    assert _resolve_native_video_codec("libx264") == "libx264"


def test_native_auto_encoder_falls_back_to_x264(monkeypatch):
    monkeypatch.setattr(native_render, "_ffmpeg_encoder_usable", lambda encoder: False)
    assert _resolve_native_video_codec("auto") == "libx264"


def test_native_nvenc_uses_cq_instead_of_crf():
    command = _raw_ffmpeg_command(
        output=Path("/tmp/out.mp4"),
        audio=None,
        duration=1.0,
        config=NativeRenderConfig(video_codec="h264_nvenc", crf=20),
    )
    joined = " ".join(command)
    assert "-c:v h264_nvenc" in joined
    assert "-cq 20" in joined
    assert "-b:v 0" in joined
    assert "-crf" not in command


def test_native_source_contains_resident_vulkan_cuda_and_perf_paths():
    root = Path("src/tubeviz/native_src")
    decoder = (root / "src/decoder.cpp").read_text()
    renderer = (root / "src/renderer.cpp").read_text()
    gpu = (root / "src/gpu.cpp").read_text()
    resident = (root / "src/resident_gpu.cpp").read_text()
    cmake = (root / "CMakeLists.txt").read_text()
    native_py = Path("src/tubeviz/native_render.py").read_text()

    assert "avcodec_get_hw_config" in decoder
    assert "AV_HWDEVICE_TYPE_CUDA" in decoder
    assert "av_hwdevice_ctx_create" in decoder
    assert '"primary_ctx", "1"' in decoder
    assert "SharedCudaDevice" in decoder
    assert "av_buffer_ref(shared)" in decoder
    assert "AV_PIX_FMT_FLAG_HWACCEL" in decoder
    assert "av_hwframe_transfer_data" in decoder

    assert "ResidentGpuPipeline" in renderer
    assert "render_shot_resident" in renderer
    assert "resident_->last_hardware_map_failed()" in renderer
    assert "software decode + GPU YUV upload" in renderer
    assert 'PERF\\tframes=' in renderer

    assert "pl_map_avframe_ex" in resident
    assert "pl_unmap_avframe" in resident
    assert "pl_tex_download" in resident
    assert "history_mix" in resident
    assert "pl_tex_blit" in resident

    assert "GpuPostProcessor" in renderer
    assert "apply_creative_temporal_effects" in renderer
    assert "previous_output_.swap(output)" in renderer
    assert "pl_vulkan_create" in gpu
    assert "pl_vulkan_create(impl_->log, nullptr)" in gpu
    assert "pl_mpv_user_shader_parse" in gpu
    assert "pl_render_image" in gpu
    assert "params.dynamic_constants = false" in gpu
    assert "src/gpu.cpp" in cmake
    assert "src/resident_gpu.cpp" in cmake
    assert "src/libav_bridge.c" in cmake
    assert 'line.startswith("PERF\\t")' in native_py


def test_studio_render_forwards_native_acceleration_controls():
    js = Path("src/tubeviz/static/gui.js").read_text()
    html = Path("src/tubeviz/static/gui.html").read_text()
    gui = Path("src/tubeviz/gui.py").read_text()
    assert 'native_gpu:value("nativeGpu")' in js
    assert 'native_hwdecode:value("nativeHwdecode")' in js
    assert 'id="nativeGpu"' in html
    assert 'id="nativeHwdecode"' in html
    assert '"--native-gpu"' in gui
    assert '"--native-hwdecode"' in gui


def test_studio_render_forwards_browser_acceleration_controls():
    js = Path("src/tubeviz/static/gui.js").read_text()
    html = Path("src/tubeviz/static/gui.html").read_text()
    gui = Path("src/tubeviz/gui.py").read_text()
    assert 'browser_transport:value("browserTransport")' in js
    assert 'browser_gpu:value("browserGpu")' in js
    assert 'browser_source_decode:value("browserSourceDecode")' in js
    assert 'webcodecs_bitrate:number("webcodecsBitrate")' in js
    assert 'id="browserTransport"' in html
    assert 'id="browserGpu"' in html
    assert 'id="browserSourceDecode"' in html
    assert 'id="webcodecsBitrate"' in html
    assert '"--browser-transport"' in gui
    assert '"--browser-gpu"' in gui
    assert '"--browser-source-decode"' in gui
    assert '"--webcodecs-bitrate"' in gui
''')

prepend_once(
    "CHANGELOG.md",
    "# 0.42.0 — GPU-resident native rendering",
    r'''# 0.42.0 — GPU-resident native rendering

- Add a native GPU-resident rendering path that keeps decoded FFmpeg `AVFrame` data in YUV/hardware form through layer transforms, multi-source composition, creative/post effects, vector treatment and temporal history instead of converting every source frame to full-resolution RGB first.
- Map supported CUDA/NVDEC hardware frames directly into libplacebo/Vulkan with `pl_map_avframe_ex`. When CUDA-to-Vulkan mapping is unavailable in `auto` mode, reopen decoders in software mode and upload native YUV to Vulkan rather than paying a CUDA download followed by an RGB CPU conversion and Vulkan re-upload.
- Make RGB conversion lazy in the decoder. The validated CPU/hybrid renderer still uses the existing `sws_scale` path when needed, but the resident fast path consumes the retained `AVFrame` directly.
- Move layer geometry/color transforms, source composition, reactive/creative effects, post effects, vector approximations, crossfade/history blending and history texture preservation into the resident Vulkan path. Existing CPU/OpenMP and hybrid-libplacebo rendering remain automatic fallbacks.
- Add native stage telemetry for decode, AVFrame mapping, GPU composition, effects/history, final GPU download, CPU fallback work and encoder-pipe blocking. Studio/CLI progress now recognizes `PERF` records as structured performance data instead of treating them as renderer errors.
- Make native encoder selection `auto` by default. Tubeviz performs a real one-frame FFmpeg NVENC initialization probe, chooses `h264_nvenc` only when the runtime can actually encode, and otherwise falls back to `libx264`. Explicit `--video-codec` remains authoritative; browser rendering continues to default to `libx264`.
- Extend `native doctor` with NVENC usability and the encoder that native auto-selection would choose on the current machine.
- Compile the libplacebo FFmpeg bridge in its required C translation unit and validate both `TUBEVIZ_WITH_PLACEBO=ON` and `OFF` configurations in CI.
- Replace stale eager-RGB implementation assertions with regression coverage for lazy AVFrame decode, resident CUDA/Vulkan mapping, software-YUV retry, GPU history, performance telemetry and encoder selection.
''',
)

print("v0.42 release files finalized")
