# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio_ai import top_audio_concepts
from .models import Section, SectionAIDirection, TrackAnalysis
from .settings import resolve_llm_api_key


@dataclass(frozen=True)
class AIDirectorConfig:
    enabled: bool = False
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout: float = 90.0
    cache_dir: str | None = None
    force: bool = False
    semantic_strength: float = 0.75
    reasoning_effort: str = "none"
    max_completion_tokens: int = 8192


_EFFECT_FAMILIES = {"dream", "liquid", "analog", "fracture", "hyper", "prismatic", "cinematic"}

_HUE = {
    "dark": 228.0,
    "euphoric": 315.0,
    "dreamlike": 272.0,
    "tense": 350.0,
    "aggressive": 8.0,
    "serene": 196.0,
    "melancholic": 218.0,
    "mysterious": 260.0,
    "hypnotic": 282.0,
    "futuristic": 188.0,
    "industrial": 205.0,
    "urban_night": 220.0,
    "rave": 302.0,
    "space": 245.0,
    "nature": 128.0,
    "ocean": 192.0,
    "machinery": 28.0,
    "retro_tv": 42.0,
    "surveillance": 104.0,
    "abstract": 280.0,
    "neon": 300.0,
    "warm_amber": 35.0,
    "cold_blue": 208.0,
    "magenta_cyan": 300.0,
    "acid_green": 105.0,
}

_MOTION = {
    "kinetic": .90, "slow_drift": .20, "pulsing": .66, "explosive": .98,
    "flowing": .48, "chaotic": .92, "mechanical": .70, "floating": .22,
    "forward_motion": .78, "swirling": .62, "aggressive": .85,
    "serene": .20, "hypnotic": .42,
}

_COMPLEXITY = {
    "abstract": .80, "fragmented": .95, "chaotic": .92, "industrial": .70,
    "architecture": .60, "nature": .55, "space": .45, "serene": .30,
    "clean_digital": .42, "grainy_analog": .72, "high_contrast": .68,
}

_FAMILY_HINTS = {
    "dreamlike": "dream", "serene": "dream", "floating": "dream",
    "flowing": "liquid", "ocean": "liquid", "swirling": "liquid",
    "retro_tv": "analog", "grainy_analog": "analog", "surveillance": "analog",
    "fragmented": "fracture", "chaotic": "fracture", "aggressive": "fracture",
    "kinetic": "hyper", "explosive": "hyper", "forward_motion": "hyper",
    "neon": "prismatic", "rave": "prismatic", "magenta_cyan": "prismatic",
}


def _weighted_average(scores: dict[str, float], table: dict[str, float], fallback: float) -> float:
    weight = 0.0
    value = 0.0
    for key, target in table.items():
        w = float(scores.get(key, 0.0))
        value += w * target
        weight += w
    return value / weight if weight > 1e-9 else fallback


def _circular_hue(scores: dict[str, float], fallback: float) -> float:
    import math
    x = y = total = 0.0
    for key, hue in _HUE.items():
        w = float(scores.get(key, 0.0))
        if w <= 0:
            continue
        angle = math.radians(hue)
        x += math.cos(angle) * w
        y += math.sin(angle) * w
        total += w
    if total <= 1e-9 or abs(x) + abs(y) < 1e-9:
        return fallback % 360.0
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def semantic_direction(section: Section) -> SectionAIDirection:
    scores = section.audio_semantics
    top = top_audio_concepts(section, 6)
    world = ", ".join(key.replace("_", " ") for key, _ in top[:3])
    motion_style = top[0][0].replace("_", " ") if top else section.vibe
    desired_motion = _weighted_average(scores, _MOTION, .45 + .35 * section.energy)
    desired_complexity = _weighted_average(scores, _COMPLEXITY, .35 + .45 * section.energy)

    family_votes: dict[str, float] = {}
    for key, family in _FAMILY_HINTS.items():
        family_votes[family] = family_votes.get(family, 0.0) + scores.get(key, 0.0)
    effect_family = max(family_votes, key=family_votes.get) if family_votes and max(family_votes.values()) > .015 else None

    edit_density = min(1.0, max(0.0,
        .26 + .36 * section.energy + .18 * section.percussive_ratio
        + .20 * (scores.get("kinetic", 0) + scores.get("chaotic", 0) + scores.get("explosive", 0)) * 3.0
        - .18 * (scores.get("serene", 0) + scores.get("slow_drift", 0)) * 3.0
    ))
    continuity = min(1.0, max(0.0,
        .62 - .30 * section.energy
        + .30 * (scores.get("dreamlike", 0) + scores.get("serene", 0) + scores.get("hypnotic", 0)) * 3.0
        - .24 * (scores.get("fragmented", 0) + scores.get("explosive", 0)) * 3.0
    ))
    target_hue = _circular_hue(scores, 210.0)
    vector_intensity = min(1.6, max(.25, .55 + .55*desired_complexity + .25*section.energy))
    codec_intensity = min(1.5, max(.15, .32 + .65*(scores.get("fragmented", 0)+scores.get("aggressive", 0)+scores.get("chaotic", 0))*3.0))
    palette = top[0][0].replace("_", " ") if top else section.vibe

    return SectionAIDirection(
        visual_world=world,
        motion_style=motion_style,
        palette=palette,
        effect_family=effect_family,
        desired_motion=desired_motion,
        desired_complexity=desired_complexity,
        edit_density=edit_density,
        continuity=continuity,
        target_hue=target_hue,
        vector_intensity=vector_intensity,
        codec_intensity=codec_intensity,
        notes="CLAP semantic director",
    )


