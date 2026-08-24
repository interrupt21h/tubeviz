# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import math
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from .semantic import OpenClipEmbedder, SemanticConfig, cosine_similarity
from .youtube import SearchResult, YouTubeSource

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class DiscoveryAIConfig:
    enabled: bool = False
    query_expansion: bool = True
    query_count: int = 8
    candidates_per_term: int = 100
    model: str = "ViT-B-32"
    pretrained: str = "laion2b_s34b_b79k"
    device: str = "auto"
    batch_size: int = 32
    diversity_weight: float = 0.28
    near_duplicate_threshold: float = 0.86
    negative_weight: float = 0.45
    metadata_weight: float = 0.22
    min_ai_score: float = -0.05
    negative_concepts: tuple[str, ...] = (
        "talking head presenter",
        "podcast interview",
        "static slideshow",
        "text only screen",
        "logo title card",
        "modern youtube host",
        "powerpoint presentation",
    )
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout: float = 30.0


@dataclass(frozen=True)
class RankedCandidate:
    result: SearchResult
    ai_score: float
    visual_score: float
    negative_score: float
    metadata_score: float
    diversity_penalty: float
    thumbnail_path: Path | None


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_TOKEN_RE.findall(text.lower()))


def _overlap_score(query: str, text: str | None) -> float:
    q = _tokens(query)
    t = _tokens(text)
    if not q or not t:
        return 0.0
    return len(q & t) / math.sqrt(len(q) * len(t))


def metadata_candidate_score(result: SearchResult, seed: str) -> float:
    m = result.metadata
    query = str(m.get("_tubeviz_query") or seed)
    return (
        1.8 * _overlap_score(seed, m.get("title"))
        + 1.0 * _overlap_score(query, m.get("title"))
        + 0.45 * _overlap_score(seed, m.get("description"))
        + 0.15 * _overlap_score(seed, m.get("channel") or m.get("uploader"))
    )


