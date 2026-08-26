# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .ai_resources import EFFECT_FAMILIES, HERO_EFFECTS, compact_candidate
from .library import SceneCandidate
from .models import Section
from .settings import resolve_llm_api_key


@dataclass(frozen=True)
class AIEditConsultantConfig:
    enabled: bool = False
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout: float = 90.0
    cache_dir: str | None = None
    force: bool = False
    candidate_count: int = 12
    weight: float = 0.85
    reasoning_effort: str = "none"
    max_completion_tokens: int = 4096


def _cache_root(cfg: AIEditConsultantConfig) -> Path:
    if cfg.cache_dir:
        return Path(cfg.cache_dir).expanduser().resolve() / "edit-consultant"
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root).expanduser().resolve() if root else Path.home() / ".cache"
    return base / "tubeviz" / "ai-director" / "edit-consultant"


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def _is_native_openai(base_url: str) -> bool:
    try:
        return (urlsplit(base_url).hostname or "").lower() == "api.openai.com"
    except ValueError:
        return False


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        text = "\n".join(lines)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError("AI edit consultant response did not contain JSON")
    value = json.loads(text[a:b + 1])
    if not isinstance(value, dict):
        raise ValueError("AI edit consultant response was not an object")
    return value


def _prompt(section: Section, windows: list[tuple[float, float]], candidates: list[tuple[SceneCandidate, float]], previous: SceneCandidate | None) -> str:
    payload = {
        "section": {
            "index": section.index,
            "start": round(section.start, 3), "end": round(section.end, 3),
            "label": section.label, "vibe": section.vibe, "energy": round(section.energy, 3),
            "tempo": round(section.local_tempo_bpm, 2),
            "trajectory": section.trajectory.model_dump(mode="json") if section.trajectory else None,
            "director": section.ai_direction.model_dump(mode="json") if section.ai_direction else None,
        },
        "previous_scene": compact_candidate(previous) if previous else None,
        "shots": [
            {"shot_index": i, "start": round(a, 3), "end": round(b, 3), "duration": round(b-a, 3)}
            for i, (a, b) in enumerate(windows)
        ],
        "bounded_candidates": [compact_candidate(c, score=s) for c, s in candidates],
        "available_treatments": {"effect_families": EFFECT_FAMILIES, "hero_effects": HERO_EFFECTS},
    }
    schema = {
        "shots": [{
            "shot_index": 0,
            "preferred_scene_ids": [123, 456, 789],
            "effect_family": "cinematic",
            "hero_kind": None,
            "reason": "brief editorial reason grounded in the supplied candidates and song arc"
        }]
    }
    return (
        "You are tubeviz's bounded AI edit consultant. The deterministic engine has already fixed the musical shot windows and supplied a small set of valid candidate scenes. "
        "You may ONLY rank scene_id values present in bounded_candidates. Never invent IDs, filenames, timestamps, clips, or effects. Prefer visual storytelling across the whole section: callbacks, contrast, human/abstract alternation, palette/motion progression, and payoff. "
        "Do not choose the same clip repeatedly unless repetition is narratively useful. Your choices are advisory soft preferences: tubeviz may reject them for hard trim, cooldown, duration, motif, or media constraints. "
        "effect_family and hero_kind are optional; use hero effects rarely. Return strict JSON only.\n\n"
        f"Required schema:\n{json.dumps(schema, indent=2)}\n\n"
        f"Section edit context:\n{json.dumps(payload, indent=2)}"
    )


def _request_payload(prompt: str, cfg: AIEditConsultantConfig) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": "Return strict JSON only. Rank only candidate scene IDs supplied by tubeviz."},
            {"role": "user", "content": prompt},
        ],
    }
    if _is_native_openai(cfg.base_url or ""):
        body.update({
            "reasoning_effort": cfg.reasoning_effort,
            "max_completion_tokens": max(512, int(cfg.max_completion_tokens)),
            "response_format": {"type": "json_object"},
        })
    else:
        body["temperature"] = 0.25
    return body


def _call(prompt: str, cfg: AIEditConsultantConfig) -> dict[str, Any]:
    if not cfg.base_url or not cfg.model:
        raise RuntimeError("AI edit consultant needs an OpenAI base URL and model")
    headers = {"Content-Type": "application/json"}
    key = resolve_llm_api_key(cfg.base_url, cfg.api_key)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        _endpoint(cfg.base_url),
        data=json.dumps(_request_payload(prompt, cfg)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1200]
        raise RuntimeError(f"AI edit consultant HTTP {exc.code}: {detail}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("AI edit consultant response has no choices")
    content = str(((choices[0].get("message") or {}).get("content")) or "")
    if not content.strip():
        raise RuntimeError("AI edit consultant returned no JSON content")
    return _extract_json(content)


def consult_section(
    section: Section,
    *,
    windows: list[tuple[float, float]],
    candidates: list[tuple[SceneCandidate, float]],
    previous: SceneCandidate | None,
    config: AIEditConsultantConfig,
    progress: Callable[[str], None] = print,
) -> dict[int, dict[str, Any]]:
    if not config.enabled or not candidates or not windows:
        return {}
    valid_ids = {c.scene_id for c, _ in candidates}
    prompt = _prompt(section, windows, candidates, previous)
    root = _cache_root(config)
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps({
        "model": config.model,
        "base_url": config.base_url,
        "prompt": prompt,
    }, sort_keys=True).encode()).hexdigest()
    cache = root / f"{digest}.json"
    if cache.is_file() and not config.force:
        raw = json.loads(cache.read_text())
        progress(f"AI edit consultant: section {section.index} loaded cached candidate advice")
    else:
        progress(f"AI edit consultant: section {section.index} ranking {len(candidates)} valid scenes for {len(windows)} shots")
        raw = _call(prompt, config)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2, sort_keys=True))
        tmp.replace(cache)

    result: dict[int, dict[str, Any]] = {}
    for item in raw.get("shots", []):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("shot_index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(windows):
            continue
        prefs: list[int] = []
        for value in item.get("preferred_scene_ids", []):
            try:
                scene_id = int(value)
            except (TypeError, ValueError):
                continue
            if scene_id in valid_ids and scene_id not in prefs:
                prefs.append(scene_id)
        family = item.get("effect_family")
        if family not in EFFECT_FAMILIES:
            family = None
        hero = item.get("hero_kind")
        hero = str(hero).replace("_", " ") if hero else None
        if hero not in HERO_EFFECTS:
            hero = None
        result[index] = {
            "preferred_scene_ids": prefs,
            "effect_family": family,
            "hero_kind": hero,
            "reason": str(item.get("reason") or "")[:400],
        }
    return result


def preference_bonus(scene_id: int, advice: dict[str, Any] | None, weight: float) -> float:
    if not advice:
        return 0.0
    prefs = list(advice.get("preferred_scene_ids") or [])
    if scene_id not in prefs:
        return 0.0
    rank = prefs.index(scene_id)
    # Strong enough to break close deterministic ties, not enough to overpower a clearly bad scene.
    return max(0.0, float(weight)) * (1.0 / (1.0 + 0.55 * rank))
