from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .library import ClipLibrary
from .native_render import native_doctor


class JobRequest(BaseModel):
    kind: str
    library: str = "./library"
    audio: str | None = None
    timeline: str | None = None
    output: str | None = None
    terms: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ClipAction(BaseModel):
    library: str = "./library"
    reason: str | None = None
    keep_original: bool = False


@dataclass
class GuiJob:
    id: str
    kind: str
    command: list[str]
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    returncode: int | None = None
    status: str = "queued"
    log: deque[str] = field(default_factory=lambda: deque(maxlen=4000))
    process: subprocess.Popen[str] | None = None

    def payload(self, *, tail: int = 250) -> dict[str, Any]:
        lines = list(self.log)
        if tail > 0:
            lines = lines[-tail:]
        return {
            "id": self.id,
            "kind": self.kind,
            "command": self.command,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "returncode": self.returncode,
            "status": self.status,
            "log": lines,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, GuiJob] = {}
        self._lock = threading.RLock()

    def create(self, kind: str, command: list[str]) -> GuiJob:
        job = GuiJob(id=uuid.uuid4().hex[:12], kind=kind, command=command)
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: GuiJob) -> None:
        job.status = "running"
        job.started_at = time.time()
        job.log.append("$ " + " ".join(job.command))
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        try:
            proc = subprocess.Popen(
                job.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                start_new_session=True,
            )
            job.process = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                job.log.append(line.rstrip())
            job.returncode = proc.wait()
            job.status = "complete" if job.returncode == 0 else "failed"
        except Exception as exc:
            job.log.append(f"GUI job error: {exc}")
            job.returncode = -1
            job.status = "failed"
        finally:
            job.ended_at = time.time()
            job.process = None

    def get(self, job_id: str) -> GuiJob:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def list(self) -> list[GuiJob]:
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> GuiJob:
        job = self.get(job_id)
        proc = job.process
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            job.log.append("Cancellation requested.")
            job.status = "cancelling"
        return job


def _tubeviz_command(*parts: str) -> list[str]:
    return [sys.executable, "-m", "tubeviz.cli", *parts]


def _flag(command: list[str], name: str, value: Any, *, boolean: bool = False) -> None:
    if boolean:
        if bool(value):
            command.append(name)
        return
    if value is None or value == "":
        return
    command += [name, str(value)]


