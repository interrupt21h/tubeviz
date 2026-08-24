# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .library import ClipLibrary
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


def create_app(
    timeline_path: str | Path,
    audio_path: str | Path | None = None,
    library_path: str | Path | None = None,
    *,
    replan_scenes: bool = False,
    scene_config: SceneSelectorConfig | None = None,
    replan_transforms: bool = False,
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

    app = FastAPI(title="tubeviz", version="0.26.2")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    if library is not None:
        # StaticFiles resolves requests beneath this directory and rejects path
        # traversal; only normalized visualization assets are exposed.
        app.mount(
            "/media",
            StaticFiles(directory=library.normalized_dir, check_dir=True),
            name="media",
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
        }

    if audio_path is not None:
        resolved_audio = Path(audio_path).expanduser().resolve()

        @app.get("/audio")
        async def audio() -> FileResponse:
            return FileResponse(resolved_audio)

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
