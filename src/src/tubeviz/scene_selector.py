from __future__ import annotations

import hashlib
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import numpy as np

from .library import ClipLibrary, SceneCandidate
from .models import CompositeLayer, DirectedTimeline, SceneIntent, SceneSelection, VisualCue
from .transforms import TransformConfig, attach_transform_plan
from .editing import EditConfig, attach_edit_plan
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
    max_video_layers: int = 3
    composition_intensity: float = 1.0
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


def _media_file(normalized_path: str) -> str:
    path = Path(normalized_path)
    parts = path.parts
    if parts and parts[0] == "normalized":
        path = Path(*parts[1:])
    return path.as_posix()


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


def _composition_mode(
    label: str,
    energy: float,
    section_index: int,
    layers: int,
    vibe: str = "neutral",
) -> str:
    """Use full-frame/organic composites; avoid boxed PiP/mosaic layouts."""
    if layers <= 1:
        return "single"
    if label in {"ambient", "breakdown"} or vibe in {"ambient", "hypnotic", "dark"}:
        return "flow"
    if label == "drive":
        return "luma" if section_index % 2 == 0 else "flow"
    if label == "build":
        return "flow" if section_index % 2 == 0 else "strips"
    if label == "peak":
        return ("luma", "strips", "flow")[section_index % 3]
    return "flow"


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
    """Musically sensible shot density from section energy and vibe."""
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



def build_scene_plan(
    timeline: DirectedTimeline,
    library: ClipLibrary,
    config: SceneSelectorConfig | None = None,
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
    available_clip_count = len({candidate.clip_id for candidate in global_candidates})
    target_unique_clips = _auto_unique_target(
        timeline.track.duration, available_clip_count, cfg
    )

    all_candidates: list[SceneCandidate] | None = None
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

    shot_ordinal = 0
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

        windows = _shot_windows(timeline, section, cfg)
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
            selected = _choose_scene(
                candidates,
                target_duration=shot_duration,
                salt=salt,
                recent_scene_ids=set(recent_scenes),
                recent_clip_ids=set(recent_clips),
                semantic_scores=semantic_scores,
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
                    candidate.scene_id: metadata_semantic_score(candidate, query)
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
            source_start, source_end = _excerpt(
                selected,
                shot_duration,
                f"{cfg.selection_seed}:{salt}:primary",
                cfg,
            )

            layer_budget = max(1, min(4, int(cfg.max_video_layers)))
            comp_strength = max(0.0, min(2.0, cfg.composition_intensity))
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
                        media_url=f"/media/{quote(companion_file)}",
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
                    media_url=f"/media/{quote(media_file)}",
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
                        semantic_scores.get(selected.scene_id, 0.0)
                    ),
                    composition_mode=composition_mode,
                    layers=composite_layers,
                )
            )

    return selections


def attach_scene_plan(
    timeline: DirectedTimeline,
    library: ClipLibrary,
    config: SceneSelectorConfig | None = None,
) -> DirectedTimeline:
    cfg = config or SceneSelectorConfig()
    plan = build_scene_plan(timeline, library, cfg)
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
        TransformConfig(enabled=cfg.transforms, intensity=cfg.transform_intensity),
    )
    return attach_edit_plan(
        result,
        EditConfig(enabled=cfg.transforms, intensity=cfg.transform_intensity),
    )
