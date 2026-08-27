# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__

from .library import ClipLibrary
from .media import prepare_preview_proxy
from .models import DirectedTimeline, SceneSelection
from .scene_selector import SceneSelectorConfig, attach_scene_plan
from .transforms import TransformConfig, attach_transform_plan
from .timeline import TimelineCursor


def _scene_state_at(timeline: DirectedTimeline, position: float) -> dict | None:
    current: SceneSelection | None = None
    for scene in timeline.scene_plan:
        if scene.time <= position:
            current = scene
        else:
            break
    if current is None:
        return None

    elapsed = max(0.0, position - current.time)
    rate = current.transform.playback_rate if not current.transform.materialized else 1.0
    source_span = max(0.001, current.end - current.start)
    offset = (elapsed * rate) % source_span
    payload = current.model_dump(mode="json")
    payload["resume_at"] = min(current.end, current.start + offset)
    return payload


def _state_at(timeline: DirectedTimeline, position: float) -> dict:
    world = None
    for snapshot in timeline.world_states:
        if snapshot.time <= position:
            world = snapshot
        else:
            break

    motifs: dict[str, dict] = {}
    visual_by_motif = {item.motif_id: item for item in timeline.visual_memory}
    for motif in timeline.motifs:
        occurred = [occ for occ in motif.occurrences if occ.start <= position]
        if not occurred:
            continue
        latest = occurred[-1]
        visual = visual_by_motif[motif.id]
        motifs[motif.id] = {
            "motif_id": motif.id,
            "visual_id": visual.id,
            "shape": visual.shape,
            "hue": visual.hue,
            "scale": visual.scale * (1.0 + 0.12 * (latest.ordinal - 1)),
            "occurrence": latest.ordinal,
            "mutation": latest.ordinal - 1,
            "similarity": latest.similarity,
        }

    return {
        "type": "state",
        "time": position,
        "world": world.model_dump(mode="json") if world else None,
        "motifs": motifs,
        "scene": _scene_state_at(timeline, position),
    }



def _resolve_timeline_media(library: ClipLibrary, media_file: str, media_url: str | None = None) -> Path:
    """Resolve a timeline media reference without exposing arbitrary filesystem paths."""
    raw = Path(media_file).expanduser()
    if raw.is_absolute():
        resolved = raw.resolve()
        try:
            resolved.relative_to(library.root.resolve())
        except ValueError as exc:
            raise FileNotFoundError(f"media path is outside library: {resolved}") from exc
        if resolved.is_file():
            return resolved
        raise FileNotFoundError(str(resolved))

    candidates: list[Path] = []
    if raw.parts and raw.parts[0] in {"normalized", "originals", "transforms", "codec-glitch"}:
        candidates.append(library.root / raw)
    if media_url:
        url_path = unquote(media_url.split("?", 1)[0].split("#", 1)[0])
        mounts = {
            "/media/": library.normalized_dir,
            "/originals/": library.originals_dir,
            "/transforms/": library.root / "transforms",
            "/codec-glitch/": library.root / "codec-glitch",
        }
        for prefix, base in mounts.items():
            if url_path.startswith(prefix):
                candidates.append(base / url_path.removeprefix(prefix))
                break
    candidates.extend([
        library.normalized_dir / raw,
        library.originals_dir / raw,
        library.root / "transforms" / raw,
        library.root / "codec-glitch" / raw,
        library.root / raw,
    ])
    root = library.root.resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    raise FileNotFoundError(media_file)


def _annexb_nals(data: bytes) -> list[bytes]:
    """Split Annex-B H.264 while retaining each NAL start code."""
    starts: list[int] = []
    i = 0
    n = len(data)
    while i + 3 < n:
        if data[i:i+4] == b"\x00\x00\x00\x01":
            starts.append(i); i += 4; continue
        if data[i:i+3] == b"\x00\x00\x01":
            starts.append(i); i += 3; continue
        i += 1
    if not starts:
        return []
    starts.append(n)
    return [data[starts[j]:starts[j+1]] for j in range(len(starts)-1) if starts[j+1] > starts[j]]


