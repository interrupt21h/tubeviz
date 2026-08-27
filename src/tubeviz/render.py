# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import math
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import uvicorn

from .models import DirectedTimeline
from .server import create_app


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderConfig:
    width: int = 1920
    height: int = 1080
    fps: float = 60.0
    crf: int = 18
    preset: str = "medium"
    video_codec: str = "libx264"
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_bitrate: str = "320k"
    frame_format: str = "png"
    jpeg_quality: int = 95
    browser_channel: str = "chrome"
    browser_executable: str | None = None
    headed: bool = False
    seed: int = 0x51F15E
    page_timeout_ms: int = 30_000
    seek_timeout_ms: int = 5_000
    browser_transport: str = "auto"  # auto | webcodecs | raw (frames accepted as legacy alias)
    browser_gpu: str = "auto"  # auto | webgpu | off
    browser_source_decode: str = "auto"  # auto | webcodecs | video
    webcodecs_bitrate: int = 0  # 0 derives a high-quality bitrate from size/fps/CRF

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("render width and height must be positive")
        if self.fps <= 0 or self.fps > 240:
            raise ValueError("render fps must be > 0 and <= 240")
        if not 0 <= self.crf <= 63:
            raise ValueError("crf must be between 0 and 63")
        if self.frame_format not in {"png", "jpeg"}:
            raise ValueError("frame_format must be png or jpeg")
        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be 1..100")
        if self.browser_transport not in {"auto", "webcodecs", "raw", "frames"}:
            raise ValueError("browser_transport must be auto, webcodecs, raw, or legacy frames")
        if self.browser_gpu not in {"auto", "webgpu", "off"}:
            raise ValueError("browser_gpu must be auto, webgpu, or off")
        if self.browser_source_decode not in {"auto", "webcodecs", "video"}:
            raise ValueError("browser_source_decode must be auto, webcodecs, or video")
        if self.webcodecs_bitrate < 0:
            raise ValueError("webcodecs_bitrate must be >= 0")


def build_ffmpeg_command(
    *,
    output: Path,
    audio: Path | None,
    duration: float,
    config: RenderConfig,
) -> list[str]:
    """Build the raw-RGBA browser fallback encode command.

    v0.38 removes the old compressed-image frame transport completely. When
    WebCodecs H.264 is unavailable, the page streams one tightly packed RGBA
    frame over the binary WebSocket and FFmpeg consumes it as rawvideo. This
    avoids browser image compression and an FFmpeg image decode for every frame.
    """
    config.validate()
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo",
        "-pixel_format", "rgba",
        "-video_size", f"{config.width}x{config.height}",
        "-framerate", f"{config.fps:g}",
        "-i", "pipe:0",
    ]
    if audio is not None:
        command += ["-i", str(audio)]

    command += ["-map", "0:v:0"]
    if audio is not None:
        command += ["-map", "1:a:0"]

    command += [
        "-c:v", config.video_codec,
        "-preset", config.preset,
        "-crf", str(config.crf),
        "-pix_fmt", config.pixel_format,
        "-fps_mode", "cfr",
    ]
    if audio is not None:
        command += ["-c:a", config.audio_codec, "-b:a", config.audio_bitrate, "-shortest"]
    command += ["-t", f"{duration:.6f}", "-metadata", "comment=Rendered by tubeviz (raw RGBA fallback)"]
    if output.suffix.lower() in {".mp4", ".m4v", ".mov"}:
        command += ["-movflags", "+faststart"]
    command.append(str(output))
    return command


def build_webcodecs_mux_command(
    *,
    output: Path,
    audio: Path | None,
    duration: float,
    config: RenderConfig,
) -> list[str]:
    """Mux an Annex-B H.264 stream produced by browser WebCodecs.

    The browser already performs video encoding, normally through the platform's
    hardware encoder. FFmpeg therefore only generates timestamps and muxes the
    elementary H.264 stream with the original audio.
    """
    config.validate()
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+genpts",
        "-r",
        f"{config.fps:g}",
        "-f",
        "h264",
        "-i",
        "pipe:0",
    ]
    if audio is not None:
        command += ["-i", str(audio)]
    command += ["-map", "0:v:0"]
    if audio is not None:
        command += ["-map", "1:a:0"]
    command += ["-c:v", "copy"]
    if audio is not None:
        command += ["-c:a", config.audio_codec, "-b:a", config.audio_bitrate, "-shortest"]
    command += [
        "-t",
        f"{duration:.6f}",
        "-metadata",
        "comment=Rendered by tubeviz (WebCodecs)",
    ]
    if output.suffix.lower() in {".mp4", ".m4v", ".mov"}:
        command += ["-movflags", "+faststart"]
    command.append(str(output))
    return command


