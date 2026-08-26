# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
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

from . import __version__
from .library import ClipLibrary
from .native_render import native_doctor
from .codec_glitch import codec_doctor
from .settings import load_settings, save_settings


class JobRequest(BaseModel):
    kind: str
    library: str = "./library"
    audio: str | None = None
    timeline: str | None = None
    output: str | None = None
    terms: str | None = None
    visual_brief: str | None = None
    urls: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    hf_token: str | None = Field(default=None, exclude=True)
    llm_api_key: str | None = Field(default=None, exclude=True)


class ClipAction(BaseModel):
    library: str = "./library"
    reason: str | None = None
    keep_original: bool = False


class ClipTrimAction(BaseModel):
    library: str = "./library"
    source: str = "youtube"
    usable_start: float | None = None
    usable_end: float | None = None


class ClipTagsAction(BaseModel):
    library: str = "./library"
    source: str = "youtube"
    tags: list[str] = Field(default_factory=list)


class OutputSelectionAction(BaseModel):
    library: str = "./library"
    clip_ids: list[int] = Field(default_factory=list)
    tag: str | None = None
    selected: bool = True


class AISettingsAction(BaseModel):
    ai_enabled: bool = True
    vision_enabled: bool = False
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_vision_model: str = "gpt-5.1"
    vision_detail: str = "low"
    vision_max_frames: int = 12
    vision_timeout_seconds: int = 180
    hf_token: str | None = None
    clear_openai_key: bool = False
    clear_hf_token: bool = False


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
    metadata: dict[str, Any] = field(default_factory=dict)
    env_overrides: dict[str, str] = field(default_factory=dict, repr=False)
    stage: str = "Queued"
    progress_current: int | None = None
    progress_total: int | None = None
    progress_percent: float | None = None
    progress_eta_seconds: float | None = None

    def observe(self, line: str) -> None:
        """Extract stable progress metadata while retaining the original log line."""
        text = line.strip()
        if not text:
            return
        lower = text.lower()
        stage_rules = (
            ("ai describe", "Understanding video content"),
            ("search", "Discovering footage"), ("preview", "Evaluating previews"),
            ("download", "Downloading media"), ("media prep", "Preparing media"),
            ("transcode", "Creating compatibility proxy"), ("normalize", "Creating compatibility proxy"),
            ("visual feature", "Indexing visual features"), ("embedded", "Embedding scenes"),
            ("semantic", "Classifying scenes"), ("audio ai", "Analyzing audio semantics"),
            ("music ai", "Analyzing music representations"), ("analy", "Analyzing music"),
            ("scene", "Planning scenes"), ("materializ", "Materializing effects"),
            ("native build", "Building native renderer"), ("native configure", "Configuring native renderer"),
            ("native frame", "Rendering video"), ("frame ", "Rendering video"),
            ("codec", "Processing codec effects"), ("wrote ", "Finalizing output"),
        )
        for needle, label in stage_rules:
            if needle in lower:
                self.stage = label
                break
        matches = list(re.finditer(r"(?<![\d.])(\d+)\s*/\s*(\d+)(?![\d.])", text))
        if matches:
            current, total = (int(value) for value in matches[-1].groups())
            if total > 0 and 0 <= current <= total:
                self.progress_current, self.progress_total = current, total
                self.progress_percent = min(100.0, 100.0 * current / total)
        percent = re.search(r"\(\s*(\d+(?:\.\d+)?)%\s*\)", text)
        if percent:
            self.progress_percent = max(0.0, min(100.0, float(percent.group(1))))
        eta = re.search(r"\bETA\s+(\d+(?:\.\d+)?)s\b", text, re.IGNORECASE)
        if eta:
            self.progress_eta_seconds = float(eta.group(1))

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
            "stage": self.stage,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "progress_percent": self.progress_percent,
            "progress_eta_seconds": self.progress_eta_seconds,
            "elapsed_seconds": max(0.0, (self.ended_at or time.time()) - (self.started_at or self.created_at)),
            "log": lines,
            **self.metadata,
        }


