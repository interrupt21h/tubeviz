# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import base64
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


def build_ffmpeg_command(
    *,
    output: Path,
    audio: Path | None,
    duration: float,
    config: RenderConfig,
) -> list[str]:
    config.validate()
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "image2pipe",
        "-framerate",
        f"{config.fps:g}",
        "-vcodec",
        "png" if config.frame_format == "png" else "mjpeg",
        "-i",
        "pipe:0",
    ]
    if audio is not None:
        command += ["-i", str(audio)]

    command += ["-map", "0:v:0"]
    if audio is not None:
        command += ["-map", "1:a:0"]

    command += [
        "-c:v",
        config.video_codec,
        "-preset",
        config.preset,
        "-crf",
        str(config.crf),
        "-pix_fmt",
        config.pixel_format,
        "-fps_mode",
        "cfr",
    ]

    if audio is not None:
        command += [
            "-c:a",
            config.audio_codec,
            "-b:a",
            config.audio_bitrate,
            "-shortest",
        ]

    command += [
        "-t",
        f"{duration:.6f}",
        "-metadata",
        "comment=Rendered by tubeviz",
    ]

    if output.suffix.lower() in {".mp4", ".m4v", ".mov"}:
        command += ["-movflags", "+faststart"]

    command.append(str(output))
    return command


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
) -> tuple[uvicorn.Server, threading.Thread, int]:
    port = _free_port()
    app = create_app(timeline, audio, library)
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
    encoder = None
    started = time.monotonic()

    try:
        server, server_thread, port = _start_server(timeline_path, audio, library_path)
        progress(
            f"Render: {cfg.width}x{cfg.height} {cfg.fps:g}fps "
            f"{duration:.2f}s ({total_frames} frames)"
        )

        ffmpeg_command = build_ffmpeg_command(
            output=output_path,
            audio=audio,
            duration=duration,
            config=cfg,
        )
        encoder = subprocess.Popen(
            ffmpeg_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert encoder.stdin is not None

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright, cfg)
            context = browser.new_context(
                viewport={"width": cfg.width, "height": cfg.height},
                device_scale_factor=1,
            )
            page = context.new_page()
            page.set_default_timeout(cfg.page_timeout_ms)
            page.goto(
                f"http://127.0.0.1:{port}/?offline=1",
                wait_until="domcontentloaded",
            )
            page.wait_for_function(
                "() => typeof window.tubevizOfflineInit === 'function'"
            )
            info = page.evaluate(
                "(options) => window.tubevizOfflineInit(options)",
                {"fps": cfg.fps, "seed": cfg.seed},
            )
            progress(
                f"Browser renderer ready: scenes={info.get('scenes', 0)} "
                f"duration={info.get('duration', duration):.2f}s"
            )

            # Export the final tubeviz canvases directly from the page instead of
            # taking a compositor-level browser screenshot. This avoids browser UI
            # capture and a large part of Playwright's screenshot pipeline.
            report_every = max(1, int(round(cfg.fps * 0.5)))
            browser_ms_total = 0.0
            export_ms_total = 0.0
            pipe_ms_total = 0.0

            frame_quality = cfg.jpeg_quality / 100.0

            for frame_index in range(total_frames):
                t = frame_index / cfg.fps
                browser_start = time.monotonic()
                result = page.evaluate(
                    "([t,i,fmt,q]) => window.tubevizRenderAndExport(t,i,fmt,q)",
                    [t, frame_index, cfg.frame_format, frame_quality],
                )
                browser_elapsed = (time.monotonic() - browser_start) * 1000.0
                browser_ms_total += browser_elapsed
                export_ms_total += float(result.get("export_ms", 0.0))
                frame_bytes = base64.b64decode(result["data"])

                pipe_start = time.monotonic()
                try:
                    encoder.stdin.write(frame_bytes)
                except BrokenPipeError as exc:
                    stderr = (
                        encoder.stderr.read().decode("utf-8", errors="replace")
                        if encoder.stderr
                        else ""
                    )
                    raise RenderError(f"ffmpeg encoder terminated early: {stderr}") from exc
                pipe_ms_total += (time.monotonic() - pipe_start) * 1000.0

                done = frame_index + 1
                if (
                    frame_index == 0
                    or done == total_frames
                    or done % report_every == 0
                ):
                    elapsed = time.monotonic() - started
                    rate = done / elapsed if elapsed > 0 else 0.0
                    remaining = (total_frames - done) / rate if rate > 0 else 0.0
                    avg_browser = browser_ms_total / done
                    avg_export = export_ms_total / done
                    avg_pipe = pipe_ms_total / done
                    progress(
                        f"  frame {done}/{total_frames} "
                        f"({done / total_frames * 100:5.1f}%) "
                        f"{rate:.2f} fps-render ETA {remaining:.0f}s "
                        f"[browser {avg_browser:.0f}ms, canvas-export {avg_export:.0f}ms, "
                        f"ffmpeg-pipe {avg_pipe:.0f}ms]"
                    )

            encoder.stdin.close()
            stderr = (
                encoder.stderr.read().decode("utf-8", errors="replace")
                if encoder.stderr
                else ""
            )
            rc = encoder.wait()
            if rc != 0:
                raise RenderError(f"ffmpeg exited with status {rc}: {stderr}")

            context.close()
            browser.close()
            browser = None

        elapsed = time.monotonic() - started
        progress(f"Wrote {output_path} in {elapsed:.1f}s")
        return output_path

    finally:
        if encoder is not None and encoder.poll() is None:
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
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=5)