def _derived_webcodecs_bitrate(config: RenderConfig) -> int:
    if config.webcodecs_bitrate > 0:
        return int(config.webcodecs_bitrate)
    # CRF cannot be mapped exactly onto WebCodecs' VBR target. This deliberately
    # errs on the high-quality side because the encoded stream becomes the final
    # video stream rather than a temporary JPEG/PNG intermediate.
    quality = max(0.0, min(1.0, (36.0 - float(config.crf)) / 28.0))
    bits_per_pixel = 0.075 + 0.125 * quality
    bitrate = int(config.width * config.height * config.fps * bits_per_pixel)
    return max(2_000_000, min(80_000_000, bitrate))


class _OfflineFrameSink:
    """Thread-safe sink used by the render server's binary WebSocket endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._encoder: subprocess.Popen[bytes] | None = None
        self.frames = 0
        self.bytes = 0
        self.completed_payload: dict | None = None
        self.generation = 0

    def attach(self, encoder: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._encoder = encoder
            self.generation += 1
            self.frames = 0
            self.bytes = 0
            self.completed_payload = None

    def detach(self) -> None:
        with self._lock:
            self._encoder = None

    def consume(self, data: bytes, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self.generation:
                raise RenderError("stale offline render stream")
            encoder = self._encoder
            if encoder is None or encoder.stdin is None:
                raise RenderError("offline render stream is not attached to FFmpeg")
            if encoder.poll() is not None:
                stderr = (
                    encoder.stderr.read().decode("utf-8", errors="replace")
                    if encoder.stderr
                    else ""
                )
                raise RenderError(f"ffmpeg encoder terminated early: {stderr}")
            try:
                encoder.stdin.write(data)
            except BrokenPipeError as exc:
                stderr = (
                    encoder.stderr.read().decode("utf-8", errors="replace")
                    if encoder.stderr
                    else ""
                )
                raise RenderError(f"ffmpeg encoder terminated early: {stderr}") from exc
            self.frames += 1
            self.bytes += len(data)

    def complete(self, payload: dict, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self.generation:
                raise RenderError("stale offline render completion")
            self.completed_payload = dict(payload)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RenderError(f"timed out waiting for internal render server on port {port}")


def _start_server(
    timeline: Path,
    audio: Path | None,
    library: Path,
    *,
    offline_render_sink: _OfflineFrameSink | None = None,
) -> tuple[uvicorn.Server, threading.Thread, int]:
    port = _free_port()
    app = create_app(
        timeline,
        audio,
        library,
        offline_render_sink=offline_render_sink,
    )
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="tubeviz-render-server", daemon=True)
    thread.start()
    _wait_for_port(port)
    return server, thread, port


def _launch_browser(playwright, cfg: RenderConfig):
    chromium = playwright.chromium
    kwargs: dict = {"headless": not cfg.headed}
    # WebGPU is enabled in modern Chrome by default. Avoid forcing experimental
    # flags: they can switch software backends on some systems and make performance
    # less predictable. The page feature-detects navigator.gpu instead.
    if cfg.browser_executable:
        kwargs["executable_path"] = cfg.browser_executable
        try:
            return chromium.launch(**kwargs)
        except Exception as exc:
            raise RenderError(
                f"failed to launch browser executable {cfg.browser_executable!r}: {exc}"
            ) from exc

    channel = cfg.browser_channel.strip().lower()
    if channel:
        kwargs["channel"] = channel
    try:
        return chromium.launch(**kwargs)
    except Exception as exc:
        if channel == "chrome":
            hint = (
                "Install Google Chrome, select another installed branded channel, "
                "or run `playwright install chromium` and pass "
                "`--browser-channel chromium`."
            )
        else:
            hint = (
                "Ensure the requested Playwright browser is installed. For Chromium, "
                "run `playwright install chromium`; for H.264 tubeviz media, an "
                "installed Chrome channel is recommended."
            )
        raise RenderError(
            f"failed to launch Playwright browser channel {channel!r}: {exc}. {hint}"
        ) from exc


def _stop_encoder(encoder: subprocess.Popen[bytes] | None) -> None:
    if encoder is None or encoder.poll() is not None:
        return
    try:
        if encoder.stdin:
            encoder.stdin.close()
    except Exception:
        pass
    encoder.terminate()
    try:
        encoder.wait(timeout=3)
    except subprocess.TimeoutExpired:
        encoder.kill()
        encoder.wait()


def _finish_encoder(encoder: subprocess.Popen[bytes]) -> str:
    if encoder.stdin is not None and not encoder.stdin.closed:
        encoder.stdin.close()
    stderr = (
        encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
    )
    rc = encoder.wait()
    if rc != 0:
        raise RenderError(f"ffmpeg exited with status {rc}: {stderr}")
    return stderr


def _choose_transport(cfg: RenderConfig, capabilities: dict) -> str:
    h264_requested = cfg.video_codec.lower() in {"libx264", "h264", "h264_nvenc", "avc", "avc1"}
    webcodecs = bool(capabilities.get("webcodecs_h264")) and h264_requested
    if cfg.browser_transport == "webcodecs":
        if not h264_requested:
            raise RenderError("browser WebCodecs transport currently emits H.264; choose libx264/h264_nvenc or use --browser-transport raw")
        if not webcodecs:
            reason = capabilities.get("webcodecs_error") or "H.264 VideoEncoder unsupported"
            raise RenderError(f"browser WebCodecs transport requested but unavailable: {reason}")
        return "webcodecs"
    if cfg.browser_transport in {"raw", "frames"}:
        return "raw"
    return "webcodecs" if webcodecs else "raw"


def render_timeline(
    timeline_path: str | Path,
    *,
    library_path: str | Path,
    output_path: str | Path,
    audio_path: str | Path | None = None,
    config: RenderConfig | None = None,
    progress: Callable[[str], None] = print,
) -> Path:
    cfg = config or RenderConfig()
    cfg.validate()

    if shutil.which("ffmpeg") is None:
        raise RenderError("ffmpeg was not found in PATH")

    timeline_path = Path(timeline_path).expanduser().resolve()
    library_path = Path(library_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timeline = DirectedTimeline.model_validate_json(timeline_path.read_text())
    if not timeline.scene_plan:
        raise RenderError(
            "timeline contains no scene plan; run `tubeviz analyze --library ...` first"
        )

    if audio_path is None:
        source = Path(timeline.track.source).expanduser()
        audio = source.resolve() if source.exists() else None
    else:
        audio = Path(audio_path).expanduser().resolve()
        if not audio.exists():
            raise RenderError(f"audio file not found: {audio}")

    duration = float(timeline.track.duration)
    total_frames = max(1, math.ceil(duration * cfg.fps))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderError(
            "offline rendering requires Playwright. Install with "
            "`pip install -e '.[render]'` and then run `playwright install chromium`."
        ) from exc

    server = None
    server_thread = None
    browser = None
    encoder: subprocess.Popen[bytes] | None = None
    sink = _OfflineFrameSink()
    started = time.monotonic()

    try:
        server, server_thread, port = _start_server(
            timeline_path,
            audio,
            library_path,
            offline_render_sink=sink,
        )
        progress(
            f"Render: {cfg.width}x{cfg.height} {cfg.fps:g}fps "
            f"{duration:.2f}s ({total_frames} frames)"
        )

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright, cfg)
            context = browser.new_context(
                viewport={"width": cfg.width, "height": cfg.height},
                device_scale_factor=1,
            )
            page = context.new_page()
            page.set_default_timeout(cfg.page_timeout_ms)
            page.goto(
                f"http://127.0.0.1:{port}/?offline=1&gpu={cfg.browser_gpu}",
                wait_until="domcontentloaded",
            )
            page.wait_for_function("() => typeof window.tubevizOfflineInit === 'function'")
            info = page.evaluate(
                "(options) => window.tubevizOfflineInit(options)",
                {"fps": cfg.fps, "seed": cfg.seed, "sourceDecode": cfg.browser_source_decode},
            )
            progress(
                f"Browser renderer ready: scenes={info.get('scenes', 0)} "
                f"duration={info.get('duration', duration):.2f}s "
                f"gpu={info.get('gpu', 'canvas2d')}" + (f"/{info.get('gpu_reason')}" if info.get('gpu_reason') else "") + f" source_decode={info.get('source_decode', 'video')}"
            )

            bitrate = _derived_webcodecs_bitrate(cfg)
            capabilities = page.evaluate(
                "(options) => window.tubevizOfflineCapabilities(options)",
                {
                    "width": cfg.width,
                    "height": cfg.height,
                    "fps": cfg.fps,
                    "bitrate": bitrate,
                },
            )
            if info.get("source_decode") == "webcodecs":
                progress(
                    "Browser source decode: WebCodecs H.264 "
                    f"({capabilities.get('webcodecs_decode_codec') or 'Annex-B'}, worker-preferred)"
                    + (f" fallbacks={info.get('source_fallbacks', 0)}" if info.get('source_fallbacks') else "")
                )
            else:
                reason = capabilities.get("webcodecs_decode_error") or info.get("source_decode_reason") or "requested fallback"
                progress(f"Browser source decode: HTMLVideoElement ({reason})")
            transport = _choose_transport(cfg, capabilities)
            progress(
                "Browser transport: "
                + (
                    f"WebCodecs H.264 ({capabilities.get('webcodecs_codec')}, "
                    f"{bitrate / 1_000_000:.1f} Mbps, hardware preferred)"
                    if transport == "webcodecs"
                    else "raw RGBA binary frame stream"
                )
            )

            ffmpeg_command = (
                build_webcodecs_mux_command(
                    output=output_path, audio=audio, duration=duration, config=cfg
                )
                if transport == "webcodecs"
                else build_ffmpeg_command(
                    output=output_path, audio=audio, duration=duration, config=cfg
                )
            )
            encoder = subprocess.Popen(
                ffmpeg_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            sink.attach(encoder)

            last_report = {"done": 0, "browser_ms": 0.0, "export_ms": 0.0}

            def report_browser(payload: dict) -> None:
                done = int(payload.get("done", 0))
                if done <= last_report["done"] and done != total_frames:
                    return
                last_report.update(payload)
                elapsed = time.monotonic() - started
                rate = done / elapsed if elapsed > 0 and done else 0.0
                remaining = (total_frames - done) / rate if rate > 0 else 0.0
                browser_fps = float(payload.get("browser_fps", 0.0))
                queued = int(payload.get("queued", 0))
                progress(
                    f"  frame {done}/{total_frames} "
                    f"({done / total_frames * 100:5.1f}%) "
                    f"{rate:.2f} fps-total / {browser_fps:.2f} fps-browser "
                    f"ETA {remaining:.0f}s queued={queued}"
                )

            page.expose_function("tubevizReportOfflineProgress", report_browser)

            render_options = {
                "fps": cfg.fps,
                "totalFrames": total_frames,
                "transport": transport,
                "bitrate": bitrate,
                "width": cfg.width,
                "height": cfg.height,
                "reportEvery": max(1, int(round(cfg.fps * 0.5))),
                "maxBufferedBytes": 24 * 1024 * 1024,
                "seed": cfg.seed,
            }

            try:
                result = page.evaluate(
                    "(options) => window.tubevizRenderOfflineSequence(options)",
                    render_options,
                )
            except Exception as exc:
                # Auto mode gets one robust fallback if a browser advertises an
                # H.264 encoder but fails to initialize/use it at runtime.
                if transport == "webcodecs" and cfg.browser_transport == "auto":
                    progress(f"WebCodecs render failed ({exc}); retrying with raw RGBA streaming")
                    _stop_encoder(encoder)
                    sink.detach()
                    output_path.unlink(missing_ok=True)
                    encoder = subprocess.Popen(
                        build_ffmpeg_command(
                            output=output_path,
                            audio=audio,
                            duration=duration,
                            config=cfg,
                        ),
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    sink.attach(encoder)
                    page.evaluate(
                        "(options) => window.tubevizOfflineInit(options)",
                        {"fps": cfg.fps, "seed": cfg.seed, "sourceDecode": cfg.browser_source_decode},
                    )
                    render_options["transport"] = "raw"
                    result = page.evaluate(
                        "(options) => window.tubevizRenderOfflineSequence(options)",
                        render_options,
                    )
                    transport = "raw"
                else:
                    raise RenderError(f"browser render failed: {exc}") from exc

            # The completion acknowledgement is emitted only after the server has
            # consumed all preceding binary WebSocket messages in order.
            _finish_encoder(encoder)
            sink.detach()
            encoder = None

            progress(
                f"Browser sequence complete: transport={transport} "
                f"gpu={result.get('gpu', 'canvas2d')} source_decode={result.get('source_decode', info.get('source_decode', 'video'))} "
                f"browser={result.get('browser_fps', 0):.2f} fps "
                f"streamed={sink.bytes / (1024 * 1024):.1f} MiB"
            )

            context.close()
            browser.close()
            browser = None

        elapsed = time.monotonic() - started
        progress(f"Wrote {output_path} in {elapsed:.1f}s")
        return output_path

    finally:
        _stop_encoder(encoder)
        sink.detach()
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=3)