class JobManager:
    def __init__(self, *, cwd: str | Path | None = None) -> None:
        self._jobs: dict[str, GuiJob] = {}
        self._lock = threading.RLock()
        self._cwd = Path(cwd).expanduser().resolve() if cwd is not None else None

    def create(
        self,
        kind: str,
        command: list[str],
        *,
        metadata: dict[str, Any] | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> GuiJob:
        job = GuiJob(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            command=command,
            metadata=dict(metadata or {}),
            env_overrides=dict(env_overrides or {}),
        )
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: GuiJob) -> None:
        if job.status == "cancelled":
            job.ended_at = time.time()
            return
        job.status = "running"
        job.stage = "Starting"
        job.started_at = time.time()
        job.log.append("$ " + " ".join(job.command))
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.update(job.env_overrides)
        try:
            proc = subprocess.Popen(
                job.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                cwd=str(self._cwd) if self._cwd is not None else None,
                start_new_session=True,
            )
            job.process = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                clean = line.rstrip()
                job.log.append(clean)
                job.observe(clean)
            job.returncode = proc.wait()
            job.status = "complete" if job.returncode == 0 else "failed"
            job.stage = "Complete" if job.returncode == 0 else "Failed"
            if job.returncode == 0:
                job.progress_percent = 100.0
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
        if job.status == "queued" and proc is None:
            job.status = "cancelled"
            job.ended_at = time.time()
            job.log.append("Cancelled before start.")
            return job
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            job.log.append("Cancellation requested.")
            job.status = "cancelling"
        return job

    def cancel_kind(self, kind: str) -> list[GuiJob]:
        cancelled: list[GuiJob] = []
        for job in self.list():
            if job.kind != kind:
                continue
            if job.status not in {"queued", "running", "cancelling"}:
                continue
            cancelled.append(self.cancel(job.id))
        return cancelled


def _free_tcp_port(host: str = "127.0.0.1") -> int:
    # Bind port 0 only long enough to obtain an unused local preview port.
    # The preview subprocess is launched immediately afterwards.
    bind_host = "127.0.0.1" if host in {"0.0.0.0", "::", "localhost"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((bind_host, 0))
        return int(sock.getsockname()[1])


def _tubeviz_command(*parts: str) -> list[str]:
    return [sys.executable, "-u", "-m", "tubeviz.cli", *parts]


def _flag(command: list[str], name: str, value: Any, *, boolean: bool = False) -> None:
    if boolean:
        if bool(value):
            command.append(name)
        return
    if value is None or value == "":
        return
    command += [name, str(value)]


_GUI_CLI_ALLOWED_TOP_LEVEL = {
    "ingest", "ingest-url", "library", "audio-ai", "music-ai", "choreography", "analyze", "materialize",
    "render", "codec", "native", "serve",
}


def _jsonable_default(value: Any) -> Any:
    if value is argparse.SUPPRESS:
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable_default(item) for item in value]
    return str(value)


def _action_schema(action: argparse.Action) -> dict[str, Any]:
    flags = list(action.option_strings)
    positive_flag = next((flag for flag in flags if not flag.startswith("--no-")), flags[0] if flags else None)
    negative_flag = next((flag for flag in flags if flag.startswith("--no-")), None)
    action_name = action.__class__.__name__
    value_type = None
    if getattr(action, "type", None) is int:
        value_type = "int"
    elif getattr(action, "type", None) is float:
        value_type = "float"
    elif getattr(action, "type", None) is not None:
        value_type = getattr(action.type, "__name__", "string")
    else:
        value_type = "string"
    choices = getattr(action, "choices", None)
    return {
        "dest": action.dest,
        "flags": flags,
        "positive_flag": positive_flag,
        "negative_flag": negative_flag,
        "positional": not bool(flags),
        "required": bool(getattr(action, "required", False)) or (not flags and action.nargs not in ("?", "*")),
        "nargs": action.nargs,
        "default": _jsonable_default(getattr(action, "default", None)),
        "choices": list(choices) if choices is not None else None,
        "type": value_type,
        "action": action_name,
        "help": action.help if action.help is not argparse.SUPPRESS else None,
        "metavar": action.metavar,
    }


