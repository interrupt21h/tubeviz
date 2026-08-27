# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import numpy as np

from .library import ClipLibrary, SceneCandidate
from .ai_edit_consultant import AIEditConsultantConfig, consult_section, preference_bonus
from .audio_ai import CONCEPT_KEYS, CONCEPT_PROMPTS, scene_audio_concept_alignment, top_audio_concepts
from .models import CompositeLayer, DirectedTimeline, SceneIntent, SceneSelection, VisualCue
from .transforms import TransformConfig, attach_transform_plan
from .creative_effects import apply_temporal_persistence, promote_hero_effects
from .editing import EditConfig, attach_edit_plan
from .visual_features import index_scene_visual_features
from .choreography import (
    effect_compatibility_score, shot_trajectory, trajectory_scene_score,
    trajectory_transition_score,
)
from .visual_director import (
    aligned_excerpt,
    build_visual_direction,
    transition_score,
    visual_match_score,
)
from .semantic import (
    OpenClipEmbedder,
    SemanticConfig,
    cosine_similarity,
    metadata_semantic_score,
)


@dataclass(frozen=True)
class SceneSelectorConfig:
    crossfade_seconds: float = 1.25
    opacity: float = 0.92
    min_scene_seconds: float = 1.0
    recent_scene_window: int = 8
    semantic: bool = False
    semantic_model: str = "ViT-B-32"
    semantic_pretrained: str = "laion2b_s34b_b79k"
    semantic_device: str = "auto"
    visual_semantic_weight: float = 4.0
    transforms: bool = True
    transform_intensity: float = 1.0
    creative_effects: bool = True
    creative_intensity: float = 1.0
    # Intensity controls amplitude; density controls how often punctuation is
    # scheduled.  The latter deliberately restores dynamic range without making
    # every active effect stronger.
    effect_density: float = 1.0
    temporal_persistence: float = 1.0
    hero_frequency: float = 1.0
    max_video_layers: int = 3
    composition_intensity: float = 1.0
    composition_diversity: float = 1.0
    selection_seed: int = 0
    selection_variation: float = 0.30
    # Novelty-aware editing. target_unique_clips=0 means auto.
    target_unique_clips: int = 0
    novelty_weight: float = 0.65
    novelty_candidate_fraction: float = 0.30
    clip_reuse_cooldown: int = 20
    scene_reuse_cooldown: int = 48
    # Shot subdivision inside musical sections.
    dynamic_shots: bool = True
    min_shot_seconds: float = 0.65
    max_shot_seconds: float = 6.0
    source_excerpt_max_seconds: float = 5.0
    visual_match_weight: float = 1.25
    transition_weight: float = 0.70
    rhythm_alignment: bool = True
    visual_auto_index: bool = True
    vector_effects: bool = True
    vector_intensity: float = 1.0
    codec_glitch_mode: str = "off"
    codec_glitch_intensity: float = 0.65
    audio_visual_match_weight: float = 1.10
    # v0.27 phrase-aware multi-shot optimization.
    sequence_lookahead: int = 5
    sequence_beam_width: int = 6
    sequence_candidate_pool: int = 18
    trajectory_weight: float = 0.85
    anticipation_weight: float = 0.75
    effect_compatibility_weight: float = 0.60
    preference_learning: bool = True
    preference_weight: float = 0.35
    # Optional second LLM pass. It sees only a bounded slate of already-valid scenes
    # and contributes a soft ranking bonus; deterministic timing/cooldowns stay authoritative.
    ai_consultant_enabled: bool = False
    ai_consultant_base_url: str | None = None
    ai_consultant_model: str | None = None
    ai_consultant_api_key: str | None = None
    ai_consultant_timeout: float = 90.0
    ai_consultant_cache_dir: str | None = None
    ai_consultant_force: bool = False
    ai_consultant_candidates: int = 12
    ai_consultant_weight: float = 0.85
    ai_consultant_reasoning_effort: str = "none"
    ai_consultant_max_completion_tokens: int = 4096


_SECTION_DESCRIPTORS = {
    "ambient": "slow atmospheric sparse quiet dreamlike",
    "drive": "kinetic rhythmic moving energetic",
    "build": "rising tension anticipation increasing motion",
    "breakdown": "deconstructed spacious suspended reduced motion",
    "peak": "intense dramatic chaotic high energy climax",
}


def _stable_u64(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _media_file(media_path: str) -> str:
    # Keep the library-relative directory explicit.  New libraries may point
    # ready clips directly at originals/ while legacy/proxied clips live under
    # normalized/.  Explicit paths remove the old native-renderer ambiguity.
    return Path(media_path).as_posix()


def _media_url(media_path: str) -> str:
    path = Path(media_path)
    parts = path.parts
    if parts and parts[0] == "originals":
        relative = Path(*parts[1:]).as_posix()
        return f"/originals/{quote(relative)}"
    if parts and parts[0] == "normalized":
        relative = Path(*parts[1:]).as_posix()
        return f"/media/{quote(relative)}"
    # Backward compatibility for custom/basename-only scene candidates.
    return f"/media/{quote(path.as_posix())}"


def _intent_query(
    term: str,
    section_label: str,
    key: str | None,
    *,
    vibe: str = "neutral",
    local_tempo_bpm: float | None = None,
) -> str:
    descriptor = _SECTION_DESCRIPTORS.get(section_label, section_label)
    pieces = [term, descriptor, f"{vibe} visual atmosphere", "cinematic archival video footage"]
    if local_tempo_bpm:
        if local_tempo_bpm < 95:
            pieces.append("slow drifting motion")
        elif local_tempo_bpm > 135:
            pieces.append("fast kinetic motion")
        else:
            pieces.append("rhythmic medium motion")
    if key:
        pieces.append(f"mood associated with {key}")
    return ". ".join(piece for piece in pieces if piece)


def _semantic_score(
    candidate: SceneCandidate,
    *,
    query: str,
    query_vector: np.ndarray | None,
    embedding_map: dict[int, np.ndarray],
    visual_weight: float,
) -> float:
    score = metadata_semantic_score(candidate, query)
    # Vision descriptions cover the whole visible frame (subjects, action,
    # setting, mood, camera, palette and editing utility). Feed all textual
    # fields into retrieval instead of treating the analysis as display-only.
    if candidate.ai_description:
        corpus = json.dumps(candidate.ai_description, ensure_ascii=False).lower()
        terms = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 2}
        if terms:
            score += 1.6 * sum(1 for token in terms if token in corpus) / len(terms)
        utility = candidate.ai_description
        target = query.lower()
        if "peak" in target or "intense" in target:
            score += .45 * float(utility.get("drop_fit", utility.get("energy", 0)) or 0)
        elif "build" in target or "rising" in target:
            score += .45 * float(utility.get("build_fit", utility.get("motion", 0)) or 0)
        elif "ambient" in target or "slow" in target:
            score += .45 * float(utility.get("ambient_fit", utility.get("continuity", 0)) or 0)
    if query_vector is not None:
        vector = embedding_map.get(candidate.scene_id)
        if vector is not None:
            score += visual_weight * cosine_similarity(vector, query_vector)
    return score


