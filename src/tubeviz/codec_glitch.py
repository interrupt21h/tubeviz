# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .models import CodecEffect, CodecMaterialization, DirectedTimeline, SceneSelection


class CodecGlitchError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodecGlitchConfig:
    ffedit: str = "ffedit"
    ffmpeg: str = "ffmpeg"
    ffgac: str | None = None
    working_codec: str = "mpeg4"
    qscale: int = 3
    gop: int = 18
    fps: float = 30.0
    width: int = 1280
    height: int = 720
    threads: int = 0
    output_crf: int = 18
    output_preset: str = "fast"
    cache_namespace: str = "ffglitch-v1"


_FFGLITCH_SCRIPT = r'''// tubeviz deterministic FFglitch motion-vector director.
let frame_num = 0;
let params = {};

export function setup(args) {
  if (!args.features.includes("mv")) args.features.push("mv");
  params = args.params || {};
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function hash01(n) {
  let x = (n | 0) ^ ((params.seed || 1) | 0);
  x ^= x << 13; x ^= x >>> 17; x ^= x << 5;
  return (x >>> 0) / 4294967296.0;
}
function smoothstep(a, b, x) {
  if (a === b) return x >= b ? 1 : 0;
  const t = clamp((x-a)/(b-a), 0, 1);
  return t*t*(3-2*t);
}
function envelope(effect, p) {
  const a = effect.start ?? 0.0, b = effect.end ?? 1.0;
  if (p < a || p > b) return 0.0;
  const local = (p-a) / Math.max(1e-9, b-a);
  const attack = effect.attack ?? 0.12, release = effect.release ?? 0.18;
  const ai = attack > 0 ? smoothstep(0, attack, local) : 1;
  const ro = release > 0 ? 1-smoothstep(1-release, 1, local) : 1;
  let shape = Math.min(ai, ro);
  if (effect.pulse) shape *= 0.45 + 0.55*Math.abs(Math.sin(local*Math.PI*(effect.pulse||1)));
  return clamp((effect.amount ?? 0) * shape, 0, 1.5);
}
function eachMV(tree, fn) {
  if (!tree) return;
  const height = tree.length || 1;
  for (let y=0; y<height; y++) {
    const row = tree[y]; if (!row) continue;
    const width = row.length || 1;
    for (let x=0; x<width; x++) {
      const cell = row[x]; if (!cell) continue;
      // MPEG-4 may encode four 8x8 MVs for one macroblock. Handle both the
      // ordinary [h,v] form and the four-vector nested form documented by
      // FFglitch without assuming every cell has the same representation.
      if (typeof cell[0] === "number" && typeof cell[1] === "number") {
        fn(cell, x, y, width, height);
      } else if (cell.length) {
        for (let k=0; k<cell.length; k++) {
          const v = cell[k];
          if (v && typeof v[0] === "number" && typeof v[1] === "number")
            fn(v, x + (k&1)*0.35, y + ((k>>1)&1)*0.35, width, height);
        }
      }
    }
  }
}
function applyOne(v, x, y, w, h, effect, amount, p) {
  const nx = w > 1 ? x/(w-1)-0.5 : 0;
  const ny = h > 1 ? y/(h-1)-0.5 : 0;
  const seed = (effect.seed || params.seed || 1) + frame_num*104729 + y*257 + x;
  const kind = effect.kind;
  if (kind === "mv_shear") {
    v[0] += Math.round(ny * amount * 22);
  } else if (kind === "mv_explode") {
    v[0] += Math.round(nx * amount * 28);
    v[1] += Math.round(ny * amount * 28);
  } else if (kind === "mv_implode") {
    v[0] -= Math.round(nx * amount * 24);
    v[1] -= Math.round(ny * amount * 24);
  } else if (kind === "mv_spiral") {
    const r = Math.sqrt(nx*nx + ny*ny) + 0.04;
    v[0] += Math.round((-ny/r) * amount * 16);
    v[1] += Math.round(( nx/r) * amount * 16);
  } else if (kind === "mv_jitter") {
    v[0] += Math.round((hash01(seed)-0.5) * amount * 22);
    v[1] += Math.round((hash01(seed+13)-0.5) * amount * 22);
  } else if (kind === "mv_wave") {
    v[0] += Math.round(Math.sin(y*.55 + frame_num*.23) * amount * 12);
    v[1] += Math.round(Math.cos(x*.41 + frame_num*.17) * amount * 7);
  } else if (kind === "mv_drift") {
    const angle = effect.angle ?? (params.angle ?? 0);
    v[0] += Math.round(Math.cos(angle) * amount * 14);
    v[1] += Math.round(Math.sin(angle) * amount * 14);
  } else if (kind === "mv_freeze") {
    const keep = 1 - clamp(amount, 0, 1);
    v[0] = Math.round(v[0] * keep); v[1] = Math.round(v[1] * keep);
  } else if (kind === "mv_feedback" || kind === "datamosh") {
    const gain = 1 + amount * (kind === "datamosh" ? 5.2 : 3.1);
    v[0] = Math.round(v[0] * gain); v[1] = Math.round(v[1] * gain);
  } else if (kind === "mv_invert") {
    const mix = clamp(amount, 0, 1);
    v[0] = Math.round(v[0] * (1-2*mix)); v[1] = Math.round(v[1] * (1-2*mix));
  } else if (kind === "mv_radial_wave") {
    const r = Math.sqrt(nx*nx + ny*ny);
    const q = Math.sin(r*24 - frame_num*.32) * amount * 12;
    if (r > 1e-4) { v[0] += Math.round(nx/r*q); v[1] += Math.round(ny/r*q); }
  }
  const limit = effect.limit ?? 96;
  v[0] = clamp(Math.round(v[0]), -limit, limit);
  v[1] = clamp(Math.round(v[1]), -limit, limit);
}

export function glitch_frame(frame, stream) {
  const total = Math.max(1, params.frames || 1);
  const p = clamp(frame_num / Math.max(1, total-1), 0, 1);
  const effects = params.effects || [];
  if (frame.mv) frame.mv.overflow = "truncate";
  for (const dir of [frame.mv?.forward, frame.mv?.backward]) {
    if (!dir) continue;
    eachMV(dir, (v,x,y,w,h) => {
      for (const effect of effects) {
        const a = envelope(effect, p);
        if (a > 0.0001) applyOne(v,x,y,w,h,effect,a,p);
      }
    });
  }
  frame_num++;
}
'''