def cli_schema() -> dict[str, Any]:
    """Return the current argparse command tree for Studio's parity UI.

    Importing cli lazily avoids the cli -> gui import cycle during module load.
    The GUI command itself is deliberately excluded: Studio should operate the
    current Studio process rather than recursively launching another one.
    """
    from .cli import build_parser

    root = build_parser()
    commands: list[dict[str, Any]] = []

    def walk(parser: argparse.ArgumentParser, path: list[str]) -> None:
        subparsers = [
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        normal = [
            action for action in parser._actions
            if not isinstance(action, (argparse._HelpAction, argparse._SubParsersAction))
        ]
        if path and not subparsers:
            if path[0] in _GUI_CLI_ALLOWED_TOP_LEVEL:
                commands.append({
                    "path": path,
                    "name": " ".join(path),
                    "description": parser.description or "",
                    "arguments": [_action_schema(action) for action in normal],
                })
            return
        for sub in subparsers:
            for name, child in sub.choices.items():
                if not path and name == "gui":
                    continue
                walk(child, [*path, name])

    walk(root, [])
    commands.sort(key=lambda item: item["name"])
    return {"commands": commands}


def _validated_cli_command(argv: Any) -> list[str]:
    if not isinstance(argv, list) or not argv:
        raise ValueError("CLI argv must be a non-empty list")
    clean: list[str] = []
    for token in argv:
        if not isinstance(token, str):
            raise ValueError("CLI argv entries must be strings")
        if "\\x00" in token:
            raise ValueError("CLI argv entries may not contain NUL bytes")
        if len(token) > 32768:
            raise ValueError("CLI argv entry is unreasonably large")
        clean.append(token)
    if clean[0] not in _GUI_CLI_ALLOWED_TOP_LEVEL:
        raise ValueError(f"unsupported GUI CLI command: {clean[0]}")

    # Parse against the actual current CLI. This catches unknown/removed flags
    # while preserving argument-vector execution (no shell interpolation).
    from .cli import build_parser
    parser = build_parser()
    try:
        namespace = parser.parse_args(clean)
    except SystemExit as exc:
        raise ValueError("invalid tubeviz CLI arguments") from exc
    if not callable(getattr(namespace, "func", None)):
        raise ValueError("incomplete tubeviz CLI command")
    return _tubeviz_command(*clean)


def _job_command(request: JobRequest) -> list[str]:
    kind = request.kind
    o = request.options
    library = str(Path(request.library).expanduser())

    if kind == "cli":
        return _validated_cli_command(o.get("argv"))

    if kind == "ingest-url":
        urls = [url.strip() for url in request.urls if url and url.strip()]
        if not urls:
            raise ValueError("at least one YouTube URL is required")
        command = _tubeviz_command("ingest-url", *urls, "--library", library)
        _flag(command, "--term", o.get("term", "manual"))
        _flag(command, "--min-duration", o.get("min_duration", 0.0))
        _flag(command, "--hard-max-duration", o.get("hard_max_duration", 0.0))
        _flag(command, "--min-width", o.get("min_width", 0))
        _flag(command, "--min-source-height", o.get("min_source_height", 1080))
        _flag(command, "--max-source-height", o.get("max_source_height", 1080))
        _flag(command, "--media-prep", o.get("media_prep", "auto"))
        _flag(command, "--normalize-encoder", o.get("normalize_encoder", "auto"))
        _flag(command, "--width", o.get("width", 0))
        _flag(command, "--height", o.get("height", 0))
        _flag(command, "--fps", o.get("fps", 0))
        _flag(command, "--scene-threshold", o.get("scene_threshold", 0.40))
        _flag(command, "--min-scene-seconds", o.get("min_scene_seconds", 1.5))
        _flag(command, "--keep-audio", o.get("keep_audio", False), boolean=True)
        _flag(command, "--no-scenes", o.get("no_scenes", False), boolean=True)
        _flag(command, "--no-visual-index", o.get("no_visual_index", False), boolean=True)
        _flag(command, "--no-semantic-index", o.get("no_semantic_index", False), boolean=True)
        _flag(command, "--no-scene-classification", o.get("no_scene_classification", False), boolean=True)
        _flag(command, "--semantic-device", o.get("semantic_device", "auto"))
        _flag(command, "--semantic-model", o.get("semantic_model", "ViT-B-32"))
        _flag(command, "--semantic-pretrained", o.get("semantic_pretrained", "laion2b_s34b_b79k"))
        _flag(command, "--force", o.get("force", False), boolean=True)
        _flag(command, "--cookies-from-browser", o.get("cookies_from_browser"))
        _flag(command, "--download-socket-timeout", o.get("download_socket_timeout", 20.0))
        _flag(command, "--concurrent-fragments", o.get("concurrent_fragments", 4))
        _flag(command, "--download-retries", o.get("download_retries", 2))
        _flag(command, "--fragment-retries", o.get("fragment_retries", 2))
        _flag(command, "--verbose-ytdlp", o.get("verbose_ytdlp", False), boolean=True)
        return command

    if kind == "analyze":
        if not request.audio:
            raise ValueError("audio is required")
        command = _tubeviz_command("analyze", request.audio)
        _flag(command, "--library", library)
        _flag(command, "--output", request.output or "timeline.json")
        _flag(command, "--semantic", o.get("semantic", True), boolean=True)
        _flag(command, "--semantic-device", o.get("semantic_device", "auto"))
        if o.get("music_ai", False):
            command.append("--music-ai")
            _flag(command, "--music-ai-model", o.get("music_ai_model", "m-a-p/MERT-v1-95M"))
            _flag(command, "--music-ai-device", o.get("music_ai_device", "auto"))
            _flag(command, "--music-ai-window", o.get("music_ai_window", 8))
            _flag(command, "--music-ai-hop", o.get("music_ai_hop", 4))
        if o.get("audio_ai", False):
            command.append("--audio-ai")
            _flag(command, "--audio-ai-model", o.get("audio_ai_model", "laion/clap-htsat-fused"))
            _flag(command, "--audio-ai-device", o.get("audio_ai_device", "auto"))
            _flag(command, "--audio-ai-window", o.get("audio_ai_window", 8))
            _flag(command, "--audio-ai-hop", o.get("audio_ai_hop", 4))
            _flag(command, "--audio-visual-match-weight", o.get("audio_visual_match_weight", 1.10))
        if o.get("choreography", True) is False:
            command.append("--no-choreography")
        _flag(command, "--trajectory-strength", o.get("trajectory_strength", 0.85))
        _flag(command, "--anticipation-seconds", o.get("anticipation_seconds", 12.0))
        _flag(command, "--visual-arc-strength", o.get("visual_arc_strength", 0.70))
        _flag(command, "--sequence-lookahead", o.get("sequence_lookahead", 5))
        _flag(command, "--sequence-beam-width", o.get("sequence_beam_width", 6))
        _flag(command, "--sequence-candidate-pool", o.get("sequence_candidate_pool", 18))
        _flag(command, "--trajectory-weight", o.get("trajectory_weight", 0.85))
        _flag(command, "--anticipation-weight", o.get("anticipation_weight", 0.75))
        _flag(command, "--effect-compatibility-weight", o.get("effect_compatibility_weight", 0.60))
        if o.get("preference_learning", True) is False:
            command.append("--no-preference-learning")
        _flag(command, "--preference-weight", o.get("preference_weight", 0.35))
        if o.get("ai_director", False):
            command.append("--ai-director")
            _flag(command, "--ai-director-base-url", o.get("ai_director_base_url"))
            _flag(command, "--ai-director-model", o.get("ai_director_model"))
            _flag(command, "--ai-director-strength", o.get("ai_director_strength", .75))
        _flag(command, "--section-bars", o.get("section_bars", 8))
        _flag(command, "--max-video-layers", o.get("max_video_layers", 3))
        _flag(command, "--composition-intensity", o.get("composition_intensity", 1.0))
        _flag(command, "--transform-intensity", o.get("transform_intensity", 1.0))
        _flag(command, "--target-unique-clips", o.get("target_unique_clips", 0))
        _flag(command, "--novelty-weight", o.get("novelty_weight", 0.65))
        _flag(command, "--visual-match-weight", o.get("visual_match_weight", 1.25))
        _flag(command, "--transition-weight", o.get("transition_weight", 0.70))
        _flag(command, "--vector-intensity", o.get("vector_intensity", 1.0))
        _flag(command, "--codec-glitch", o.get("codec_glitch", "off"))
        _flag(command, "--codec-glitch-intensity", o.get("codec_glitch_intensity", 0.65))
        if o.get("vector_effects", True) is False:
            command.append("--no-vector-effects")
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
        _flag(command, "--codec-materialize", o.get("codec_materialize", False), boolean=True)
        _flag(command, "--codec-ffedit", o.get("codec_ffedit", "ffedit"))
        _flag(command, "--codec-qscale", o.get("codec_qscale", 3))
        _flag(command, "--codec-gop", o.get("codec_gop", 18))
        return command

    if kind == "ingest":
        if not request.terms and not request.visual_brief:
            raise ValueError("terms file or visual brief is required")
        command = _tubeviz_command("ingest", "--library", library)
        _flag(command, "--terms", request.terms)
        _flag(command, "--visual-brief", request.visual_brief)
        _flag(command, "--audio", request.audio if request.visual_brief else None)
        _flag(command, "--results-per-term", o.get("results_per_term", 5))
        _flag(command, "--hard-max-duration", o.get("hard_max_duration", 600))
        _flag(command, "--min-source-height", o.get("min_source_height", 1080))
        _flag(command, "--max-source-height", o.get("max_source_height", 1080))
        _flag(command, "--media-prep", o.get("media_prep", "auto"))
        _flag(command, "--normalize-encoder", o.get("normalize_encoder", "auto"))
        _flag(command, "--width", o.get("width", 0))
        _flag(command, "--height", o.get("height", 0))
        _flag(command, "--fps", o.get("fps", 0))
        _flag(command, "--cookies-from-browser", o.get("cookies_from_browser"))
        _flag(command, "--ai-discovery", o.get("ai_discovery", True), boolean=True)
        _flag(command, "--ai-device", o.get("ai_device", "auto"))
        _flag(command, "--ai-query-count", o.get("ai_query_count", 8))
        _flag(command, "--ai-candidates-per-term", o.get("ai_candidates_per_term", 100))
        _flag(command, "--ai-min-score", o.get("ai_min_score", -0.05))
        _flag(command, "--ai-llm-base-url", o.get("ai_llm_base_url"))
        _flag(command, "--ai-llm-model", o.get("ai_llm_model"))
        _flag(command, "--target-clips", o.get("target_clips", 40))
        _flag(command, "--acquisition-query-count", o.get("acquisition_query_count", 24))
        _flag(command, "--preview-gate", o.get("preview_gate", bool(request.visual_brief)), boolean=True)
        _flag(command, "--preview-seconds", o.get("preview_seconds", 4))
        _flag(command, "--preview-samples", o.get("preview_samples", 4))
        _flag(command, "--min-video-fitness", o.get("min_video_fitness", .18))
        _flag(command, "--min-dynamic-score", o.get("min_dynamic_score", .24))
        _flag(command, "--max-text-overlay-fraction", o.get("max_text_overlay_fraction", .10))
        _flag(command, "--max-persistent-text-fraction", o.get("max_persistent_text_fraction", .045))
        _flag(command, "--min-motion-coverage", o.get("min_motion_coverage", .20))
        _flag(command, "--min-temporal-diversity", o.get("min_temporal_diversity", .12))
        _flag(command, "--max-face-dominance", o.get("max_face_dominance", .42))
        _flag(command, "--min-aesthetic-score", o.get("min_aesthetic_score", .22))
        _flag(command, "--sample-long-videos", o.get("sample_long_videos", True), boolean=True)
        _flag(command, "--long-video-segment-attempts", o.get("long_video_segment_attempts", 8))
        _flag(command, "--long-video-excerpt-seconds", o.get("long_video_excerpt_seconds", 45))
        _flag(command, "--auto-trim", o.get("auto_trim", True), boolean=True)
        if o.get("visual_index_scenes", True) is False:
            command.append("--no-visual-index-scenes")
        return command

    if kind == "visual-index":
        command = _tubeviz_command("library", "visual-index", "--library", library)
        _flag(command, "--fps", o.get("fps", 6))
        _flag(command, "--max-frames", o.get("max_frames", 180))
        _flag(command, "--force", o.get("force", False), boolean=True)
        return command

    if kind == "ai-describe":
        command = _tubeviz_command("library", "ai-describe", "--library", library)
        _flag(command, "--clip-id", o.get("clip_id"))
        _flag(command, "--limit", o.get("limit", 0))
        _flag(command, "--force", o.get("force", False), boolean=True)
        return command

    if kind == "codec-doctor":
        return _tubeviz_command("codec", "doctor")

    if kind == "codec-materialize":
        if not request.timeline:
            raise ValueError("timeline is required")
        command = _tubeviz_command("codec", "materialize", request.timeline)
        _flag(command, "--library", library)
        _flag(command, "--output", request.output or "timeline.codec.json")
        _flag(command, "--qscale", o.get("qscale", 3))
        _flag(command, "--gop", o.get("gop", 18))
        _flag(command, "--force", o.get("force", False), boolean=True)
        return command

    if kind == "codec-motion-index":
        command = _tubeviz_command("library", "codec-motion-index", "--library", library)
        _flag(command, "--force", o.get("force", False), boolean=True)
        return command

    if kind == "audio-ai-doctor":
        command = _tubeviz_command("audio-ai", "doctor")
        _flag(command, "--model", o.get("model", "laion/clap-htsat-fused"))
        _flag(command, "--device", o.get("device", "auto"))
        return command

    if kind == "music-ai-doctor":
        command = _tubeviz_command("music-ai", "doctor")
        _flag(command, "--model", o.get("model", "m-a-p/MERT-v1-95M"))
        _flag(command, "--device", o.get("device", "auto"))
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
        _flag(command, "--codec-materialize", o.get("codec_materialize", False), boolean=True)
        _flag(command, "--codec-qscale", o.get("codec_qscale", 3))
        _flag(command, "--codec-gop", o.get("codec_gop", 18))
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


def _job_env_overrides(request: JobRequest) -> dict[str, str]:
    """Build the process-local credential environment for a Studio job.

    The persisted OpenAI credential is exported only as OPENAI_API_KEY. Generic
    compatible endpoints use an explicit per-job TUBEVIZ_LLM_API_KEY override;
    OpenAI-specific call sites resolve the saved key when their destination is
    api.openai.com. This keeps secrets out of argv/job logs and avoids sending an
    OpenAI key to arbitrary compatible endpoints.
    """
    env_overrides: dict[str, str] = {}
    settings = load_settings()
    env_overrides["TUBEVIZ_AI_ENABLED"] = "1" if settings.ai_enabled else "0"
    if settings.effective_openai_key():
        env_overrides["OPENAI_API_KEY"] = settings.effective_openai_key()
    if settings.effective_hf_token():
        env_overrides["HF_TOKEN"] = settings.effective_hf_token()
        env_overrides["HUGGING_FACE_HUB_TOKEN"] = settings.effective_hf_token()
    token = (request.hf_token or "").strip()
    if token:
        env_overrides["HF_TOKEN"] = token
        env_overrides["HUGGING_FACE_HUB_TOKEN"] = token
    llm_key = (request.llm_api_key or "").strip()
    if llm_key:
        env_overrides["TUBEVIZ_LLM_API_KEY"] = llm_key
    return env_overrides


def create_gui_app(
    *,
    default_library: str | Path = "./library",
    project_root: str | Path = ".",
) -> FastAPI:
    root = Path(project_root).expanduser().resolve()
    default_library = Path(default_library).expanduser().resolve()
    package_dir = Path(__file__).resolve().parent
    static_dir = package_dir / "static"
    jobs = JobManager(cwd=root)

    app = FastAPI(title="tubeviz studio", version=__version__)

    @app.middleware("http")
    async def studio_no_cache(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "gui.html")

    @app.get("/api/gui/config")
    async def config() -> dict[str, Any]:
        return {
            "studio_version": __version__,
            "project_root": str(root),
            "library": str(default_library),
            "native": native_doctor(),
            "codec": codec_doctor(),
            "huggingface": {
                "token_from_env": bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")),
                "source": "environment" if (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")) else None,
            },
        }

    @app.get("/api/gui/ai-settings")
    async def get_ai_settings() -> dict[str, Any]:
        return load_settings().public_dict()

    @app.post("/api/gui/ai-settings")
    async def update_ai_settings(action: AISettingsAction) -> dict[str, Any]:
        changes = action.model_dump(exclude={"clear_openai_key", "clear_hf_token"})
        result = save_settings(
            changes, clear_openai=action.clear_openai_key, clear_hf=action.clear_hf_token
        )
        return result.public_dict()

    @app.get("/api/gui/library")
    async def library_state(
        library: str = Query(default=str(default_library)),
        status: str | None = None,
        term: str | None = None,
        tag: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        lib = ClipLibrary(library)
        lib.initialize()
        return {
            "stats": lib.stats(),
            "terms": lib.list_terms(),
            "tags": lib.list_tags(),
            "output_selection": {"active": lib.output_selection_count() > 0,
                                 "count": lib.output_selection_count()},
            "clips": lib.list_clips(status=status, term=term, tag=tag,
                                    limit=min(1000, max(1, limit))),
        }

    @app.post("/api/gui/clip/{source_id}/tags")
    async def save_clip_tags(source_id: str, action: ClipTagsAction) -> dict[str, Any]:
        lib = ClipLibrary(action.library)
        lib.initialize()
        try:
            tags = lib.set_clip_tags(action.source, source_id, action.tags)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"source_id": source_id, "tags": tags}

    @app.post("/api/gui/library/output-selection")
    async def update_output_selection(action: OutputSelectionAction) -> dict[str, Any]:
        lib = ClipLibrary(action.library)
        lib.initialize()
        changed = (lib.select_output_by_tag(action.tag, action.selected)
                   if action.tag else lib.set_output_selected(action.clip_ids, action.selected))
        count = lib.output_selection_count()
        return {"changed": changed, "count": count, "active": count > 0}

    @app.post("/api/gui/library/output-selection/clear")
    async def clear_output_selection(action: OutputSelectionAction) -> dict[str, Any]:
        lib = ClipLibrary(action.library)
        lib.initialize()
        changed = lib.clear_output_selection()
        return {"changed": changed, "count": 0, "active": False}

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

    @app.post("/api/gui/clip/{source_id}/trim")
    async def save_clip_trim(source_id: str, action: ClipTrimAction) -> dict[str, Any]:
        lib = ClipLibrary(action.library)
        lib.initialize()
        try:
            return lib.set_clip_trim(
                action.source,
                source_id,
                usable_start=action.usable_start,
                usable_end=action.usable_end,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/gui/clip/{source_id}/trim/clear")
    async def clear_clip_trim(source_id: str, action: ClipTrimAction) -> dict[str, Any]:
        lib = ClipLibrary(action.library)
        lib.initialize()
        try:
            return lib.clear_clip_trim(action.source, source_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

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
        trim_start = float(details.get("usable_start") or 0.0)
        trim_end = details.get("usable_end")
        trim_end_value = float(trim_end) if trim_end is not None else float("inf")
        for scene in details.get("scenes", []):
            # Prefer a thumbnail from a scene that remains selectable after
            # non-destructive trim, rather than showing an excluded title card.
            if float(scene.get("end", 0.0)) <= trim_start:
                continue
            if float(scene.get("start", 0.0)) >= trim_end_value:
                continue
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
        metadata: dict[str, Any] = {}
        effective = request
        if request.kind == "preview":
            # A preview server keeps the timeline in memory. Reusing a fixed
            # port let Studio silently reopen an older server when a newer
            # `tubeviz serve` failed with EADDRINUSE. Always retire Studio's
            # previous preview and launch this selection on a fresh port.
            jobs.cancel_kind("preview")
            options = dict(request.options)
            host = str(options.get("host", "127.0.0.1"))
            port = int(options.get("port") or 0)
            if port <= 0:
                port = _free_tcp_port(host)
            options["port"] = port
            effective = request.model_copy(update={"options": options})
            browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
            metadata = {
                "preview_url": f"http://{browser_host}:{port}/",
                "preview_timeline": str(request.timeline or ""),
                "preview_audio": str(request.audio or ""),
                "preview_library": str(Path(request.library).expanduser()),
            }
        try:
            command = _job_command(effective)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        env_overrides = _job_env_overrides(request)
        return jobs.create(
            request.kind, command, metadata=metadata, env_overrides=env_overrides
        ).payload()

    @app.get("/api/gui/cli-schema")
    async def gui_cli_schema() -> dict[str, Any]:
        return cli_schema()

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