def _seed_unit(seed: int, value: str) -> float:
    return _stable_u64(f"{seed}:{value}") / float(1 << 64)


def _scene_rank(
    candidate: SceneCandidate,
    target_duration: float,
    salt: str,
    semantic_score: float,
    *,
    selection_seed: int = 0,
    selection_variation: float = 0.0,
    used_clip_counts: Counter[int] | None = None,
    target_unique_clips: int = 0,
    unique_used: int = 0,
    recent_clip_ids: set[int] | None = None,
    novelty_weight: float = 0.0,
) -> tuple[float, float, int]:
    duration_penalty = abs(candidate.duration - target_duration)
    tie = _stable_u64(f"{selection_seed}:{salt}:{candidate.scene_id}")
    variation = max(0.0, float(selection_variation)) if selection_seed else 0.0
    jitter = _seed_unit(selection_seed, f"{salt}:{candidate.scene_id}") * variation

    counts = used_clip_counts or Counter()
    clip_uses = counts.get(candidate.clip_id, 0)
    novelty = 0.0
    if novelty_weight > 0:
        if clip_uses == 0:
            # Strongly explore until the requested unique-source target is met.
            target_pressure = 1.0 if target_unique_clips <= 0 or unique_used < target_unique_clips else 0.35
            novelty += novelty_weight * target_pressure
        else:
            novelty += novelty_weight * 0.12 / (1.0 + clip_uses)
        if recent_clip_ids and candidate.clip_id in recent_clip_ids:
            novelty -= novelty_weight * 0.80

    return (-(semantic_score + jitter + novelty), duration_penalty, tie)



def _choose_scene(
    candidates: list[SceneCandidate],
    *,
    target_duration: float,
    salt: str,
    recent_scene_ids: set[int],
    semantic_scores: dict[int, float],
    preferred_clip_id: int | None = None,
    ordinal: int = 1,
    selection_seed: int = 0,
    selection_variation: float = 0.0,
    recent_clip_ids: set[int] | None = None,
    used_clip_counts: Counter[int] | None = None,
    target_unique_clips: int = 0,
    novelty_weight: float = 0.0,
    novelty_candidate_fraction: float = 0.30,
) -> SceneCandidate | None:
    usable = [candidate for candidate in candidates if candidate.duration > 0]
    if not usable:
        return None

    counts = used_clip_counts or Counter()
    recent_clips = recent_clip_ids or set()

    if preferred_clip_id is not None:
        same_clip = [candidate for candidate in usable if candidate.clip_id == preferred_clip_id]
        if same_clip:
            fresh_same_clip = [
                candidate for candidate in same_clip
                if candidate.scene_id not in recent_scene_ids
            ]
            rotation_pool = fresh_same_clip or same_clip
            return min(
                rotation_pool,
                key=lambda item: _scene_rank(
                    item,
                    target_duration,
                    f"{salt}:occurrence:{ordinal}",
                    semantic_scores.get(item.scene_id, 0.0),
                    selection_seed=selection_seed,
                    selection_variation=selection_variation,
                    used_clip_counts=counts,
                    target_unique_clips=target_unique_clips,
                    unique_used=len(counts),
                    recent_clip_ids=recent_clips,
                    novelty_weight=novelty_weight * 0.25,
                ),
            )

    # Scene cooldown first.
    fresh_scenes = [c for c in usable if c.scene_id not in recent_scene_ids]
    pool = fresh_scenes or usable

    # While there are alternatives, honor clip cooldown too. This prevents a
    # high-scoring source from monopolizing the entire song.
    fresh_clips = [c for c in pool if c.clip_id not in recent_clips]
    if fresh_clips:
        pool = fresh_clips

    # Before reaching the unique-source target, prefer unseen clips, but only
    # among the semantically strongest portion of the candidate pool. This keeps
    # novelty from turning into random/irrelevant footage.
    if target_unique_clips > 0 and len(counts) < target_unique_clips and pool:
        fraction = min(1.0, max(0.05, novelty_candidate_fraction))
        plausible_count = min(
            len(pool),
            max(8, int(round(len(pool) * fraction))),
        )
        plausible = sorted(
            pool,
            key=lambda c: (
                -semantic_scores.get(c.scene_id, 0.0),
                c.scene_id,
            ),
        )[:plausible_count]
        unseen = [c for c in plausible if counts.get(c.clip_id, 0) == 0]
        if unseen:
            pool = unseen

    return min(
        pool,
        key=lambda item: _scene_rank(
            item,
            target_duration,
            salt,
            semantic_scores.get(item.scene_id, 0.0),
            selection_seed=selection_seed,
            selection_variation=selection_variation,
            used_clip_counts=counts,
            target_unique_clips=target_unique_clips,
            unique_used=len(counts),
            recent_clip_ids=recent_clips,
            novelty_weight=novelty_weight,
        ),
    )



def _preference_score(candidate: SceneCandidate, profile: dict[str, object] | None) -> float:
    if not profile or not candidate.visual_features:
        return 0.0
    keys = list(profile.get("keys", []))
    rejected = list(profile.get("rejected_centroid", []))
    scale = list(profile.get("rejected_scale", []))
    if not keys or len(keys) != len(rejected):
        return 0.0
    values = [float(candidate.visual_features.get(key, .0 if key == "cut_rate" else .5)) for key in keys]
    # Similarity to a repeatedly rejected region yields a negative score;
    # distance saturates so a few odd rejects cannot dominate semantic matching.
    norm_sq = 0.0
    for i, value in enumerate(values):
        sigma = float(scale[i]) if i < len(scale) else .2
        norm_sq += ((value-float(rejected[i]))/max(.08,sigma))**2
    distance = (norm_sq/max(1,len(values)))**.5
    rejected_similarity = max(0.0, 1.0-distance/3.0)
    ready = profile.get("ready_centroid")
    positive = 0.0
    if isinstance(ready, list) and len(ready) == len(values):
        euclid = (sum((values[i]-float(ready[i]))**2 for i in range(len(values)))/len(values))**.5
        positive = max(0.0, 1.0-euclid/.65)
    return max(-1.0, min(1.0, .20*positive-.85*rejected_similarity))