def _heuristic_queries(seed: str, count: int) -> list[str]:
    variants = [
        seed,
        f"{seed} archival footage",
        f"{seed} vintage film",
        f"{seed} close up details",
        f"{seed} cinematic footage",
        f"{seed} analog VHS",
        f"{seed} industrial educational film",
        f"{seed} atmospheric footage",
        f"{seed} moving camera",
        f"{seed} raw footage no narration",
        f"{seed} 16mm film",
        f"{seed} documentary archive",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for value in variants:
        value = " ".join(value.split())
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        out.append(value)
        if len(out) >= max(1, count):
            break
    return out


def _llm_queries(seed: str, cfg: DiscoveryAIConfig) -> list[str]:
    if not cfg.llm_base_url or not cfg.llm_model:
        return []
    endpoint = cfg.llm_base_url.rstrip("/") + "/chat/completions"
    prompt = (
        "Generate diverse YouTube search queries for a video-first music visualizer. "
        "The goal is visually dynamic footage, not commentary. Return ONLY a JSON array "
        f"of {cfg.query_count} strings. Include literal, archival, detail, texture, "
        "motion-heavy, environmental, and adjacent visual interpretations. Avoid adding "
        "copyright claims or invented proper nouns.\n\n"
        f"Seed visual concept: {seed}"
    )
    payload = json.dumps({
        "model": cfg.llm_model,
        "temperature": 0.8,
        "messages": [
            {"role": "system", "content": "You generate concise visual search queries."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.llm_api_key:
        headers["Authorization"] = f"Bearer {cfg.llm_api_key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=cfg.llm_timeout) as response:
        raw = json.loads(response.read().decode("utf-8"))
    content = raw["choices"][0]["message"]["content"].strip()
    # Tolerate fenced JSON from less-strict local models.
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I)
        content = re.sub(r"\s*```$", "", content)
    values = json.loads(content)
    if not isinstance(values, list):
        return []
    return [" ".join(str(v).split()) for v in values if str(v).strip()][: cfg.query_count]


def expand_queries(seed: str, cfg: DiscoveryAIConfig, progress: Callable[[str], None] = print) -> list[str]:
    if not cfg.query_expansion:
        return [seed]
    values: list[str] = []
    if cfg.llm_base_url and cfg.llm_model:
        try:
            values.extend(_llm_queries(seed, cfg))
        except Exception as exc:
            progress(f"  AI query expansion fallback: {exc}")
    if len(values) < cfg.query_count:
        values.extend(_heuristic_queries(seed, cfg.query_count))
    seen: set[str] = set()
    unique: list[str] = []
    for value in [seed, *values]:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
        if len(unique) >= cfg.query_count:
            break
    return unique or [seed]


def discover_candidates(
    source: YouTubeSource,
    seed: str,
    cfg: DiscoveryAIConfig,
    *,
    progress: Callable[[str], None] = print,
) -> tuple[list[str], list[SearchResult]]:
    queries = expand_queries(seed, cfg, progress)
    per_query = max(5, math.ceil(max(1, cfg.candidates_per_term) / len(queries)))
    candidates: dict[str, SearchResult] = {}

    progress(f"  AI queries ({len(queries)}):")
    for query in queries:
        progress(f"    - {query}")
        for result in source.search(query, per_query):
            metadata = dict(result.metadata)
            metadata["_tubeviz_query"] = query
            metadata["_tubeviz_seed"] = seed
            candidate = SearchResult(
                source=result.source,
                source_id=result.source_id,
                url=result.url,
                rank=result.rank,
                metadata=metadata,
            )
            previous = candidates.get(result.source_id)
            if previous is None or result.rank < previous.rank:
                candidates[result.source_id] = candidate

    values = list(candidates.values())
    values.sort(key=lambda item: item.rank)
    return queries, values[: max(cfg.candidates_per_term, len(queries))]


def _thumbnail_url(result: SearchResult) -> str | None:
    thumbnails = result.metadata.get("thumbnails") or []
    best: tuple[int, str] | None = None
    for thumb in thumbnails:
        if not isinstance(thumb, dict):
            continue
        url = thumb.get("url")
        if not url:
            continue
        score = int(thumb.get("width") or 0) * int(thumb.get("height") or 0)
        if best is None or score > best[0]:
            best = (score, str(url))
    if best:
        return best[1]
    url = result.metadata.get("thumbnail")
    return str(url) if url else None


def cache_thumbnail(
    result: SearchResult,
    cache_dir: Path,
    *,
    timeout: float = 15.0,
) -> Path | None:
    url = _thumbnail_url(result)
    if not url:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{result.source_id}.jpg"
    if path.exists() and path.stat().st_size > 256:
        return path
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 tubeviz/AI-discovery",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(4 * 1024 * 1024)
        if len(data) < 256:
            return None
        path.write_bytes(data)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        return None


def _mean_query_vector(embedder: OpenClipEmbedder, queries: Iterable[str]) -> np.ndarray:
    vectors = embedder.encode_text(list(queries))
    if vectors.size == 0:
        return np.empty(0, dtype=np.float32)
    vector = np.mean(vectors, axis=0)
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 1e-12 else vector


def rank_candidates(
    candidates: list[SearchResult],
    *,
    seed: str,
    queries: list[str],
    cache_dir: Path,
    config: DiscoveryAIConfig,
    embedder: OpenClipEmbedder | None = None,
    progress: Callable[[str], None] = print,
) -> list[RankedCandidate]:
    if not candidates:
        return []

    embedder = embedder or OpenClipEmbedder(SemanticConfig(
        model=config.model,
        pretrained=config.pretrained,
        device=config.device,
        batch_size=config.batch_size,
    ))

    positive_prompts = [
        seed,
        *queries,
        f"dynamic cinematic footage of {seed}",
        f"visually interesting archival footage of {seed}",
    ]
    positive_vector = _mean_query_vector(embedder, positive_prompts)
    negative_vectors = embedder.encode_text(config.negative_concepts)

    prepared: list[tuple[SearchResult, Path, float]] = []
    missing: list[SearchResult] = []
    for result in candidates:
        path = cache_thumbnail(result, cache_dir)
        meta = metadata_candidate_score(result, seed)
        if path is None:
            missing.append(result)
        else:
            prepared.append((result, path, meta))

    vectors_by_id: dict[str, np.ndarray] = {}
    visual_by_id: dict[str, float] = {}
    negative_by_id: dict[str, float] = {}
    path_by_id: dict[str, Path] = {}

    batch_size = max(1, config.batch_size)
    for offset in range(0, len(prepared), batch_size):
        batch = prepared[offset: offset + batch_size]
        vectors = embedder.encode_images(path for _, path, _ in batch)
        for (result, path, _), vector in zip(batch, vectors, strict=True):
            vectors_by_id[result.source_id] = vector
            path_by_id[result.source_id] = path
            visual_by_id[result.source_id] = cosine_similarity(vector, positive_vector)
            if negative_vectors.size:
                negative_by_id[result.source_id] = max(
                    cosine_similarity(vector, neg) for neg in negative_vectors
                )
            else:
                negative_by_id[result.source_id] = 0.0

    base_scores: dict[str, float] = {}
    metadata_scores: dict[str, float] = {}
    for result in candidates:
        meta = metadata_candidate_score(result, seed)
        metadata_scores[result.source_id] = meta
        visual = visual_by_id.get(result.source_id, 0.0)
        negative = negative_by_id.get(result.source_id, 0.0)
        duration = result.metadata.get("duration")
        duration_bonus = 0.0
        if duration is not None:
            duration = float(duration)
            if 15 <= duration <= 600:
                duration_bonus = 0.06
            elif duration > 1800:
                duration_bonus = -0.05
        base_scores[result.source_id] = (
            visual
            - config.negative_weight * max(0.0, negative)
            + config.metadata_weight * meta
            + duration_bonus
        )

    # Greedy maximal-marginal-relevance ranking.
    remaining = list(candidates)
    selected: list[RankedCandidate] = []
    selected_vectors: list[np.ndarray] = []

    while remaining:
        best: tuple[float, SearchResult, float] | None = None
        for result in remaining:
            vector = vectors_by_id.get(result.source_id)
            diversity = 0.0
            if vector is not None and selected_vectors:
                diversity = max(cosine_similarity(vector, other) for other in selected_vectors)
            # Similar-but-not-identical footage is useful; reserve the strong
            # MMR penalty for genuinely near-duplicate thumbnails.
            threshold = min(0.999, max(0.0, config.near_duplicate_threshold))
            near_duplicate = max(0.0, diversity - threshold) / max(1e-6, 1.0 - threshold)
            score = base_scores[result.source_id] - config.diversity_weight * near_duplicate
            if best is None or score > best[0]:
                best = (score, result, diversity)
        assert best is not None
        score, result, diversity = best
        remaining.remove(result)
        vector = vectors_by_id.get(result.source_id)
        if vector is not None:
            selected_vectors.append(vector)
        selected.append(RankedCandidate(
            result=result,
            ai_score=float(score),
            visual_score=float(visual_by_id.get(result.source_id, 0.0)),
            negative_score=float(negative_by_id.get(result.source_id, 0.0)),
            metadata_score=float(metadata_scores[result.source_id]),
            diversity_penalty=float(diversity),
            thumbnail_path=path_by_id.get(result.source_id),
        ))

    progress(
        f"  AI preview ranking: {len(prepared)} thumbnails scored; "
        f"{len(missing)} without usable thumbnails"
    )
    for item in selected[: min(12, len(selected))]:
        title = str(item.result.metadata.get("title") or "")[:72]
        progress(
            f"    {item.ai_score:+.3f} visual={item.visual_score:+.3f} "
            f"neg={item.negative_score:+.3f} div={item.diversity_penalty:.3f} "
            f"{item.result.source_id} {title}"
        )
    return selected


def index_clip_scene_embeddings(
    library,
    clip_id: int,
    *,
    config: DiscoveryAIConfig,
    embedder: OpenClipEmbedder,
    progress: Callable[[str], None] = print,
) -> int:
    """Embed newly indexed scene thumbnails using the already-loaded AI model."""
    candidates = library.scene_candidates(clip_id=clip_id)
    existing = library.scene_embedding_ids(
        model=config.model,
        pretrained=config.pretrained,
    )
    pending = []
    for candidate in candidates:
        if candidate.scene_id in existing or not candidate.thumbnail_path:
            continue
        path = library.root / candidate.thumbnail_path
        if path.exists():
            pending.append((candidate, path))
    indexed = 0
    for offset in range(0, len(pending), max(1, config.batch_size)):
        batch = pending[offset: offset + max(1, config.batch_size)]
        vectors = embedder.encode_images(path for _, path in batch)
        for (candidate, _), vector in zip(batch, vectors, strict=True):
            library.store_scene_embedding(
                candidate.scene_id,
                model=config.model,
                pretrained=config.pretrained,
                vector=vector,
            )
            indexed += 1
    if indexed:
        progress(f"  AI scene embeddings: {indexed} scenes indexed")
    return indexed
