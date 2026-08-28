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

from .ai_resources import (
    COMPOSITION_MODES, EFFECT_CATALOG, EFFECT_FAMILIES, HERO_EFFECTS,
    compact_candidate, normalize_effect_name,
)
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
        "available_treatments": {
            "effect_families": EFFECT_FAMILIES,
            "hero_effects": HERO_EFFECTS,
            "composition_modes": COMPOSITION_MODES,
            "effect_catalog": EFFECT_CATALOG,
        },
    }
    schema = {
        "shots": [{
            "shot_index": 0,
            "preferred_scene_ids": [123, 456, 789],
            "effect_family": "cinematic",
            "preferred_effects": ["optical-flow warp", "motion trails"],
            "effect_bias": 0.75,
            "composition_mode": "flow",
            "history_mode": "auto",
            "hero_kind": None,
            "reason": "brief editorial reason grounded in the supplied candidates, song arc and effect suitability"
        }]
    }
    return (
        "You are tubeviz's bounded AI edit consultant. The deterministic engine has already fixed the musical shot windows and supplied a small set of valid candidate scenes. "
        "You may ONLY rank scene_id values present in bounded_candidates. Never invent IDs, filenames, timestamps, clips, or effects. Prefer visual storytelling across the whole section: callbacks, contrast, human/abstract alternation, palette/motion progression, and payoff. The section's whole-song director plan is primary creative intent: reinforce its strategy and director_beats rather than replacing them; use your candidate ranking and shot advice to make those ideas feasible with the bounded material. "
        "Do not choose the same clip repeatedly unless repetition is narratively useful. Your choices are advisory soft preferences: tubeviz may reject them for hard trim, cooldown, duration, motif, or media constraints. "
        "For each shot, use the exact effect_catalog and its tier/default_policy to judge which effects suit the supplied scene semantics, motion, complexity and the musical moment. preferred_effects must contain catalog names only, and an empty list is often the correct source-first choice. effect_bias controls occurrence density for this shot (about 0.6–0.9 ordinary, 1 normal, above 1 only for a strong build/peak/hero), not raw amplitude. Core effects may remain subtle; accent effects should be absent on most shots; hero-tier effects should normally accompany an actual hero/payoff decision. "
        "composition_mode must be one of the supplied modes and should be used only when multiple sources improve the edit. history_mode may be auto, inherit or reset; inherit is useful for coherent temporal trails/feedback across related shots, while reset protects abrupt visual changes. "
        "effect_family and hero_kind are optional; use hero effects as punctuation rather than wallpaper. Native render is the reference output, so prefer treatments marked native. Return strict JSON only.\n\n"
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
        preferred_effects: list[str] = []
        for value in item.get("preferred_effects", []):
            name = normalize_effect_name(value)
            if name and name not in preferred_effects:
                preferred_effects.append(name)
        try:
            effect_bias = min(1.75, max(0.25, float(item.get("effect_bias", 0.75))))
        except (TypeError, ValueError):
            effect_bias = 0.75
        if hero is None:
            effect_bias = min(effect_bias, 1.25 if section.label in {"build", "peak"} else 1.0)
        composition = str(item.get("composition_mode") or "").strip().lower().replace("_", " ")
        composition_aliases = {
            "single source": "single", "flow blend": "flow", "luma blend": "luma",
            "organic strips": "strips", "split reveal": "split", "flowing mosaic": "mosaic",
            "source swap": "swap",
        }
        composition = composition_aliases.get(composition, composition)
        if composition not in COMPOSITION_MODES:
            composition = None
        history_mode = str(item.get("history_mode") or "auto").strip().lower()
        if history_mode not in {"auto", "inherit", "reset"}:
            history_mode = "auto"
        result[index] = {
            "preferred_scene_ids": prefs,
            "effect_family": family,
            "preferred_effects": preferred_effects[:8],
            "effect_bias": effect_bias,
            "composition_mode": composition,
            "history_mode": history_mode,
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