def attach_semantic_directions(track: TrackAnalysis) -> TrackAnalysis:
    sections = [
        section.model_copy(update={"ai_direction": semantic_direction(section)})
        if section.audio_semantics else section
        for section in track.sections
    ]
    return track.model_copy(update={"sections": sections})


def _cache_root(cfg: AIDirectorConfig) -> Path:
    if cfg.cache_dir:
        return Path(cfg.cache_dir).expanduser().resolve()
    root = os.environ.get("XDG_CACHE_HOME")
    if root:
        return Path(root).expanduser().resolve() / "tubeviz" / "ai-director"
    return Path.home() / ".cache" / "tubeviz" / "ai-director"


def _track_summary(track: TrackAnalysis) -> list[dict[str, Any]]:
    out = []
    for section in track.sections:
        out.append({
            "index": section.index,
            "start": round(section.start, 3),
            "end": round(section.end, 3),
            "label": section.label,
            "vibe": section.vibe,
            "energy": round(section.energy, 3),
            "tempo": round(section.local_tempo_bpm, 2),
            "brightness": round(section.brightness, 3),
            "percussive": round(section.percussive_ratio, 3),
            "top_audio_concepts": [
                [key, round(value, 4)] for key, value in top_audio_concepts(section, 7)
            ],
            "semantic_confidence": round(section.audio_semantic_confidence, 3),
            "trajectory": section.trajectory.model_dump(mode="json") if section.trajectory else None,
            "baseline": section.ai_direction.model_dump(mode="json") if section.ai_direction else None,
        })
    return out


def _director_prompt(track: TrackAnalysis, resource_manifest: dict[str, Any] | None = None) -> str:
    schema = {
        "sections": [{
            "index": 0,
            "visual_world": "short thematic visual-world description",
            "motion_style": "short motion/camera description",
            "palette": "palette description",
            "effect_family": "dream|liquid|analog|fracture|hyper|prismatic|cinematic",
            "desired_motion": 0.5,
            "desired_complexity": 0.5,
            "edit_density": 0.5,
            "continuity": 0.5,
            "target_hue": 210.0,
            "vector_intensity": 1.0,
            "codec_intensity": 0.5,
            "creative_trajectory": {
                "abstraction": [0.15, 0.55],
                "camera_energy": [0.25, 0.75],
                "temporal": [0.10, 0.45],
                "feedback": [0.05, 0.30],
                "depth": [0.20, 0.50],
                "flow": [0.10, 0.60],
                "palette": [0.25, 0.70]
            },
            "notes": "brief reasoning",
        }]
    }
    return (
        "You are the high-level music-video director for tubeviz. Plan the visual arc of the whole track using the ACTUAL library strengths and renderer capabilities supplied below. "
        "Do NOT select filenames, clip IDs, scene IDs, or exact cut times in this first pass. A later bounded edit-consultant pass will choose only among valid retrieved scenes, and the deterministic optimizer owns hard timing. "
        "Explicitly exploit resources that exist and avoid relying on visual worlds/effects that the resource manifest says are absent or scarce. "
        "Use callbacks and controlled evolution: avoid changing visual worlds arbitrarily every section. "
        "Use the supplied trajectory fields (build/drop/release probability, tension slope, anticipation, withholding) to create coherent escalation and payoff. Reserve the strongest contrast/effects for builds, drops, mutations and payoffs; keep pre-drop withholding when it creates useful contrast. Return JSON only.\n\n"
        f"Required schema example:\n{json.dumps(schema, indent=2)}\n\n"
        f"Track analysis:\n{json.dumps(_track_summary(track), indent=2)}\n\n"
        f"Actual tubeviz resources available for this production:\n{json.dumps(resource_manifest or {}, indent=2)}"
    )


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def _is_native_openai(base_url: str) -> bool:
    try:
        return (urlsplit(base_url).hostname or "").lower() == "api.openai.com"
    except ValueError:
        return False


def _request_payload(track: TrackAnalysis, cfg: AIDirectorConfig, resource_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {
                "role": "system",
                "content": "Return strict JSON only. You direct themes and intensity; you never choose media files.",
            },
            {"role": "user", "content": _director_prompt(track, resource_manifest)},
        ],
    }

    if _is_native_openai(cfg.base_url or ""):
        # GPT-5.6 reasoning tokens and visible output share the Chat Completions
        # completion budget. The director needs structured creative planning, not
        # deep hidden reasoning, so disable reasoning and leave enough room for a
        # whole-song JSON plan. Do not send legacy sampling parameters here.
        payload.update({
            "reasoning_effort": cfg.reasoning_effort,
            "max_completion_tokens": max(512, int(cfg.max_completion_tokens)),
            "response_format": {"type": "json_object"},
        })
    else:
        # Keep the existing generic OpenAI-compatible/vLLM request shape.
        payload["temperature"] = 0.35

    return payload


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("AI director response did not contain a JSON object")
    return json.loads(text[start:end+1])