def _job_command(request: JobRequest) -> list[str]:
    kind = request.kind
    o = request.options
    library = str(Path(request.library).expanduser())

    if kind == "analyze":
        if not request.audio:
            raise ValueError("audio is required")
        command = _tubeviz_command("analyze", request.audio)
        _flag(command, "--library", library)
        _flag(command, "--output", request.output or "timeline.json")
        _flag(command, "--semantic", o.get("semantic", True), boolean=True)
        _flag(command, "--semantic-device", o.get("semantic_device", "auto"))
        _flag(command, "--section-bars", o.get("section_bars", 8))
        _flag(command, "--max-video-layers", o.get("max_video_layers", 3))
        _flag(command, "--composition-intensity", o.get("composition_intensity", 1.0))
        _flag(command, "--transform-intensity", o.get("transform_intensity", 1.0))
        _flag(command, "--target-unique-clips", o.get("target_unique_clips", 0))
        _flag(command, "--novelty-weight", o.get("novelty_weight", 0.65))
        _flag(command, "--visual-match-weight", o.get("visual_match_weight", 1.25))
        _flag(command, "--transition-weight", o.get("transition_weight", 0.70))
        if o.get("rhythm_alignment", True) is False:
            command.append("--no-rhythm-alignment")
        _flag(command, "--selection-variation", o.get("selection_variation", 0.30))
        _flag(command, "--min-shot-seconds", o.get("min_shot_seconds", 0.65))
        _flag(command, "--max-shot-seconds", o.get("max_shot_seconds", 6.0))
        _flag(command, "--source-excerpt-max-seconds", o.get("source_excerpt_max_seconds", 5.0))
        if o.get("selection_seed"):
            _flag(command, "--selection-seed", o["selection_seed"])
        elif o.get("reshuffle", True):
            command.append("--reshuffle")
        if o.get("dynamic_shots", True) is False:
            command.append("--no-dynamic-shots")
        return command

    if kind == "render":
        if not request.timeline:
            raise ValueError("timeline is required")
        command = _tubeviz_command("render", request.timeline)
        _flag(command, "--library", library)
        _flag(command, "--audio", request.audio)
        _flag(command, "--output", request.output or "tubeviz-output.mp4")
        _flag(command, "--backend", o.get("backend", "native"))
        _flag(command, "--width", o.get("width", 1920))
        _flag(command, "--height", o.get("height", 1080))
        _flag(command, "--fps", o.get("fps", 30))
        _flag(command, "--crf", o.get("crf", 20))
        _flag(command, "--video-codec", o.get("video_codec", "libx264"))
        _flag(command, "--native-preset", o.get("native_preset", "veryfast"))
        _flag(command, "--native-decoder-cache", o.get("native_decoder_cache", 16))
        _flag(command, "--native-threads", o.get("native_threads", 0))
        _flag(command, "--native-build-if-missing", o.get("native_build_if_missing", True), boolean=True)
        _flag(command, "--browser-executable", o.get("browser_executable"))
        return command

    if kind == "ingest":
        if not request.terms:
            raise ValueError("terms file is required")
        command = _tubeviz_command("ingest", "--terms", request.terms, "--library", library)
        _flag(command, "--results-per-term", o.get("results_per_term", 5))
        _flag(command, "--hard-max-duration", o.get("hard_max_duration", 600))
        _flag(command, "--cookies-from-browser", o.get("cookies_from_browser"))
        _flag(command, "--ai-discovery", o.get("ai_discovery", True), boolean=True)
        _flag(command, "--ai-device", o.get("ai_device", "auto"))
        _flag(command, "--ai-query-count", o.get("ai_query_count", 8))
        _flag(command, "--ai-candidates-per-term", o.get("ai_candidates_per_term", 100))
        _flag(command, "--ai-min-score", o.get("ai_min_score", -0.05))
        if o.get("visual_index_scenes", True) is False:
            command.append("--no-visual-index-scenes")
        return command

    if kind == "visual-index":
        command = _tubeviz_command("library", "visual-index", "--library", library)
        _flag(command, "--fps", o.get("fps", 6))
        _flag(command, "--max-frames", o.get("max_frames", 180))
        _flag(command, "--force", o.get("force", False), boolean=True)
        return command

    if kind == "native-build":
        command = _tubeviz_command("native", "build")
        _flag(command, "--clean", o.get("clean", False), boolean=True)
        _flag(command, "--jobs", o.get("jobs"))
        return command

    if kind == "preview":
        if not request.timeline:
            raise ValueError("timeline is required")
        port = int(o.get("port", 8080))
        command = _tubeviz_command("serve", request.timeline)
        _flag(command, "--library", library)
        _flag(command, "--audio", request.audio)
        _flag(command, "--host", o.get("host", "127.0.0.1"))
        _flag(command, "--port", port)
        if o.get("replan_scenes"):
            command.append("--replan-scenes")
            _flag(command, "--semantic", o.get("semantic", True), boolean=True)
            _flag(command, "--semantic-device", o.get("semantic_device", "auto"))
            if o.get("reshuffle", False):
                command.append("--reshuffle")
        return command

    if kind == "materialize":
        if not request.timeline:
            raise ValueError("timeline is required")
        command = _tubeviz_command("materialize", request.timeline)
        _flag(command, "--library", library)
        _flag(command, "--output", request.output or "timeline.materialized.json")
        _flag(command, "--width", o.get("width", 1280))
        _flag(command, "--height", o.get("height", 720))
        _flag(command, "--fps", o.get("fps", 30))
        _flag(command, "--crf", o.get("crf", 20))
        return command

    raise ValueError(f"unsupported GUI job kind: {kind}")