def _pack_sequence_h264(data: bytes, *, fps: float) -> tuple[bytes, int]:
    """Pack an Annex-B H.264 stream as a compact sequential WebCodecs transport.

    TVZ2 stores access units with an explicit key/delta flag. Unlike the older
    TVZ1 all-IDR cache, this permits a normal GOP so VideoDecoder can decode
    sequentially on the hardware path instead of paying an IDR-sized bitrate for
    every source frame. Key access units are made independently restartable by
    prepending the most recent SPS/PPS when FFmpeg did not repeat them in-band.
    """
    nals = _annexb_nals(data)
    if not nals:
        raise RuntimeError("FFmpeg produced no Annex-B NAL units")
    sps_pps: list[bytes] = []
    units: list[list[bytes]] = []
    current: list[bytes] = []
    for nal in nals:
        start = 4 if nal.startswith(b"\x00\x00\x00\x01") else 3
        if len(nal) <= start:
            continue
        nal_type = nal[start] & 0x1F
        if nal_type in (7, 8):
            if nal_type == 7:
                sps_pps = [n for n in sps_pps if ((n[4 if n.startswith(b"\x00\x00\x00\x01") else 3] & 0x1F) != 7)]
            else:
                sps_pps = [n for n in sps_pps if ((n[4 if n.startswith(b"\x00\x00\x00\x01") else 3] & 0x1F) != 8)]
            sps_pps.append(nal)
        if nal_type == 9 and current:
            units.append(current)
            current = [nal]
        else:
            current.append(nal)
    if current:
        units.append(current)

    packed_units: list[tuple[bool, bytes]] = []
    for unit in units:
        types: set[int] = set()
        for nal in unit:
            start = 4 if nal.startswith(b"\x00\x00\x00\x01") else 3
            if len(nal) > start:
                types.add(nal[start] & 0x1F)
        # Keep only access units containing a coded picture. Type 5 is IDR;
        # types 1-4 are non-IDR coded slices.
        if not any(t in types for t in (1, 2, 3, 4, 5)):
            continue
        key = 5 in types
        prefix = b""
        if key and not (7 in types and 8 in types):
            prefix = b"".join(sps_pps)
        packed_units.append((key, prefix + b"".join(unit)))

    if not packed_units:
        raise RuntimeError("FFmpeg produced no decodable H.264 access units")
    if not packed_units[0][0]:
        raise RuntimeError("FFmpeg source transport did not begin with a key frame")

    header = b"TVZ2" + struct.pack("<If", len(packed_units), float(fps))
    out = bytearray(header)
    for key, unit in packed_units:
        out += struct.pack("<BI", 1 if key else 0, len(unit))
        out += unit
    return bytes(out), len(packed_units)


def _pack_keyframe_h264(data: bytes, *, fps: float) -> tuple[bytes, int]:
    """Backward-compatible helper retained for callers/tests; emits TVZ2."""
    return _pack_sequence_h264(data, fps=fps)


def _make_browser_source_cache(
    source: Path, *, start: float, end: float, fps: float, cache_dir: Path,
    return_path: bool = False,
) -> tuple[bytes | Path, str]:
    """Create/reuse a sequential H.264 transport for browser WebCodecs.

    WebCodecs deliberately does not provide container demuxing. tubeviz therefore
    uses FFmpeg once per unique scene range to create an Annex-B transport with a
    normal two-second GOP and no B-frames. The browser keeps one VideoDecoder per
    active layer and advances it sequentially; backwards/random access resets only
    to the nearest preceding IDR. This is dramatically smaller and more decoder-
    friendly than the former all-IDR-per-frame cache.
    """
    stat = source.stat()
    gop = max(1, min(240, int(round(float(fps) * 2.0))))
    key = json.dumps({
        "path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "start": round(float(start), 6), "end": round(float(end), 6), "fps": round(float(fps), 6),
        "gop": gop, "format": 2,
    }, sort_keys=True).encode()
    digest = hashlib.sha256(key).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{digest}.tvzh264"
    if cached.is_file():
        return (cached if return_path else cached.read_bytes()), "cache"

    span = max(0.05, float(end) - float(start))
    base = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{max(0.0, float(start)):.6f}", "-i", str(source),
        "-t", f"{span:.6f}", "-an", "-vf", f"fps={float(fps):.8g}",
    ]
    tail = [
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.2",
        "-g", str(gop), "-bf", "0", "-bsf:v", "h264_metadata=aud=insert",
        "-f", "h264", "pipe:1",
    ]
    commands = [
        [*base, "-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-rc", "constqp", "-qp", "18", *tail],
        [*base, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
         "-x264-params", f"keyint={gop}:min-keyint={gop}:scenecut=0:repeat-headers=1:bframes=0", *tail],
    ]
    last_error = ""
    for idx, command in enumerate(commands):
        try:
            proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=max(30.0, span * 8.0))
            packed, _ = _pack_sequence_h264(proc.stdout, fps=fps)
            with tempfile.NamedTemporaryFile(dir=cache_dir, prefix=f".{digest}.", suffix=".tmp", delete=False) as tmp:
                tmp.write(packed); tmp.flush()
                tmp_path = Path(tmp.name)
            tmp_path.replace(cached)
            return (cached if return_path else packed), "nvenc" if idx == 0 else "x264"
        except Exception as exc:
            last_error = str(exc)
            continue
    raise RuntimeError(f"unable to build browser WebCodecs source cache: {last_error}")