def _sequence_choose(
    candidates: list[SceneCandidate],
    *,
    section,
    windows: list[tuple[float, float]],
    window_index: int,
    previous: SceneCandidate | None,
    semantic_scores: dict[int, float],
    audio_visual_scores: dict[int, float],
    recent_scene_ids: set[int],
    recent_clip_ids: set[int],
    used_clip_counts: Counter[int],
    preferred_clip_id: int | None,
    preference_profile: dict[str, object] | None,
    cfg: SceneSelectorConfig,
    salt: str,
    consultant_advice: dict[int, dict[str, object]] | None = None,
) -> SceneCandidate | None:
    """Beam-search a short scene sequence and return its first scene.

    Greedy per-shot matching can produce individually-good but collectively
    incoherent cuts. This search scores short future sequences for semantic fit,
    trajectory progression, effect compatibility, transitions and source reuse.
    Exact cut times remain owned by the beat-aligned shot planner.
    """
    usable = [c for c in candidates if c.duration > 0]
    if not usable:
        return None
    depth = min(max(1, cfg.sequence_lookahead), len(windows)-window_index)
    beam_width = max(1, cfg.sequence_beam_width)
    pool_size = max(4, cfg.sequence_candidate_pool)
    section_span = max(.05, float(section.end-section.start))

    def progress_for(idx: int) -> float:
        a, b = windows[idx]
        return min(1.0, max(0.0, ((a+b)*.5-section.start)/section_span))

    p0 = progress_for(window_index)
    def static_score(c: SceneCandidate, progress: float, local_index: int) -> float:
        return (
            semantic_scores.get(c.scene_id, 0.0)
            + cfg.visual_match_weight * visual_match_score(c, section)
            + cfg.audio_visual_match_weight * section.audio_semantic_confidence
              * audio_visual_scores.get(c.scene_id, 0.0)
            + cfg.trajectory_weight * trajectory_scene_score(c, section, progress)
            + cfg.effect_compatibility_weight * effect_compatibility_score(c, section)
            + cfg.preference_weight * _preference_score(c, preference_profile)
            + preference_bonus(c.scene_id, (consultant_advice or {}).get(local_index), cfg.ai_consultant_weight)
        )

    initial = sorted(usable, key=lambda c: (-static_score(c, p0, window_index), c.scene_id))[:pool_size]
    if preferred_clip_id is not None:
        preferred = [c for c in usable if c.clip_id == preferred_clip_id]
        for c in preferred[:4]:
            if c not in initial:
                initial.append(c)

    # (score, sequence, local clip counts)
    beams: list[tuple[float, tuple[SceneCandidate, ...], Counter[int]]] = [(0.0, tuple(), Counter())]
    for step in range(depth):
        progress = progress_for(window_index+step)
        candidates_step = initial if step == 0 else sorted(
            usable, key=lambda c: (-static_score(c, progress, window_index+step), c.scene_id)
        )[:pool_size]
        if step == 0 and preferred_clip_id is not None:
            preferred_step = [c for c in usable if c.clip_id == preferred_clip_id]
            fresh_preferred = [c for c in preferred_step if c.scene_id not in recent_scene_ids]
            if fresh_preferred:
                preferred_step = fresh_preferred
            if preferred_step:
                candidates_step = preferred_step
        expanded: list[tuple[float, tuple[SceneCandidate, ...], Counter[int]]] = []
        for score, sequence, local_counts in beams:
            prev = sequence[-1] if sequence else previous
            for candidate in candidates_step:
                base = static_score(candidate, progress, window_index+step)
                transition = cfg.transition_weight * transition_score(prev, candidate, section)
                anticipation = cfg.anticipation_weight * trajectory_transition_score(prev, candidate, section, progress)
                # Cooldowns are soft inside the lookahead: impossible hard filters can
                # collapse a beam in small libraries, while penalties preserve escape paths.
                penalty = 0.0
                if candidate.scene_id in recent_scene_ids:
                    penalty += .80
                if candidate.clip_id in recent_clip_ids:
                    penalty += .48
                total_uses = used_clip_counts.get(candidate.clip_id, 0) + local_counts.get(candidate.clip_id, 0)
                penalty += min(.85, total_uses*.10*max(.25, cfg.novelty_weight))
                if sequence and candidate.clip_id == sequence[-1].clip_id:
                    penalty += .38
                if preferred_clip_id is not None and step == 0 and candidate.clip_id == preferred_clip_id:
                    base += .80
                jitter = _seed_unit(cfg.selection_seed, f"beam:{salt}:{step}:{candidate.scene_id}") * max(0.0, cfg.selection_variation)
                discount = .88**step
                next_counts = local_counts.copy()
                next_counts[candidate.clip_id] += 1
                expanded.append((score + discount*(base+transition+anticipation+jitter-penalty), sequence+(candidate,), next_counts))
        expanded.sort(key=lambda item: (-item[0], tuple(c.scene_id for c in item[1])))
        beams = expanded[:beam_width]
        if not beams:
            break
    return beams[0][1][0] if beams and beams[0][1] else None

def _composition_mode(
    label: str,
    energy: float,
    section_index: int,
    layers: int,
    vibe: str = "neutral",
    *,
    diversity: float = 1.0,
    preferred: str | None = None,
) -> str:
    """Choose a musical multi-source grammar, including dynamic full-frame modes.

    ``composition_intensity`` still controls how many companions are present.
    ``diversity`` instead controls how readily the editor departs from the safe
    flow/luma/strips vocabulary.  At 1.0 historical scheduling is preserved;
    values above ~1.1 admit animated split, mosaic-flow and source-swap modes.
    """
    if layers <= 1:
        return "single"
    preferred = str(preferred or "").replace(" ", "_").lower()
    aliases = {
        "flow_blend": "flow", "luma_blend": "luma", "organic_strips": "strips",
        "split_reveal": "split", "flowing_mosaic": "mosaic", "source_swap": "swap",
    }
    preferred = aliases.get(preferred, preferred)
    if preferred in {"flow", "luma", "strips", "split", "mosaic", "swap"}:
        return preferred

    diversity = max(0.0, min(2.5, float(diversity)))
    if diversity <= 1.10:
        if label in {"ambient", "breakdown"} or vibe in {"ambient", "hypnotic", "dark"}:
            return "flow"
        if label == "drive":
            return "luma" if section_index % 2 == 0 else "flow"
        if label == "build":
            return "flow" if section_index % 2 == 0 else "strips"
        if label == "peak":
            return ("luma", "strips", "flow")[section_index % 3]
        return "flow"

    # Dynamic modes are deterministic and phrase-sensitive rather than random.
    if label in {"ambient", "breakdown"}:
        choices = ("flow", "luma", "mosaic") if diversity >= 1.45 else ("flow", "luma")
    elif label == "build":
        choices = ("strips", "split", "flow", "swap")
    elif label == "peak":
        choices = ("split", "mosaic", "swap", "strips", "luma", "flow")
    elif label == "drive":
        choices = ("swap", "strips", "luma", "split", "flow")
    else:
        choices = ("flow", "luma", "strips", "split")
    if diversity < 1.45:
        choices = tuple(mode for mode in choices if mode not in {"mosaic", "swap"}) or ("flow",)
    index = int(section_index + round(energy * 7.0) + round(diversity * 3.0)) % len(choices)
    return choices[index]