def create_gui_app(
    *,
    default_library: str | Path = "./library",
    project_root: str | Path = ".",
) -> FastAPI:
    root = Path(project_root).expanduser().resolve()
    default_library = Path(default_library).expanduser().resolve()
    package_dir = Path(__file__).resolve().parent
    static_dir = package_dir / "static"
    jobs = JobManager()

    app = FastAPI(title="tubeviz studio", version="0.21.0")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "gui.html")

    @app.get("/api/gui/config")
    async def config() -> dict[str, Any]:
        return {
            "project_root": str(root),
            "library": str(default_library),
            "native": native_doctor(),
        }

    @app.get("/api/gui/library")
    async def library_state(
        library: str = Query(default=str(default_library)),
        status: str | None = None,
        term: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        lib = ClipLibrary(library)
        lib.initialize()
        return {
            "stats": lib.stats(),
            "terms": lib.list_terms(),
            "clips": lib.list_clips(status=status, term=term, limit=min(1000, max(1, limit))),
        }

    @app.get("/api/gui/clip/{source_id}")
    async def clip_details(
        source_id: str,
        library: str = Query(default=str(default_library)),
        source: str = "youtube",
    ) -> dict[str, Any]:
        lib = ClipLibrary(library)
        lib.initialize()
        details = lib.clip_details(source, source_id)
        if details is None:
            raise HTTPException(404, "clip not found")
        return details

    @app.get("/api/gui/clip/{source_id}/media")
    async def clip_media(
        source_id: str,
        library: str = Query(default=str(default_library)),
        source: str = "youtube",
    ) -> FileResponse:
        lib = ClipLibrary(library)
        lib.initialize()
        path = lib.resolve_clip_media(source, source_id)
        if path is None:
            diagnostic = lib.clip_media_diagnostic(source, source_id)
            if not diagnostic["found"]:
                raise HTTPException(
                    404,
                    {
                        "message": "clip not found",
                        **diagnostic,
                    },
                )
            raise HTTPException(
                404,
                {
                    "message": "clip exists but has no playable local media",
                    **diagnostic,
                },
            )
        return FileResponse(path)

    @app.get("/api/gui/clip/{source_id}/thumbnail")
    async def clip_thumbnail(
        source_id: str,
        library: str = Query(default=str(default_library)),
        source: str = "youtube",
    ) -> FileResponse:
        lib = ClipLibrary(library)
        lib.initialize()
        details = lib.clip_details(source, source_id)
        if details is None:
            raise HTTPException(404, "clip not found")
        for scene in details.get("scenes", []):
            rel = scene.get("thumbnail_path")
            if rel:
                path = (lib.root / rel).resolve()
                try:
                    path.relative_to(lib.root)
                except ValueError:
                    continue
                if path.is_file():
                    return FileResponse(path)
        ai_thumb = lib.metadata_dir / "ai-thumbnails" / f"{source_id}.jpg"
        if ai_thumb.is_file():
            return FileResponse(ai_thumb)
        raise HTTPException(404, "thumbnail not found")

    @app.post("/api/gui/clip/{source_id}/reject")
    async def reject_clip(source_id: str, action: ClipAction) -> dict[str, Any]:
        lib = ClipLibrary(action.library)
        lib.initialize()
        try:
            record = lib.reject_clip(
                "youtube", source_id, reason=action.reason or "rejected in tubeviz studio"
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"source_id": source_id, "status": record.status}

    @app.post("/api/gui/clip/{source_id}/restore")
    async def restore_clip(source_id: str, action: ClipAction) -> dict[str, Any]:
        lib = ClipLibrary(action.library)
        lib.initialize()
        try:
            record = lib.restore_clip("youtube", source_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"source_id": source_id, "status": record.status}

    @app.post("/api/gui/clip/{source_id}/delete")
    async def delete_clip(source_id: str, action: ClipAction) -> dict[str, Any]:
        lib = ClipLibrary(action.library)
        lib.initialize()
        try:
            return lib.delete_clip(
                "youtube",
                source_id,
                dry_run=False,
                keep_original=action.keep_original,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/gui/jobs")
    async def start_job(request: JobRequest) -> dict[str, Any]:
        try:
            command = _job_command(request)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jobs.create(request.kind, command).payload()

    @app.get("/api/gui/jobs")
    async def list_jobs() -> list[dict[str, Any]]:
        return [job.payload(tail=80) for job in jobs.list()[:30]]

    @app.get("/api/gui/jobs/{job_id}")
    async def get_job(job_id: str, tail: int = 500) -> dict[str, Any]:
        try:
            return jobs.get(job_id).payload(tail=min(4000, max(1, tail)))
        except KeyError as exc:
            raise HTTPException(404, "job not found") from exc

    @app.post("/api/gui/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return jobs.cancel(job_id).payload()
        except KeyError as exc:
            raise HTTPException(404, "job not found") from exc

    return app