def create_app(
    timeline_path: str | Path,
    audio_path: str | Path | None = None,
    library_path: str | Path | None = None,
    *,
    replan_scenes: bool = False,
    scene_config: SceneSelectorConfig | None = None,
    replan_transforms: bool = False,
    offline_render_sink: Any | None = None,
) -> FastAPI:
    timeline_path = Path(timeline_path).expanduser().resolve()
    timeline = DirectedTimeline.model_validate_json(timeline_path.read_text())

    library: ClipLibrary | None = None
    if library_path is not None:
        library = ClipLibrary(library_path)
        library.initialize()
        if replan_scenes or not timeline.scene_plan:
            timeline = attach_scene_plan(timeline, library, scene_config)
        elif replan_transforms:
            cfg = scene_config or SceneSelectorConfig()
            timeline = attach_transform_plan(
                timeline, TransformConfig(enabled=cfg.transforms, intensity=cfg.transform_intensity)
            )

    package_dir = Path(__file__).resolve().parent
    static_dir = package_dir / "static"

    app = FastAPI(title="tubeviz", version=__version__)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    if library is not None:
        # StaticFiles resolves requests beneath each dedicated media directory
        # and rejects path traversal. The library root/database are never exposed.
        app.mount(
            "/media",
            StaticFiles(directory=library.normalized_dir, check_dir=True),
            name="media",
        )
        # Auto media preparation can keep browser-compatible downloads as the
        # canonical ready media. Expose only the originals directory, not the
        # whole library root, so timeline playback remains narrowly scoped.
        app.mount(
            "/originals",
            StaticFiles(directory=library.originals_dir, check_dir=True),
            name="originals",
        )
        transforms_dir = library.root / "transforms"
        transforms_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/transforms",
            StaticFiles(directory=transforms_dir, check_dir=True),
            name="transforms",
        )
        codec_dir = library.root / "codec-glitch"
        codec_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/codec-glitch",
            StaticFiles(directory=codec_dir, check_dir=True),
            name="codec-glitch",
        )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/timeline")
    async def get_timeline() -> dict:
        return timeline.model_dump(mode="json")

    @app.get("/api/status")
    async def get_status() -> dict:
        primary_clip_ids = {scene.clip_id for scene in timeline.scene_plan}
        all_clip_ids = set(primary_clip_ids)
        for scene in timeline.scene_plan:
            all_clip_ids.update(layer.clip_id for layer in scene.layers)
        return {
            "clips_enabled": library is not None,
            "scene_count": len(timeline.scene_plan),
            "planned_shots": len(timeline.scene_plan),
            "unique_primary_clips": len(primary_clip_ids),
            "unique_clips_with_companions": len(all_clip_ids),
            "video_layers": sum(1 + len(scene.layers) for scene in timeline.scene_plan),
            "transformed_scenes": sum(1 for scene in timeline.scene_plan if scene.transform.materialized),
            "library": str(library.root) if library is not None else None,
            "timeline": str(timeline_path),
            "audio": str(Path(audio_path).expanduser().resolve()) if audio_path is not None else None,
            "preview_proxy_height": 720 if library is not None else None,
            "preview_proxy_fps": 30 if library is not None else None,
            "browser_source_decode": library is not None,
        }

    if audio_path is not None:
        resolved_audio = Path(audio_path).expanduser().resolve()

        @app.get("/audio")
        async def audio() -> FileResponse:
            return FileResponse(resolved_audio)

    if library is not None:
        def _timeline_layer(scene_index: int, layer_index: int):
            if scene_index < 0 or scene_index >= len(timeline.scene_plan):
                raise HTTPException(status_code=404, detail="scene index out of range")
            scene = timeline.scene_plan[scene_index]
            layers = [scene, *scene.layers]
            if layer_index < 0 or layer_index >= len(layers):
                raise HTTPException(status_code=404, detail="layer index out of range")
            return layers[layer_index]

        @app.get("/api/preview-media/{scene_index}/{layer_index}")
        async def preview_media(
            scene_index: int,
            layer_index: int,
            height: int = Query(720, ge=240, le=1080),
            fps: int = Query(30, ge=12, le=60),
        ) -> FileResponse:
            layer = _timeline_layer(scene_index, layer_index)
            try:
                source = _resolve_timeline_media(library, layer.media_file, getattr(layer, "media_url", None))
                preview = await asyncio.to_thread(
                    prepare_preview_proxy, source, library.preview_dir,
                    max_height=int(height), max_fps=int(fps),
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=f"source media unavailable: {exc}") from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return FileResponse(
                preview.path,
                media_type="video/mp4" if preview.path.suffix.lower() == ".mp4" else None,
                headers={
                    "Cache-Control": "private, max-age=31536000, immutable",
                    "X-Tubeviz-Preview-Proxy": "1" if preview.path.parent == library.preview_dir else "0",
                    "X-Tubeviz-Preview-Encoder": preview.encoder or "source",
                },
            )

        @app.get("/api/browser-source/{scene_index}/{layer_index}")
        @app.get("/api/offline-source/{scene_index}/{layer_index}")
        async def browser_source(
            scene_index: int,
            layer_index: int,
            fps: float = Query(30.0, gt=0.0, le=120.0),
        ) -> Response:
            layer = _timeline_layer(scene_index, layer_index)
            try:
                source = _resolve_timeline_media(library, layer.media_file, getattr(layer, "media_url", None))
                cache_file, encoder = await asyncio.to_thread(
                    _make_browser_source_cache,
                    source,
                    start=float(layer.start),
                    end=float(layer.end),
                    fps=float(fps),
                    cache_dir=library.root / "browser-webcodecs-cache",
                    return_path=True,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=f"source media unavailable: {exc}") from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return FileResponse(
                cache_file,
                media_type="application/x-tubeviz-h264",
                headers={
                    "Cache-Control": "private, max-age=31536000, immutable",
                    "X-Tubeviz-Source-Encoder": encoder,
                    "X-Tubeviz-Source-FPS": f"{float(fps):g}",
                    "X-Tubeviz-Source-Transport": "TVZ2",
                },
            )

    if offline_render_sink is not None:
        @app.websocket("/ws/offline-render")
        async def offline_render_endpoint(websocket: WebSocket) -> None:
            """Receive browser-rendered H.264 or raw-RGBA data without per-frame RPC."""
            await websocket.accept()
            generation = getattr(offline_render_sink, "generation", None)
            try:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    data = message.get("bytes")
                    if data is not None:
                        if generation is None:
                            await asyncio.to_thread(offline_render_sink.consume, data)
                        else:
                            await asyncio.to_thread(offline_render_sink.consume, data, generation)
                        continue
                    text = message.get("text")
                    if not text:
                        continue
                    import json
                    payload = json.loads(text)
                    if payload.get("type") == "complete":
                        if generation is None:
                            await asyncio.to_thread(offline_render_sink.complete, payload)
                        else:
                            await asyncio.to_thread(offline_render_sink.complete, payload, generation)
                        await websocket.send_json({"type": "complete", "frames": payload.get("frames", 0)})
                        return
            except WebSocketDisconnect:
                return
            except Exception as exc:
                try:
                    await websocket.send_json({"type": "error", "error": str(exc)})
                finally:
                    await websocket.close(code=1011)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        cursor = TimelineCursor(timeline)
        playing = False
        playback_start_monotonic = 0.0
        playback_start_position = 0.0

        async def restore(position: float) -> None:
            cursor.reset(position)
            await websocket.send_json(_state_at(timeline, position))

        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=1.0 / 60.0
                    )
                    command = message.get("command")
                    if command == "play":
                        playback_start_position = float(message.get("position", 0.0))
                        playback_start_monotonic = time.monotonic()
                        await restore(playback_start_position)
                        playing = True
                    elif command == "pause":
                        if playing:
                            playback_start_position += time.monotonic() - playback_start_monotonic
                        playing = False
                    elif command == "seek":
                        playback_start_position = float(message["position"])
                        playback_start_monotonic = time.monotonic()
                        await restore(playback_start_position)
                except asyncio.TimeoutError:
                    pass

                if not playing:
                    continue

                now = playback_start_position + (time.monotonic() - playback_start_monotonic)
                if now > timeline.track.duration:
                    playing = False
                    await websocket.send_json({"type": "ended", "time": timeline.track.duration})
                    continue

                cues = cursor.advance(now)
                await websocket.send_json(
                    {
                        "type": "frame",
                        "time": now,
                        "cues": [cue.model_dump(mode="json") for cue in cues],
                    }
                )
        except WebSocketDisconnect:
            return

    return app