def _choose_companions(
    candidates: list[SceneCandidate],
    *,
    selected: SceneCandidate,
    target_duration: float,
    salt: str,
    semantic_scores: dict[int, float],
    recent_scene_ids: set[int],
    count: int,
    selection_seed: int = 0,
    selection_variation: float = 0.0,
    recent_clip_ids: set[int] | None = None,
    used_clip_counts: Counter[int] | None = None,
    target_unique_clips: int = 0,
    novelty_weight: float = 0.0,
) -> list[SceneCandidate]:
    pool = [c for c in candidates if c.scene_id != selected.scene_id and c.duration > 0]
    # Prefer source diversity for compositing. If the corpus is sparse, permit the
    # same clip only after all other clips have been considered.
    recent_clips = recent_clip_ids or set()
    counts = used_clip_counts or Counter()
    pool.sort(key=lambda c: (
        c.clip_id == selected.clip_id,
        c.clip_id in recent_clips,
        c.scene_id in recent_scene_ids,
        *_scene_rank(
            c, target_duration, f"{salt}:layer", semantic_scores.get(c.scene_id, 0.0),
            selection_seed=selection_seed,
            selection_variation=selection_variation,
            used_clip_counts=counts,
            target_unique_clips=target_unique_clips,
            unique_used=len(counts),
            recent_clip_ids=recent_clips,
            novelty_weight=novelty_weight * 0.7,
        ),
    ))
    out: list[SceneCandidate] = []
    used_clips = {selected.clip_id}
    for candidate in pool:
        if len(out) >= count:
            break
        if candidate.clip_id in used_clips and any(c.clip_id not in used_clips for c in pool):
            continue
        out.append(candidate)
        used_clips.add(candidate.clip_id)
    if len(out) < count:
        for candidate in pool:
            if candidate not in out and len(out) < count:
                out.append(candidate)
    return out


def _beats_per_shot(section) -> int:
    """Musically sensible shot density from section energy, vibe, and AI arc."""
    if section.ai_direction is not None:
        density = section.ai_direction.edit_density
        # Quantize the AI director onto musical beat counts so it can influence
        # pacing without owning exact cut times.
        if density >= .86:
            return 1
        if density >= .68:
            return 2
        if density >= .46:
            return 4
        if density >= .28:
            return 6
        return 8
    vibe = section.vibe
    if vibe in {"ambient", "hypnotic"} or section.label == "breakdown":
        return 8
    if section.label == "peak" or vibe in {"heavy", "fractured", "euphoric"}:
        return 2
    if section.label == "build":
        return 2 if section.energy >= 0.72 else 4
    if vibe == "driving" or section.energy >= 0.58:
        return 4
    return 6


def _shot_windows(timeline: DirectedTimeline, section, cfg: SceneSelectorConfig) -> list[tuple[float, float]]:
    start, end = float(section.start), float(section.end)
    if end <= start:
        return []
    if not cfg.dynamic_shots:
        return [(start, end)]

    beats = [b for b in timeline.track.beats if start - 1e-6 <= b < end - 1e-6]
    beats_per_shot = _beats_per_shot(section)
    boundaries = [start]
    if len(beats) >= 2:
        # Begin subdivisions on the first beat inside the section and then use
        # musical beat counts rather than fixed wall-clock seconds.
        for i in range(beats_per_shot, len(beats), beats_per_shot):
            t = float(beats[i])
            if t - boundaries[-1] >= cfg.min_shot_seconds:
                boundaries.append(t)
    else:
        # A beat-less imported/legacy timeline has no musical grid to subdivide
        # against, so retain the original one-shot-per-section behavior.
        return [(start, end)]
    boundaries.append(end)

    windows: list[tuple[float, float]] = []
    for a, b in zip(boundaries, boundaries[1:]):
        if b <= a:
            continue
        # Split unexpectedly long windows while respecting the configured max.
        cursor = a
        while b - cursor > cfg.max_shot_seconds + cfg.min_shot_seconds:
            cut = min(b, cursor + cfg.max_shot_seconds)
            windows.append((cursor, cut))
            cursor = cut
        if b - cursor >= cfg.min_shot_seconds * 0.45:
            windows.append((cursor, b))
        elif windows:
            prev_a, _ = windows[-1]
            windows[-1] = (prev_a, b)
    return windows or [(start, end)]


def _excerpt(candidate: SceneCandidate, shot_seconds: float, salt: str, cfg: SceneSelectorConfig) -> tuple[float, float]:
    """Choose a deterministic short source range within a detected scene."""
    available = max(0.05, candidate.end_time - candidate.start_time)
    wanted = min(
        available,
        max(cfg.min_scene_seconds, shot_seconds),
        max(cfg.min_scene_seconds, cfg.source_excerpt_max_seconds),
    )
    if wanted >= available - 1e-6:
        return candidate.start_time, candidate.end_time
    travel = available - wanted
    # The seed salt gives different excerpts from the same long detected scene.
    unit = _stable_u64(f"excerpt:{salt}:{candidate.scene_id}") / float(1 << 64)
    source_start = candidate.start_time + travel * unit
    return source_start, source_start + wanted


def _auto_unique_target(duration: float, available_clip_count: int, cfg: SceneSelectorConfig) -> int:
    if cfg.target_unique_clips > 0:
        return min(available_clip_count, cfg.target_unique_clips)
    # Default: roughly one unique source every 2.4 seconds for short/medium
    # songs, capped by the actual READY corpus. A 4-minute song targets ~100.
    desired = max(12, int(round(duration / 2.4)))
    return min(available_clip_count, desired)