def _run(command: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise CodecGlitchError(f"executable not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CodecGlitchError(f"command timed out: {' '.join(command[:4])} ...") from exc


def _version(binary: str) -> str | None:
    path = shutil.which(binary) if os.sep not in binary else binary
    if not path or not Path(path).exists():
        return None
    for args in ([path, "-version"], [path, "--version"], [path, "-h"]):
        result = _run(list(args), timeout=5)
        text = (result.stdout + "\n" + result.stderr).strip()
        if text:
            return text.splitlines()[0][:240]
    return str(path)


def codec_doctor(config: CodecGlitchConfig | None = None) -> dict[str, Any]:
    cfg = config or CodecGlitchConfig()
    ffedit_path = shutil.which(cfg.ffedit) if os.sep not in cfg.ffedit else cfg.ffedit
    ffmpeg_path = shutil.which(cfg.ffmpeg) if os.sep not in cfg.ffmpeg else cfg.ffmpeg
    ffgac_name = cfg.ffgac or "ffgac"
    ffgac_path = shutil.which(ffgac_name) if os.sep not in ffgac_name else ffgac_name
    return {
        "available": bool(ffedit_path and ffmpeg_path),
        "ffedit": str(ffedit_path) if ffedit_path else None,
        "ffedit_version": _version(cfg.ffedit) if ffedit_path else None,
        "ffmpeg": str(ffmpeg_path) if ffmpeg_path else None,
        "ffmpeg_version": _version(cfg.ffmpeg) if ffmpeg_path else None,
        "ffgac": str(ffgac_path) if ffgac_path and Path(ffgac_path).exists() else None,
        "ffgac_version": _version(ffgac_name) if ffgac_path and Path(ffgac_path).exists() else None,
        "working_codec": cfg.working_codec,
        "note": "tubeviz uses controlled MPEG-4 Part 2 AVI intermediates for ffedit motion-vector transplication",
    }


def _safe_media(library_root: Path, media_file: str, media_url: str | None = None) -> Path:
    raw = Path(media_file).expanduser()
    if raw.is_absolute() and raw.is_file():
        return raw.resolve()
    candidates: list[Path] = []
    if media_url:
        url = media_url.split("?", 1)[0]
        if url.startswith("/transforms/"):
            candidates.append(library_root / "transforms" / url.removeprefix("/transforms/"))
        elif url.startswith("/codec-glitch/"):
            candidates.append(library_root / "codec-glitch" / url.removeprefix("/codec-glitch/"))
        elif url.startswith("/media/"):
            candidates.append(library_root / "normalized" / url.removeprefix("/media/"))
    if raw.parts and raw.parts[0] in {"normalized", "transforms", "codec-glitch"}:
        candidates.append(library_root / raw)
    candidates += [library_root / "normalized" / raw, library_root / "transforms" / raw, library_root / raw]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise CodecGlitchError(f"source media not found for codec glitch: {media_file}")


def _effect_payload(effects: Iterable[CodecEffect], *, frames: int, seed: int) -> dict[str, Any]:
    return {
        "frames": max(1, int(frames)),
        "seed": int(seed),
        "effects": [effect.model_dump(mode="json", exclude={"materialized"}) for effect in effects],
    }


def _cache_key(selection: SceneSelection, effects: list[CodecEffect], cfg: CodecGlitchConfig, source: Path) -> str:
    payload = {
        "namespace": cfg.cache_namespace,
        "source_id": selection.source_id,
        "scene_id": selection.scene_id,
        "start": round(selection.start, 6),
        "end": round(selection.end, 6),
        "effects": [e.model_dump(mode="json", exclude={"materialized"}) for e in effects],
        "working": [cfg.working_codec, cfg.qscale, cfg.gop, cfg.fps, cfg.width, cfg.height],
        "output": [cfg.output_crf, cfg.output_preset],
        "source": [str(source), source.stat().st_size, source.stat().st_mtime_ns],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]


def _prepare_working_clip(
    source: Path, selection: SceneSelection, output: Path, cfg: CodecGlitchConfig
) -> None:
    duration = max(0.08, selection.end - selection.start)
    command = [
        cfg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{selection.start:.6f}", "-t", f"{duration:.6f}", "-i", str(source),
        "-an", "-vf", f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=decrease,pad={cfg.width}:{cfg.height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-r", f"{cfg.fps:g}", "-c:v", cfg.working_codec,
        "-q:v", str(cfg.qscale), "-g", str(cfg.gop), "-bf", "0",
        "-pix_fmt", "yuv420p", "-f", "avi", str(output),
    ]
    result = _run(command)
    if result.returncode:
        raise CodecGlitchError(f"FFglitch preparation encode failed: {result.stderr.strip()}")


def _transplicate(working: Path, glitched: Path, effects: list[CodecEffect], cfg: CodecGlitchConfig, *, frames: int, seed: int, workdir: Path) -> None:
    script = workdir / "tubeviz_ffglitch.js"
    script.write_text(_FFGLITCH_SCRIPT)
    params = json.dumps(_effect_payload(effects, frames=frames, seed=seed), separators=(",", ":"))
    command = [cfg.ffedit, "-y", "-i", str(working), "-f", "mv", "-s", str(script), "-sp", params, "-o", str(glitched)]
    if cfg.threads > 0:
        command += ["-threads", str(cfg.threads)]
    result = _run(command)
    if result.returncode:
        raise CodecGlitchError(f"ffedit transplication failed: {result.stderr.strip() or result.stdout.strip()}")


def _finalize(glitched: Path, output: Path, cfg: CodecGlitchConfig) -> None:
    command = [
        cfg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(glitched),
        "-an", "-c:v", "libx264", "-preset", cfg.output_preset, "-crf", str(cfg.output_crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ]
    result = _run(command)
    if result.returncode:
        raise CodecGlitchError(f"FFglitch output conversion failed: {result.stderr.strip()}")


def materialize_codec_selection(
    selection: SceneSelection,
    *,
    library_root: str | Path,
    config: CodecGlitchConfig | None = None,
    force: bool = False,
) -> SceneSelection:
    cfg = config or CodecGlitchConfig()
    effects = [effect for effect in selection.direction.codec_effects if effect.amount > 0.001]
    if not effects:
        return selection
    if selection.codec_materialization.materialized and not force:
        return selection
    doctor = codec_doctor(cfg)
    if not doctor["available"]:
        raise CodecGlitchError("FFglitch is unavailable; install ffedit 0.10.2+ and ensure ffedit/ffmpeg are on PATH")
    root = Path(library_root).expanduser().resolve()
    materialization = selection.codec_materialization
    source_media_file = materialization.original_media_file if materialization.materialized and materialization.original_media_file else selection.media_file
    source_media_url = materialization.original_media_url if materialization.materialized and materialization.original_media_url else selection.media_url
    source_start = materialization.original_start if materialization.materialized and materialization.original_start is not None else selection.start
    source_end = materialization.original_end if materialization.materialized and materialization.original_end is not None else selection.end
    source_selection = selection.model_copy(update={
        "media_file": source_media_file, "media_url": source_media_url,
        "start": source_start, "end": source_end,
        "duration": max(.05, source_end-source_start),
    })
    source = _safe_media(root, source_media_file, source_media_url)
    cache = root / "codec-glitch"
    cache.mkdir(parents=True, exist_ok=True)
    key = _cache_key(source_selection, effects, cfg, source)
    output = cache / f"{key}.mp4"
    duration = max(0.08, selection.end - selection.start)
    frames = max(2, int(math.ceil(duration * cfg.fps)))
    seed = int(hashlib.sha256(f"{selection.scene_id}:{selection.time}:{key}".encode()).hexdigest()[:8], 16)
    if force or not output.is_file():
        with tempfile.TemporaryDirectory(prefix="tubeviz-ffglitch-") as tmp:
            tmpdir = Path(tmp)
            working = tmpdir / "working.avi"
            glitched = tmpdir / "glitched.avi"
            _prepare_working_clip(source, source_selection, working, cfg)
            _transplicate(working, glitched, effects, cfg, frames=frames, seed=seed, workdir=tmpdir)
            partial = cache / f".{key}.partial.mp4"
            try:
                _finalize(glitched, partial, cfg)
                os.replace(partial, output)
            finally:
                partial.unlink(missing_ok=True)
        sidecar = cache / f"{key}.json"
        sidecar.write_text(json.dumps({
            "cache_key": key, "source": str(source),
            "source_size": source.stat().st_size, "start": source_selection.start,
            "end": source_selection.end, "effects": [e.model_dump(mode="json") for e in effects],
            "ffedit_version": doctor.get("ffedit_version"),
            "working": {"codec": cfg.working_codec, "qscale": cfg.qscale, "gop": cfg.gop, "fps": cfg.fps, "width": cfg.width, "height": cfg.height},
        }, indent=2))
    mat = CodecMaterialization(
        materialized=True,
        cache_key=key,
        original_media_file=source_selection.media_file,
        original_media_url=source_selection.media_url,
        original_start=source_selection.start,
        original_end=source_selection.end,
        media_file=output.name,
        media_url=f"/codec-glitch/{output.name}",
        ffedit_version=str(doctor.get("ffedit_version") or "unknown"),
    )
    direction = selection.direction.model_copy(update={
        "codec_effects": [e.model_copy(update={"materialized": True}) for e in effects]
    })
    return selection.model_copy(update={
        "media_file": output.name,
        "media_url": f"/codec-glitch/{output.name}",
        "start": 0.0,
        "end": duration,
        "duration": duration,
        "direction": direction,
        "codec_materialization": mat,
    })


def materialize_codec_timeline(
    timeline: DirectedTimeline,
    *,
    library_root: str | Path,
    config: CodecGlitchConfig | None = None,
    force: bool = False,
    progress: Callable[[str], None] = print,
) -> DirectedTimeline:
    cfg = config or CodecGlitchConfig()
    updated: list[SceneSelection] = []
    total = sum(bool(s.direction.codec_effects) for s in timeline.scene_plan)
    done = 0
    for selection in timeline.scene_plan:
        if selection.direction.codec_effects:
            done += 1
            progress(f"codec-glitch {done}/{total}: {selection.source_id} shot@{selection.time:.2f}s")
            updated.append(materialize_codec_selection(selection, library_root=library_root, config=cfg, force=force))
        else:
            updated.append(selection)
    by_key = {(s.section_index, round(float(s.time), 6)): s for s in updated}
    cues = []
    for cue in timeline.cues:
        if cue.action in {"play_scene", "crossfade_scene"}:
            key = (cue.parameters.get("section_index"), round(float(cue.time), 6))
            replacement = by_key.get(key)
            if replacement is not None:
                cue = cue.model_copy(update={"parameters": replacement.model_dump(mode="json")})
        cues.append(cue)
    return timeline.model_copy(update={"scene_plan": updated, "cues": cues})


def export_codec_motion(
    media: str | Path,
    *,
    start: float,
    end: float,
    config: CodecGlitchConfig | None = None,
) -> dict[str, Any]:
    """Extract codec MV statistics using ffedit's documented JSON export mode."""
    cfg = config or CodecGlitchConfig(width=320, height=180, fps=12, qscale=4, gop=18)
    source = Path(media).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="tubeviz-codec-motion-") as tmp:
        tmpdir = Path(tmp)
        dummy = SceneSelection.model_construct(start=start, end=end)
        working = tmpdir / "motion.avi"
        _prepare_working_clip(source, dummy, working, cfg)  # type: ignore[arg-type]
        json_path = tmpdir / "mv.json"
        result = _run([cfg.ffedit, "-i", str(working), "-f", "mv", "-e", str(json_path)])
        if result.returncode or not json_path.is_file():
            raise CodecGlitchError(f"ffedit motion export failed: {result.stderr.strip()}")
        payload = json.loads(json_path.read_text())
    vectors_per_frame: list[list[tuple[float, float]]] = []
    for stream in payload.get("streams", []):
        for frame in stream.get("frames", []):
            vectors: list[tuple[float, float]] = []
            mv = frame.get("mv") or {}
            def collect(node) -> None:
                if node is None:
                    return
                if isinstance(node, list):
                    if (len(node) >= 2 and isinstance(node[0], (int, float))
                            and isinstance(node[1], (int, float))):
                        vectors.append((float(node[0]), float(node[1])))
                        return
                    for child in node:
                        collect(child)
            for direction in (mv.get("forward"), mv.get("backward")):
                collect(direction)
            vectors_per_frame.append(vectors)
    mags, xs, ys = [], [], []
    frame_mags: list[float] = []
    for vectors in vectors_per_frame:
        if vectors:
            fm = sum(math.hypot(x, y) for x, y in vectors) / len(vectors)
            frame_mags.append(fm)
            for x, y in vectors:
                xs.append(x); ys.append(y); mags.append(math.hypot(x, y))
        else:
            frame_mags.append(0.0)
    mean_mag = sum(mags) / len(mags) if mags else 0.0
    peak = max(frame_mags, default=0.0)
    norm = max(1.0, peak)
    accents = []
    for i, value in enumerate(frame_mags):
        left = frame_mags[i-1] if i else 0.0
        right = frame_mags[i+1] if i+1 < len(frame_mags) else 0.0
        if value > mean_mag * 1.35 and value >= left and value >= right:
            accents.append({"time": i / max(1e-6, cfg.fps), "strength": min(1.0, value / norm)})
    return {
        "codec_motion": min(1.0, mean_mag / 12.0),
        "codec_motion_peak": min(1.0, peak / 24.0),
        "codec_motion_direction_x": max(-1.0, min(1.0, (sum(xs)/len(xs))/12.0 if xs else 0.0)),
        "codec_motion_direction_y": max(-1.0, min(1.0, (sum(ys)/len(ys))/12.0 if ys else 0.0)),
        "codec_motion_accents": accents[:32],
        "codec_motion_frames": len(frame_mags),
    }


def index_codec_motion_features(
    library,
    *,
    clip_id: int | None = None,
    force: bool = False,
    config: CodecGlitchConfig | None = None,
    progress: Callable[[str], None] = print,
) -> int:
    """Backfill FFglitch motion-vector statistics into scene visual fingerprints."""
    cfg = config or CodecGlitchConfig(width=320, height=180, fps=12.0, qscale=4, gop=18)
    if not codec_doctor(cfg)["available"]:
        raise CodecGlitchError("ffedit/ffmpeg are required for codec-motion indexing")
    candidates = library.scene_candidates(clip_id=clip_id)
    indexed = 0
    for candidate in candidates:
        features = dict(candidate.visual_features or {})
        if not force and "codec_motion" in features:
            continue
        media = library.root / candidate.normalized_path
        if not media.is_file():
            continue
        try:
            codec = export_codec_motion(
                media,
                start=candidate.start_time,
                end=candidate.end_time,
                config=cfg,
            )
        except Exception as exc:
            progress(f"  codec-motion warning scene={candidate.scene_id}: {exc}")
            continue
        features.update(codec)
        features.setdefault("version", 1)
        library.store_scene_visual_features(candidate.scene_id, features)
        indexed += 1
        if indexed % 10 == 0:
            progress(f"  codec motion: {indexed} scenes")
    progress(f"Codec-motion index complete: {indexed} scenes")
    return indexed