def _call_llm(track: TrackAnalysis, cfg: AIDirectorConfig, resource_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    if not cfg.base_url or not cfg.model:
        raise RuntimeError("--ai-director requires --ai-director-base-url and --ai-director-model")
    payload = _request_payload(track, cfg, resource_manifest)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = resolve_llm_api_key(cfg.base_url, cfg.api_key)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(_endpoint(cfg.base_url), data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            response_body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            response_body = ""
        request_id = exc.headers.get("x-request-id") if exc.headers else None
        detail = f"HTTP {exc.code} {exc.reason}"
        if request_id:
            detail += f"; x-request-id={request_id}"
        if response_body:
            try:
                parsed = json.loads(response_body)
                response_body = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                pass
            detail += f"; response={response_body}"
        raise RuntimeError(f"AI director request failed: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI director request failed: {exc}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("AI director response has no choices")

    choice = choices[0]
    message = choice.get("message") or {}
    content = str(message.get("content") or "")
    if not content.strip():
        usage = data.get("usage") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        raise RuntimeError(
            "AI director returned no content "
            f"(finish_reason={choice.get('finish_reason')!r}, "
            f"completion_tokens={usage.get('completion_tokens')!r}, "
            f"reasoning_tokens={completion_details.get('reasoning_tokens')!r}). "
            "The completion budget may have been exhausted before visible JSON was emitted."
        )
    return _extract_json(content)


def _blend(base: SectionAIDirection, proposed: SectionAIDirection, strength: float) -> SectionAIDirection:
    s = min(1.0, max(0.0, strength))
    def mix(a: float, b: float) -> float:
        return float(a * (1-s) + b * s)
    return base.model_copy(update={
        "visual_world": proposed.visual_world or base.visual_world,
        "motion_style": proposed.motion_style or base.motion_style,
        "palette": proposed.palette or base.palette,
        "effect_family": proposed.effect_family or base.effect_family,
        "desired_motion": mix(base.desired_motion, proposed.desired_motion),
        "desired_complexity": mix(base.desired_complexity, proposed.desired_complexity),
        "edit_density": mix(base.edit_density, proposed.edit_density),
        "continuity": mix(base.continuity, proposed.continuity),
        "target_hue": proposed.target_hue if proposed.target_hue is not None else base.target_hue,
        "vector_intensity": mix(base.vector_intensity, proposed.vector_intensity),
        "codec_intensity": mix(base.codec_intensity, proposed.codec_intensity),
        "creative_trajectory": proposed.creative_trajectory or base.creative_trajectory,
        "notes": proposed.notes or base.notes,
    })


def attach_llm_directions(track: TrackAnalysis, *, config: AIDirectorConfig, resource_manifest: dict[str, Any] | None = None, progress=print) -> TrackAnalysis:
    if not config.enabled:
        return track
    root = _cache_root(config)
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps({
        "model": config.model,
        "base_url": config.base_url,
        "sections": _track_summary(track),
        "resources": resource_manifest or {},
    }, sort_keys=True).encode()).hexdigest()
    cache = root / f"{digest}.json"
    if cache.is_file() and not config.force:
        result = json.loads(cache.read_text())
        progress("AI director: loaded cached whole-song plan")
    else:
        progress(f"AI director: requesting whole-song plan from {config.model}")
        result = _call_llm(track, config, resource_manifest)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2, sort_keys=True))
        tmp.replace(cache)

    by_index: dict[int, dict[str, Any]] = {}
    for item in result.get("sections", []):
        if isinstance(item, dict) and "index" in item:
            by_index[int(item["index"])] = item

    sections: list[Section] = []
    for section in track.sections:
        raw = by_index.get(section.index)
        if not raw:
            sections.append(section)
            continue
        base = section.ai_direction or semantic_direction(section)
        data = dict(raw)
        data.pop("index", None)
        if data.get("effect_family") not in _EFFECT_FAMILIES:
            data["effect_family"] = base.effect_family
        # Drop unknown keys rather than letting a chat model break timeline validation.
        allowed = set(SectionAIDirection.model_fields)
        data = {key: value for key, value in data.items() if key in allowed}
        try:
            proposed = SectionAIDirection.model_validate({**base.model_dump(), **data})
        except Exception:
            proposed = base
        # High CLAP uncertainty reduces how strongly the language model may pull
        # choreography away from the deterministic baseline.
        confidence = section.audio_semantic_confidence
        strength = config.semantic_strength * (.35 + .65*confidence)
        sections.append(section.model_copy(update={"ai_direction": _blend(base, proposed, strength)}))
    return track.model_copy(update={"sections": sections})