def _consultant_slate(
    candidates: list[SceneCandidate], *, section, windows: list[tuple[float, float]],
    semantic_scores: dict[int, float], audio_visual_scores: dict[int, float],
    preference_profile: dict[str, object] | None, cfg: SceneSelectorConfig,
) -> list[tuple[SceneCandidate, float]]:
    """Union the strongest deterministic candidates across the section's shot trajectory."""
    if not candidates:
        return []
    section_span = max(.05, float(section.end-section.start))
    best: dict[int, tuple[SceneCandidate, float]] = {}
    per_window = max(4, min(8, cfg.ai_consultant_candidates // 2 or 4))
    for a, b in windows:
        progress = min(1.0, max(0.0, ((a+b)*.5-section.start)/section_span))
        scored = []
        for candidate in candidates:
            score = (
                semantic_scores.get(candidate.scene_id, 0.0)
                + cfg.visual_match_weight * visual_match_score(candidate, section)
                + cfg.audio_visual_match_weight * section.audio_semantic_confidence
                  * audio_visual_scores.get(candidate.scene_id, 0.0)
                + cfg.trajectory_weight * trajectory_scene_score(candidate, section, progress)
                + cfg.effect_compatibility_weight * effect_compatibility_score(candidate, section)
                + cfg.preference_weight * _preference_score(candidate, preference_profile)
            )
            scored.append((score, candidate))
        scored.sort(key=lambda x: (-x[0], x[1].scene_id))
        for score, candidate in scored[:per_window]:
            old = best.get(candidate.scene_id)
            if old is None or score > old[1]:
                best[candidate.scene_id] = (candidate, score)
    result = sorted(best.values(), key=lambda x: (-x[1], x[0].scene_id))
    return result[:max(4, int(cfg.ai_consultant_candidates))]


def build_scene_plan(
    timeline: DirectedTimeline,
    library: ClipLibrary,
    config: SceneSelectorConfig | None = None,
    *,
    progress=print,
) -> list[SceneSelection]:
    cfg = config or SceneSelectorConfig()
    library.initialize()
    terms = library.list_terms(ready_only=True)
    if not terms:
        return []

    motif_by_section: dict[int, tuple[str, int]] = {}
    for motif in timeline.motifs:
        for occurrence in motif.occurrences:
            motif_by_section[occurrence.section_index] = (motif.id, occurrence.ordinal)

    motif_term: dict[str, str] = {
        motif.id: (
            terms[_stable_u64(f"{cfg.selection_seed}:motif:{motif.id}") % len(terms)]
            if cfg.selection_seed
            else terms[_stable_u64(motif.id) % len(terms)]
        )
        for motif in timeline.motifs
    }
    motif_clip: dict[str, int] = {}

    # Keep scene and source cooldowns independently. Scene reuse is much more
    # expensive than source reuse, so its default window is longer.
    recent_scenes: deque[int] = deque(maxlen=max(0, cfg.scene_reuse_cooldown))
    recent_clips: deque[int] = deque(maxlen=max(0, cfg.clip_reuse_cooldown))
    used_clip_counts: Counter[int] = Counter()

    candidates_cache: dict[str, list[SceneCandidate]] = {}
    selections: list[SceneSelection] = []

    embedder: OpenClipEmbedder | None = None
    all_embeddings: dict[int, np.ndarray] = {}
    global_candidates = library.scene_candidates(min_duration=cfg.min_scene_seconds)
    preference_profile = library.visual_preference_profile() if cfg.preference_learning and cfg.preference_weight > 0 else None
    if cfg.visual_auto_index and any(candidate.visual_features is None for candidate in global_candidates):
        # One-time backfill for libraries created before visual fingerprints
        # existed. Features are persisted, so subsequent analysis is cheap.
        index_scene_visual_features(library)
        global_candidates = library.scene_candidates(min_duration=cfg.min_scene_seconds)
    available_clip_count = len({candidate.clip_id for candidate in global_candidates})
    target_unique_clips = _auto_unique_target(
        timeline.track.duration, available_clip_count, cfg
    )

    # AI consultation should be able to consider the entire eligible output pool,
    # even when OpenCLIP semantic embeddings are disabled. Metadata/vision descriptions
    # still provide a useful retrieval signal; semantic mode additionally loads vectors.
    all_candidates: list[SceneCandidate] | None = global_candidates if cfg.ai_consultant_enabled else None
    if cfg.semantic:
        semantic_cfg = SemanticConfig(
            model=cfg.semantic_model,
            pretrained=cfg.semantic_pretrained,
            device=cfg.semantic_device,
        )
        embedder = OpenClipEmbedder(semantic_cfg)
        all_candidates = global_candidates
        all_embeddings = library.load_scene_embeddings(
            [candidate.scene_id for candidate in all_candidates],
            model=cfg.semantic_model,
            pretrained=cfg.semantic_pretrained,
        )

    concept_text_embeddings: np.ndarray | None = None
    if embedder is not None and any(section.audio_semantics for section in timeline.track.sections):
        concept_text_embeddings = embedder.encode_text(
            [CONCEPT_PROMPTS[key] for key in CONCEPT_KEYS]
        )

    shot_ordinal = 0
    previous_primary: SceneCandidate | None = None
    for section in timeline.track.sections:
        motif_info = motif_by_section.get(section.index)
        motif_id = motif_info[0] if motif_info else None
        occurrence = motif_info[1] if motif_info else 1
        if motif_id is not None:
            term = motif_term[motif_id]
        else:
            term = (
                terms[_stable_u64(f"{cfg.selection_seed}:section:{section.index}") % len(terms)]
                if cfg.selection_seed
                else terms[section.index % len(terms)]
            )

        query = _intent_query(
            term,
            section.label,
            section.key,
            vibe=section.vibe,
            local_tempo_bpm=section.local_tempo_bpm,
        )
        if section.audio_semantics:
            audio_words = [key.replace("_", " ") for key, _ in top_audio_concepts(section, 5)]
            if audio_words:
                query += ". audio character: " + ", ".join(audio_words)
        if section.ai_direction and section.ai_direction.visual_world:
            query += f". directed visual world: {section.ai_direction.visual_world}"
        query_vector: np.ndarray | None = None
        if embedder is not None:
            query_vector = embedder.encode_text([query])[0]

        if all_candidates is not None:
            candidates = all_candidates
        else:
            candidates = candidates_cache.setdefault(
                term,
                library.scene_candidates(
                    term=term, min_duration=cfg.min_scene_seconds
                ),
            )

        semantic_scores = {
            candidate.scene_id: _semantic_score(
                candidate,
                query=query,
                query_vector=query_vector,
                embedding_map=all_embeddings,
                visual_weight=cfg.visual_semantic_weight,
            )
            for candidate in candidates
        }
        audio_visual_scores = {
            candidate.scene_id: scene_audio_concept_alignment(
                section,
                scene_embedding=all_embeddings.get(candidate.scene_id),
                concept_text_embeddings=concept_text_embeddings,
                candidate=candidate,
            )
            for candidate in candidates
        } if section.audio_semantics else {}

        windows = _shot_windows(timeline, section, cfg)
        consultant_advice: dict[int, dict[str, object]] = {}
        consultant_hero_used = False
        if cfg.ai_consultant_enabled and cfg.ai_consultant_base_url and cfg.ai_consultant_model:
            slate = _consultant_slate(
                candidates, section=section, windows=windows, semantic_scores=semantic_scores,
                audio_visual_scores=audio_visual_scores, preference_profile=preference_profile, cfg=cfg,
            )
            try:
                consultant_advice = consult_section(
                    section, windows=windows, candidates=slate, previous=previous_primary,
                    config=AIEditConsultantConfig(
                        enabled=True, base_url=cfg.ai_consultant_base_url, model=cfg.ai_consultant_model,
                        api_key=cfg.ai_consultant_api_key, timeout=cfg.ai_consultant_timeout,
                        cache_dir=cfg.ai_consultant_cache_dir, force=cfg.ai_consultant_force,
                        candidate_count=cfg.ai_consultant_candidates, weight=cfg.ai_consultant_weight,
                        reasoning_effort=cfg.ai_consultant_reasoning_effort,
                        max_completion_tokens=cfg.ai_consultant_max_completion_tokens,
                    ),
                    progress=progress,
                )
            except Exception as exc:
                progress(f"AI edit consultant: section {section.index} unavailable ({exc}); using deterministic ranking")

        for local_shot_index, (shot_start, shot_end) in enumerate(windows):
            shot_ordinal += 1
            shot_duration = max(0.05, shot_end - shot_start)

            # Preserve motif source identity at the entry of a recurring motif,
            # then allow fresh sources within the phrase so callbacks remain
            # recognizable without freezing an entire section onto one clip.
            preferred_clip = (
                motif_clip.get(motif_id)
                if motif_id is not None and local_shot_index == 0
                else None
            )

            salt = (
                f"section:{section.index}:shot:{local_shot_index}:"
                f"{shot_start:.4f}:{term}"
            )
            shot_scores = {
                candidate.scene_id: (
                    semantic_scores.get(candidate.scene_id, 0.0)
                    + cfg.visual_match_weight * visual_match_score(candidate, section)
                    + cfg.transition_weight * transition_score(previous_primary, candidate, section)
                    + cfg.audio_visual_match_weight
                    * section.audio_semantic_confidence
                    * audio_visual_scores.get(candidate.scene_id, 0.0)
                    + cfg.trajectory_weight * trajectory_scene_score(
                        candidate, section,
                        ((shot_start + shot_end) * .5 - section.start) / max(.05, section.end-section.start),
                    )
                    + cfg.effect_compatibility_weight * effect_compatibility_score(candidate, section)
                    + cfg.preference_weight * _preference_score(candidate, preference_profile)
                    + preference_bonus(candidate.scene_id, consultant_advice.get(local_shot_index), cfg.ai_consultant_weight)
                )
                for candidate in candidates
            }
            selected = None
            if cfg.sequence_lookahead > 1 and len(candidates) > 1 and preferred_clip is None:
                selected = _sequence_choose(
                    candidates, section=section, windows=windows, window_index=local_shot_index,
                    previous=previous_primary, semantic_scores=semantic_scores,
                    audio_visual_scores=audio_visual_scores, recent_scene_ids=set(recent_scenes),
                    recent_clip_ids=set(recent_clips), used_clip_counts=used_clip_counts,
                    preferred_clip_id=preferred_clip, preference_profile=preference_profile, cfg=cfg, salt=salt,
                    consultant_advice=consultant_advice,
                )
            if selected is None:
                selected = _choose_scene(
                    candidates,
                    target_duration=shot_duration,
                    salt=salt,
                    recent_scene_ids=set(recent_scenes),
                    recent_clip_ids=set(recent_clips),
                    semantic_scores=shot_scores,
                    preferred_clip_id=preferred_clip,
                    ordinal=occurrence,
                    selection_seed=cfg.selection_seed,
                    selection_variation=cfg.selection_variation,
                    used_clip_counts=used_clip_counts,
                    target_unique_clips=target_unique_clips,
                    novelty_weight=cfg.novelty_weight,
                    novelty_candidate_fraction=cfg.novelty_candidate_fraction,
                )

            if selected is None:
                fallback_key = "*"
                fallback = candidates_cache.setdefault(
                    fallback_key, global_candidates
                )
                fallback_scores = {
                    candidate.scene_id: (
                        metadata_semantic_score(candidate, query)
                        + cfg.visual_match_weight * visual_match_score(candidate, section)
                        + cfg.transition_weight * transition_score(previous_primary, candidate, section)
                        + cfg.audio_visual_match_weight
                        * section.audio_semantic_confidence
                        * scene_audio_concept_alignment(
                            section,
                            scene_embedding=all_embeddings.get(candidate.scene_id),
                            concept_text_embeddings=concept_text_embeddings,
                            candidate=candidate,
                        )
                    )
                    for candidate in fallback
                }
                selected = _choose_scene(
                    fallback,
                    target_duration=shot_duration,
                    salt=f"fallback:{salt}",
                    recent_scene_ids=set(recent_scenes),
                    recent_clip_ids=set(recent_clips),
                    semantic_scores=fallback_scores,
                    preferred_clip_id=preferred_clip,
                    ordinal=occurrence,
                    selection_seed=cfg.selection_seed,
                    selection_variation=cfg.selection_variation,
                    used_clip_counts=used_clip_counts,
                    target_unique_clips=target_unique_clips,
                    novelty_weight=cfg.novelty_weight,
                    novelty_candidate_fraction=cfg.novelty_candidate_fraction,
                )
                semantic_scores = fallback_scores
                candidates = fallback

            if selected is None:
                continue

            if motif_id is not None and local_shot_index == 0:
                motif_clip.setdefault(motif_id, selected.clip_id)

            recent_scenes.append(selected.scene_id)
            recent_clips.append(selected.clip_id)
            used_clip_counts[selected.clip_id] += 1

            media_file = _media_file(selected.normalized_path)
            beat_positions = [
                float(beat - shot_start)
                for beat in timeline.track.beats
                if shot_start - 1e-6 <= beat < shot_end + 1e-6
            ]
            excerpt_seed = _stable_u64(
                f"{cfg.selection_seed}:{salt}:primary:{selected.scene_id}"
            ) / float(1 << 64)
            if cfg.rhythm_alignment and selected.visual_features:
                source_start, source_end, aligned_rate, rhythm_score = aligned_excerpt(
                    selected,
                    shot_duration=shot_duration,
                    beat_positions=beat_positions,
                    seed_unit=excerpt_seed,
                    min_scene_seconds=cfg.min_scene_seconds,
                    excerpt_max_seconds=cfg.source_excerpt_max_seconds,
                )
            else:
                source_start, source_end = _excerpt(
                    selected,
                    shot_duration,
                    f"{cfg.selection_seed}:{salt}:primary",
                    cfg,
                )
                aligned_rate, rhythm_score = 1.0, 0.0

            advice = consultant_advice.get(local_shot_index) or {}
            ai_density = section.ai_direction.effect_density if section.ai_direction is not None else 1.0
            advice_bias = max(0.25, min(1.75, float(advice.get("effect_bias", 1.0) or 1.0)))
            effective_density = max(0.0, min(2.5, cfg.effect_density * ai_density * advice_bias))
            preferred_effects = list(section.ai_direction.preferred_effects if section.ai_direction is not None else [])
            preferred_effects.extend(str(v) for v in advice.get("preferred_effects", []) if str(v))
            direction = build_visual_direction(
                selected,
                section,
                rhythm_alignment=rhythm_score,
                source_playback_rate=aligned_rate,
                transition=transition_score(previous_primary, selected, section),
                occurrence=occurrence,
                shot_index_in_section=local_shot_index,
                shot_progress=((shot_start + shot_end) * .5 - section.start) / max(.05, section.end-section.start),
                creative_enabled=cfg.transforms and cfg.creative_effects,
                creative_intensity=max(0.0, cfg.creative_intensity),
                effect_density=effective_density,
                preferred_effects=preferred_effects,
                vector_enabled=cfg.vector_effects,
                vector_intensity=cfg.vector_intensity,
                codec_glitch_mode=cfg.codec_glitch_mode,
                codec_glitch_intensity=cfg.codec_glitch_intensity,
                effect_family_override=(consultant_advice.get(local_shot_index) or {}).get("effect_family"),
            )
            requested_family = advice.get("effect_family")
            requested_hero = advice.get("hero_kind")
            if requested_hero and cfg.hero_frequency > 0.0 and not consultant_hero_used and direction.creative.hero_amount <= 0.01:
                hero_name = str(requested_hero).replace(" ", "_")
                # The consultant may request a hero, but at most one consultant hero is
                # admitted per musical section. Renderer semantics stay deterministic.
                direction = direction.model_copy(update={"creative": direction.creative.model_copy(update={
                    "hero_kind": hero_name, "hero_amount": min(0.62, 0.28 + 0.22*section.energy),
                    "hero_start": 0.18, "hero_end": 0.82,
                })})
                consultant_hero_used = True

            layer_budget = max(1, min(4, int(cfg.max_video_layers)))
            comp_strength = max(0.0, min(2.0, cfg.composition_intensity))
            comp_diversity = max(0.0, min(2.5, cfg.composition_diversity))
            if section.ai_direction is not None:
                comp_strength *= .68 + .48*section.ai_direction.desired_complexity + .14*(1-section.ai_direction.continuity)
                comp_diversity *= section.ai_direction.composition_diversity
                comp_strength = max(0.0, min(2.0, comp_strength))
                comp_diversity = max(0.0, min(2.5, comp_diversity))
            comp_diversity = max(0.0, min(2.5, comp_diversity * advice_bias))
            if section.energy < 0.30 or comp_strength <= 0.0:
                desired_layers = 1
            elif section.energy < 0.58:
                desired_layers = min(layer_budget, 2)
            else:
                desired_layers = min(
                    layer_budget, 3 if comp_strength < 1.5 else 4
                )

            companions = _choose_companions(
                candidates,
                selected=selected,
                target_duration=shot_duration,
                salt=f"composite:{salt}",
                semantic_scores=semantic_scores,
                recent_scene_ids=set(recent_scenes),
                count=max(0, desired_layers - 1),
                selection_seed=cfg.selection_seed,
                selection_variation=cfg.selection_variation,
                recent_clip_ids=set(recent_clips),
                used_clip_counts=used_clip_counts,
                target_unique_clips=target_unique_clips,
                novelty_weight=cfg.novelty_weight,
            )

            composite_layers = []
            blend_modes = ("screen", "multiply", "overlay", "lighten")
            for layer_index, companion in enumerate(companions):
                recent_scenes.append(companion.scene_id)
                recent_clips.append(companion.clip_id)
                used_clip_counts[companion.clip_id] += 1
                companion_file = _media_file(companion.normalized_path)
                companion_start, companion_end = _excerpt(
                    companion,
                    shot_duration,
                    f"{cfg.selection_seed}:{salt}:companion:{layer_index}",
                    cfg,
                )
                composite_layers.append(
                    CompositeLayer(
                        role=f"companion_{layer_index + 1}",
                        clip_id=companion.clip_id,
                        scene_id=companion.scene_id,
                        scene_index=companion.scene_index,
                        source_id=companion.source_id,
                        title=companion.title,
                        media_file=companion_file,
                        media_url=_media_url(companion.normalized_path),
                        start=companion_start,
                        end=companion_end,
                        duration=companion_end - companion_start,
                        opacity=min(
                            0.88,
                            0.40
                            + section.energy * 0.34
                            + layer_index * 0.05,
                        ),
                        blend_mode=blend_modes[
                            (shot_ordinal + layer_index) % len(blend_modes)
                        ],
                    )
                )

            composition_mode = _composition_mode(
                section.label,
                section.energy,
                shot_ordinal,
                desired_layers,
                section.vibe,
                diversity=comp_diversity,
                preferred=(advice.get("composition_mode") or (section.ai_direction.preferred_composition if section.ai_direction is not None else None)),
            )
            selections.append(
                SceneSelection(
                    section_index=section.index,
                    time=shot_start,
                    term=term,
                    motif_id=motif_id,
                    occurrence=occurrence,
                    clip_id=selected.clip_id,
                    scene_id=selected.scene_id,
                    scene_index=selected.scene_index,
                    source_id=selected.source_id,
                    title=selected.title,
                    media_file=media_file,
                    media_url=_media_url(selected.normalized_path),
                    start=source_start,
                    end=source_end,
                    duration=source_end - source_start,
                    crossfade_seconds=min(
                        max(0.0, cfg.crossfade_seconds),
                        max(0.0, shot_duration * 0.32),
                    ),
                    opacity=min(1.0, max(0.0, cfg.opacity)),
                    intent_query=query,
                    semantic_score=float(
                        shot_scores.get(selected.scene_id, 0.0)
                        if selected.scene_id in shot_scores
                        else semantic_scores.get(selected.scene_id, 0.0)
                    ),
                    direction=direction,
                    composition_mode=composition_mode,
                    layers=composite_layers,
                    ai_consultant={
                        "enabled": bool(consultant_advice),
                        "preferred_scene_ids": list((advice or {}).get("preferred_scene_ids") or []),
                        "selected_was_preferred": selected.scene_id in set((advice or {}).get("preferred_scene_ids") or []),
                        "effect_family": (advice or {}).get("effect_family"),
                        "preferred_effects": list((advice or {}).get("preferred_effects") or []),
                        "effect_bias": float((advice or {}).get("effect_bias", 1.0) or 1.0),
                        "composition_mode": (advice or {}).get("composition_mode"),
                        "history_mode": (advice or {}).get("history_mode", "auto"),
                        "hero_kind": (advice or {}).get("hero_kind"),
                        "reason": (advice or {}).get("reason", ""),
                    } if advice else {},
                )
            )
            previous_primary = selected

    return selections


def attach_scene_plan(
    timeline: DirectedTimeline,
    library: ClipLibrary,
    config: SceneSelectorConfig | None = None,
    *,
    progress=print,
) -> DirectedTimeline:
    cfg = config or SceneSelectorConfig()
    plan = build_scene_plan(timeline, library, cfg, progress=progress)
    section_map = {section.index: section for section in timeline.track.sections}
    plan = promote_hero_effects(
        plan,
        section_map,
        track_duration=timeline.track.duration,
        frequency=max(0.0, cfg.hero_frequency),
    )
    plan = apply_temporal_persistence(
        plan,
        section_map,
        persistence=max(0.0, cfg.temporal_persistence),
    )
    non_scene_cues = [
        cue for cue in timeline.cues
        if cue.action not in {"play_scene", "crossfade_scene"}
    ]
    for index, selection in enumerate(plan):
        non_scene_cues.append(
            VisualCue(
                time=selection.time,
                action="play_scene" if index == 0 else "crossfade_scene",
                parameters=selection.model_dump(mode="json"),
            )
        )
        # Export the most important continuous-director curves as timed pulses
        # too. The browser consumes the full curves directly; the native
        # renderer consumes these cue-compatible approximations.
        shot_end = (
            plan[index + 1].time
            if index + 1 < len(plan)
            else timeline.track.duration
        )
        span = max(0.05, shot_end - selection.time)
        cue_map = {
            "spectral_warp": "video_edit_ripple",
            "chromatic": "video_edit_chroma_delay",
            "flow": "video_edit_vortex",
            "bloom": "energy_bloom",
        }
        for curve_name, action in cue_map.items():
            points = selection.direction.automation.get(curve_name, [])
            if not points:
                continue
            peak_progress, peak_amount = max(points, key=lambda point: point[1])
            if peak_amount <= 0.025:
                continue
            non_scene_cues.append(
                VisualCue(
                    time=min(shot_end - 1e-4, selection.time + span * peak_progress),
                    action=action,
                    parameters={"amount": float(peak_amount), "directed": True},
                )
            )
        # Native Phase-1 fallback for vector scene-graph effects. Browser
        # rendering consumes the full vector primitives; native rendering gets
        # musically equivalent raster deformation pulses until the GPU/vector
        # native path reaches feature parity.
        vector_fallback = {
            "contours": "harmonic_warp",
            "semantic_outline": "harmonic_warp",
            "flow_ribbons": "video_edit_vortex",
            "flow_particles": "video_edit_vortex",
            "vector_echo": "video_edit_chroma_delay",
            "perspective_grid": "video_edit_ripple",
            "delaunay_fracture": "video_edit_ripple",
            "voronoi": "video_edit_chroma_delay",
            "portal": "energy_bloom",
            "motif_glyph": "harmonic_warp",
            "motion_transplant": "video_edit_vortex",
            "vector_displacement": "video_edit_ripple",
        }
        for effect in selection.direction.vector_effects:
            action = vector_fallback.get(effect.kind)
            if not action:
                continue
            points = effect.automation.get("amount", [])
            if points:
                peak_progress, peak_amount = max(points, key=lambda point: point[1])
            else:
                peak_progress, peak_amount = 0.75, effect.amount
            if peak_amount <= 0.025:
                continue
            non_scene_cues.append(
                VisualCue(
                    time=min(shot_end - 1e-4, selection.time + span * peak_progress),
                    action=action,
                    parameters={
                        "amount": float(min(1.0, peak_amount * 0.65)),
                        "directed": True,
                        "vector_fallback": effect.kind,
                    },
                )
            )
        codec_fallback = {
            "datamosh": "video_edit_datamosh",
            "mv_feedback": "video_edit_datamosh",
            "mv_explode": "video_edit_ripple",
            "mv_implode": "video_edit_ripple",
            "mv_radial_wave": "video_edit_ripple",
            "mv_spiral": "video_edit_vortex",
            "mv_jitter": "video_edit_chroma_delay",
            "mv_wave": "video_edit_ripple",
            "mv_drift": "video_edit_vortex",
            "mv_shear": "video_edit_ripple",
            "mv_freeze": "video_edit_datamosh",
            "mv_invert": "video_edit_chroma_delay",
        }
        for effect in selection.direction.codec_effects:
            action = codec_fallback.get(effect.kind)
            if not action or effect.amount <= 0.025:
                continue
            progress = min(1.0, max(0.0, (effect.start + effect.end) * .5))
            non_scene_cues.append(
                VisualCue(
                    time=min(shot_end - 1e-4, selection.time + span * progress),
                    action=action,
                    parameters={
                        "amount": float(min(1.0, effect.amount * .72)),
                        "directed": True,
                        "codec_fallback": effect.kind,
                    },
                )
            )
    non_scene_cues.sort(key=lambda cue: (cue.time, cue.action))

    section_by_index = {section.index: section for section in timeline.track.sections}
    intents = []
    for selection in plan:
        section = section_by_index[selection.section_index]
        intents.append(
            SceneIntent(
                section_index=section.index,
                query=selection.intent_query or selection.term,
                concepts=[selection.term, section.label, section.vibe],
                section_label=section.label,
                vibe=section.vibe,
                key=section.key,
                energy=section.energy,
                local_tempo_bpm=section.local_tempo_bpm,
                bass_weight=section.bass_weight,
                percussive_ratio=section.percussive_ratio,
                motif_id=selection.motif_id,
            )
        )

    result = timeline.model_copy(
        update={
            "cues": non_scene_cues,
            "scene_plan": plan,
            "scene_intents": intents,
        }
    )
    result = attach_transform_plan(
        result,
        TransformConfig(enabled=cfg.transforms, intensity=cfg.transform_intensity, density=cfg.effect_density),
    )
    return attach_edit_plan(
        result,
        EditConfig(enabled=cfg.transforms, intensity=cfg.transform_intensity),
    )
