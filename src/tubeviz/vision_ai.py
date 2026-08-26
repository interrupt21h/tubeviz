# SPDX-License-Identifier: Apache-2.0
"""Scene-aware video description through the OpenAI Responses API."""
from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .library import ClipLibrary
from .settings import UserSettings, load_settings

PROMPT_VERSION = "tubeviz-storyboard-v1"


@dataclass(frozen=True)
class VisionSummary:
    considered: int = 0
    enhanced: int = 0
    cached: int = 0
    failed: int = 0


def _output_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return str(response["output_text"])
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    raise ValueError("OpenAI response contained no output text")


def _data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _sample_scenes(details: dict[str, Any], library: ClipLibrary, maximum: int) -> list[tuple[dict[str, Any], Path]]:
    available = []
    for scene in details.get("scenes", []):
        rel = scene.get("thumbnail_path")
        path = library.root / rel if rel else None
        if path and path.is_file():
            available.append((scene, path))
    if len(available) <= maximum:
        return available
    if maximum <= 1:
        return [available[len(available) // 2]]
    indices = sorted({round(i * (len(available) - 1) / (maximum - 1)) for i in range(maximum)})
    return [available[index] for index in indices]


def _request_analysis(details: dict[str, Any], samples: list[tuple[dict[str, Any], Path]], settings: UserSettings) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": (
        "Analyze this complete video storyboard for music-video editing. Describe what is visibly present, "
        "not what the title implies. Use every sampled frame. Return JSON with: summary (string), subjects, "
        "actions, settings, camera, palette, lighting, textures, moods, semantic_tags (arrays of strings); "
        "editing_utility containing energy, motion, complexity, continuity, build_fit, drop_fit, ambient_fit "
        "(numbers 0..1); risks (array); and scenes, one per supplied scene, containing scene_index, description, "
        "semantic_tags, energy, motion, complexity, build_fit, drop_fit, ambient_fit. Preserve scene_index values."
    )}]
    for scene, path in samples:
        content.append({"type": "input_text", "text": f"Scene {scene['index']} at {float(scene['start']):.2f}s:"})
        content.append({"type": "input_image", "image_url": _data_url(path), "detail": settings.vision_detail})
    body = {
        "model": settings.openai_model,
        "input": [{"role": "user", "content": content}],
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": 5000,
    }
    request = urllib.request.Request(
        settings.openai_base_url.rstrip("/") + "/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {settings.effective_openai_key()}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.vision_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
    result = json.loads(_output_text(payload))
    if not isinstance(result, dict):
        raise ValueError("OpenAI analysis was not a JSON object")
    return result


def enhance_library(
    library: ClipLibrary, *, settings: UserSettings | None = None, clip_id: int | None = None,
    limit: int = 0, force: bool = False, progress: Callable[[str], None] = print,
) -> VisionSummary:
    cfg = settings or load_settings()
    if not cfg.ai_enabled or not cfg.vision_enabled:
        raise RuntimeError("AI video descriptions are disabled in Tubeviz AI Settings")
    if not cfg.effective_openai_key():
        raise RuntimeError("No OpenAI API key is configured in Tubeviz AI Settings or OPENAI_API_KEY")
    library.initialize()
    clips = library.list_clips(status="ready", limit=100000)
    if clip_id is not None:
        clips = [clip for clip in clips if int(clip["id"]) == clip_id]
    if limit > 0:
        clips = clips[:limit]
    counts = {"considered": len(clips), "enhanced": 0, "cached": 0, "failed": 0}
    for ordinal, clip in enumerate(clips, 1):
        details = library.clip_details(str(clip["source"]), str(clip["source_id"])) or {}
        samples = _sample_scenes(details, library, max(2, cfg.vision_max_frames))
        if not samples:
            progress(f"AI describe [{ordinal}/{len(clips)}] skipped {clip['source_id']}: no scene thumbnails")
            counts["failed"] += 1
            continue
        fingerprint = hashlib.sha256((str(clip.get("normalized_sha256") or "") + cfg.openai_model + cfg.vision_detail + PROMPT_VERSION + ",".join(str(s[0]["index"]) for s in samples)).encode()).hexdigest()
        if not force and library.clip_ai_cache_key(int(clip["id"])) == fingerprint:
            progress(f"AI describe [{ordinal}/{len(clips)}] cached {clip['source_id']}")
            counts["cached"] += 1
            continue
        progress(f"AI describe [{ordinal}/{len(clips)}] sending {len(samples)} frames for {clip['source_id']}")
        try:
            result = _request_analysis(details, samples, cfg)
            library.store_clip_ai_description(int(clip["id"]), result, provider="openai", model=cfg.openai_model, prompt_version=PROMPT_VERSION, cache_key=fingerprint)
            counts["enhanced"] += 1
            progress(f"AI describe [{ordinal}/{len(clips)}] stored {clip['source_id']}")
        except Exception as exc:
            counts["failed"] += 1
            progress(f"AI describe [{ordinal}/{len(clips)}] failed {clip['source_id']}: {exc}")
    return VisionSummary(**counts)
