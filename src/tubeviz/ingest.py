from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .library import ClipLibrary, sha256_file
from .media import detect_scene_boundaries, make_thumbnail, normalize_video, probe, require_media_tools
from .youtube import DownloadFailure, SearchResult, YouTubeSource
from .discovery_ai import DiscoveryAIConfig, discover_candidates, rank_candidates, index_clip_scene_embeddings
from .semantic import OpenClipEmbedder, SemanticConfig
from .visual_features import index_scene_visual_features


@dataclass(frozen=True)
class IngestConfig:
    # Desired READY clips per search term, not raw search-result count.
    results_per_term: int = 10
    # Initial ytsearch pool size. If the READY quota is not filled, tubeviz
    # progressively expands the search up to max_search_pool.
    search_pool: int = 50
    max_search_pool: int = 250
    search_pool_step: int = 50
    min_duration: float = 3.0
    # Soft preference only. Longer candidates remain eligible.
    preferred_max_duration: float = 20.0 * 60.0
    # Actual rejection threshold; 0 disables it.
    hard_max_duration: float = 60.0 * 60.0
    min_width: int = 0
    normalize_width: int = 1280
    normalize_height: int = 720
    normalize_fps: int = 30
    scene_threshold: float = 0.40
    min_scene_seconds: float = 1.5
    keep_audio: bool = False
    detect_scenes: bool = True
    force: bool = False

    # AI-assisted pre-download discovery/ranking.
    ai_discovery: bool = False
    ai_query_expansion: bool = True
    ai_query_count: int = 8
    ai_candidates_per_term: int = 100
    ai_model: str = "ViT-B-32"
    ai_pretrained: str = "laion2b_s34b_b79k"
    ai_device: str = "auto"
    ai_batch_size: int = 32
    ai_diversity_weight: float = 0.28
    ai_near_duplicate_threshold: float = 0.86
    ai_negative_weight: float = 0.45
    ai_metadata_weight: float = 0.22
    ai_min_score: float = -0.05
    ai_negative_concepts: tuple[str, ...] = (
        "talking head presenter",
        "podcast interview",
        "static slideshow",
        "text only screen",
        "logo title card",
        "modern youtube host",
        "powerpoint presentation",
    )
    ai_llm_base_url: str | None = None
    ai_llm_model: str | None = None
    ai_llm_api_key: str | None = None
    ai_index_scenes: bool = True
    visual_index_scenes: bool = True


@dataclass
class IngestSummary:
    terms: int = 0
    discovered: int = 0
    accepted: int = 0
    skipped_existing: int = 0
    rejected: int = 0
    downloaded: int = 0
    ready: int = 0
    failed: int = 0
    blocked_403: int = 0
    unavailable: int = 0
    private: int = 0
    auth_required: int = 0
    metadata_error: int = 0
    download_error: int = 0
    normalize_error: int = 0
    live_stream: int = 0
    no_finite_format: int = 0
    ai_scored: int = 0
    ai_rejected: int = 0
    ai_queries: int = 0
    ai_scene_embeddings: int = 0
    visual_feature_scenes: int = 0
    scenes: int = 0
    quota_shortfall: int = 0
    manual_rejected: int = 0


def read_search_terms(path: str | Path) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if not term or term.startswith("#") or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _acceptable(result: SearchResult, cfg: IngestConfig) -> tuple[bool, str | None]:
    metadata = result.metadata

    live_reason = YouTubeSource.live_rejection_reason(metadata)
    if live_reason:
        return False, live_reason

    # Hydrated yt-dlp metadata includes formats. If an archived livestream has
    # not yielded any finite VOD representation, do not allow yt-dlp/FFmpeg to
    # fall back to an HLS manifest that can wait indefinitely for segments.
    if metadata.get("formats") and not YouTubeSource.has_finite_vod_format(metadata):
        return False, "no finite HTTP/HTTPS VOD format available"
    duration = metadata.get("duration")
    if duration is not None:
        duration = float(duration)
        if duration < cfg.min_duration:
            return False, f"duration {duration:.1f}s < {cfg.min_duration:.1f}s"
        if cfg.hard_max_duration > 0 and duration > cfg.hard_max_duration:
            return False, f"duration {duration:.1f}s > hard maximum {cfg.hard_max_duration:.1f}s"

    width = metadata.get("width")
    if width is not None and cfg.min_width and int(width) < cfg.min_width:
        return False, f"width {width} < {cfg.min_width}"
    return True, None


def _candidate_priority(result: SearchResult, cfg: IngestConfig) -> tuple[float, int, float, int]:
    """AI rank first when present, then duration/relevance policy."""
    ai_score = result.metadata.get("_tubeviz_ai_score")
    ai_key = -float(ai_score) if ai_score is not None else 0.0
    duration_raw = result.metadata.get("duration")
    duration = float(duration_raw) if duration_raw is not None else cfg.preferred_max_duration
    if cfg.preferred_max_duration <= 0:
        tier = 0
    else:
        tier = 0 if duration <= cfg.preferred_max_duration else 1
    return (ai_key, tier, max(0.0, duration), result.rank)


def _record_failure(summary: IngestSummary, status: str) -> None:
    summary.failed += 1
    if hasattr(summary, status):
        setattr(summary, status, getattr(summary, status) + 1)
    else:
        summary.download_error += 1


def _ai_config(cfg: IngestConfig) -> DiscoveryAIConfig:
    return DiscoveryAIConfig(
        enabled=cfg.ai_discovery,
        query_expansion=cfg.ai_query_expansion,
        query_count=cfg.ai_query_count,
        candidates_per_term=cfg.ai_candidates_per_term,
        model=cfg.ai_model,
        pretrained=cfg.ai_pretrained,
        device=cfg.ai_device,
        batch_size=cfg.ai_batch_size,
        diversity_weight=cfg.ai_diversity_weight,
        near_duplicate_threshold=cfg.ai_near_duplicate_threshold,
        negative_weight=cfg.ai_negative_weight,
        metadata_weight=cfg.ai_metadata_weight,
        min_ai_score=cfg.ai_min_score,
        negative_concepts=cfg.ai_negative_concepts,
        llm_base_url=cfg.ai_llm_base_url,
        llm_model=cfg.ai_llm_model,
        llm_api_key=cfg.ai_llm_api_key,
    )


def ingest_terms(
    terms: Iterable[str],
    library: ClipLibrary,
    *,
    config: IngestConfig | None = None,
    source: YouTubeSource | None = None,
    progress=print,
) -> IngestSummary:
    cfg = config or IngestConfig()
    if cfg.results_per_term < 1:
        raise ValueError("results_per_term must be >= 1")
    if cfg.search_pool < cfg.results_per_term:
        raise ValueError("search_pool must be >= results_per_term")
    if cfg.max_search_pool < cfg.search_pool:
        raise ValueError("max_search_pool must be >= search_pool")
    if cfg.search_pool_step < 1:
        raise ValueError("search_pool_step must be >= 1")

    source = source or YouTubeSource()
    library.initialize()
    require_media_tools()

    terms = list(terms)
    summary = IngestSummary(terms=len(terms))

    ai_cfg = _ai_config(cfg) if cfg.ai_discovery else None
    ai_embedder = None
    if ai_cfg is not None:
        progress(
            f"AI discovery: loading OpenCLIP {ai_cfg.model}/{ai_cfg.pretrained} "
            f"on {ai_cfg.device}"
        )
        ai_embedder = OpenClipEmbedder(SemanticConfig(
            model=ai_cfg.model,
            pretrained=ai_cfg.pretrained,
            device=ai_cfg.device,
            batch_size=ai_cfg.batch_size,
        ))

    for term_index, term in enumerate(terms, start=1):
        progress(f"[{term_index}/{len(terms)}] search: {term}")

        # Progressive discovery: ytsearchN returns the first N matches. A
        # restrictive hard-duration ceiling can eliminate most of the first
        # page, so progressively increase N and process only newly discovered
        # source IDs.
        search_limit = cfg.search_pool
        candidates_by_id: dict[str, SearchResult] = {}
        processed_ids: set[str] = set()
        term_ready = 0
        attempted = 0
        exhausted = False

        ai_initialized = False
        search_results: list[SearchResult] = []

        while term_ready < cfg.results_per_term and not exhausted:
            before = len(candidates_by_id)

            if cfg.ai_discovery and not ai_initialized:
                assert ai_cfg is not None and ai_embedder is not None
                queries, discovered = discover_candidates(
                    source, term, ai_cfg, progress=progress
                )
                summary.ai_queries += len(queries)
                summary.discovered += len({r.source_id for r in discovered})
                ranked = rank_candidates(
                    discovered,
                    seed=term,
                    queries=queries,
                    cache_dir=library.metadata_dir / "ai-thumbnails",
                    config=ai_cfg,
                    embedder=ai_embedder,
                    progress=progress,
                )
                summary.ai_scored += len(ranked)
                search_results = []
                for item in ranked:
                    metadata = dict(item.result.metadata)
                    metadata.update({
                        "_tubeviz_ai_score": item.ai_score,
                        "_tubeviz_ai_visual_score": item.visual_score,
                        "_tubeviz_ai_negative_score": item.negative_score,
                        "_tubeviz_ai_metadata_score": item.metadata_score,
                        "_tubeviz_ai_diversity_penalty": item.diversity_penalty,
                    })
                    result = SearchResult(
                        source=item.result.source,
                        source_id=item.result.source_id,
                        url=item.result.url,
                        rank=item.result.rank,
                        metadata=metadata,
                    )
                    if item.ai_score < cfg.ai_min_score:
                        summary.ai_rejected += 1
                        continue
                    search_results.append(result)
                    candidates_by_id.setdefault(result.source_id, result)
                ai_initialized = True
                progress(
                    f"  AI shortlist: {len(search_results)}/{len(ranked)} candidates "
                    f"at score >= {cfg.ai_min_score:+.2f}; target ready: {cfg.results_per_term}"
                )
            elif cfg.ai_discovery:
                exhausted = True
                search_results = []
            else:
                search_results = source.search(term, search_limit)
                for result in search_results:
                    candidates_by_id.setdefault(result.source_id, result)
                new_discovered = len(candidates_by_id) - before
                summary.discovered += new_discovered

                if before == 0:
                    progress(
                        f"  candidates discovered: {len(candidates_by_id)}; "
                        f"target ready: {cfg.results_per_term}"
                    )
                elif new_discovered:
                    progress(
                        f"  search expanded: limit={search_limit}; "
                        f"new={new_discovered}; unique={len(candidates_by_id)}"
                    )

            pending = [
                result
                for result in candidates_by_id.values()
                if result.source_id not in processed_ids
            ]
            pending.sort(key=lambda item: _candidate_priority(item, cfg))

            for result in pending:
                if term_ready >= cfg.results_per_term:
                    break

                processed_ids.add(result.source_id)
                attempted += 1

                # Manual curation is persistent and outranks both --force and
                # AI/search ranking. Re-associate the result with the current
                # term while preserving its rejected_manual status.
                manually_rejected = library.get_clip(result.source, result.source_id)
                if manually_rejected and manually_rejected.status == "rejected_manual":
                    library.upsert_discovery(
                        source=result.source,
                        source_id=result.source_id,
                        source_url=result.url,
                        term=term,
                        rank=result.rank,
                        metadata=result.metadata,
                    )
                    summary.manual_rejected += 1
                    summary.skipped_existing += 1
                    progress(
                        f"  manual reject: {result.source_id} "
                        f"{manually_rejected.title or ''}"
                    )
                    continue

                # Flat ytsearch results generally include duration. Apply an
                # obvious hard reject before hydration so short-duration runs
                # do not waste watch-page requests on long videos.
                flat_ok, flat_reason = _acceptable(result, cfg)
                if not flat_ok and result.metadata.get("duration") is not None:
                    existing_policy = library.get_clip(result.source, result.source_id)
                    clip_id = library.upsert_discovery(
                        source=result.source,
                        source_id=result.source_id,
                        source_url=result.url,
                        term=term,
                        rank=result.rank,
                        metadata=result.metadata,
                    )
                    summary.rejected += 1
                    # A per-run ingest policy must not destroy a previously READY
                    # library asset. Merely exclude it from this term's quota.
                    if not (existing_policy and existing_policy.status == "ready"):
                        library.mark_failure(
                            clip_id, "rejected", flat_reason or "rejected by ingest policy"
                        )
                    progress(f"  reject: {result.source_id}: {flat_reason}")
                    continue

                existing = library.get_clip(result.source, result.source_id)
                if existing and existing.status == "ready" and not cfg.force:
                    library.upsert_discovery(
                        source=result.source,
                        source_id=result.source_id,
                        source_url=result.url,
                        term=term,
                        rank=result.rank,
                        metadata=result.metadata,
                    )
                    summary.skipped_existing += 1
                    term_ready += 1
                    progress(
                        f"  existing ready [{term_ready}/{cfg.results_per_term}]: "
                        f"{result.source_id} {existing.title or ''}"
                    )
                    continue

                try:
                    hydrated = source.hydrate(result)
                except DownloadFailure as exc:
                    clip_id = library.upsert_discovery(
                        source=result.source,
                        source_id=result.source_id,
                        source_url=result.url,
                        term=term,
                        rank=result.rank,
                        metadata=result.metadata,
                    )
                    library.mark_failure(clip_id, exc.status, str(exc))
                    _record_failure(summary, exc.status)
                    progress(f"  {exc.status}: {result.source_id}: {exc}")
                    continue
                except Exception as exc:
                    clip_id = library.upsert_discovery(
                        source=result.source,
                        source_id=result.source_id,
                        source_url=result.url,
                        term=term,
                        rank=result.rank,
                        metadata=result.metadata,
                    )
                    library.mark_failure(clip_id, "metadata_error", str(exc))
                    _record_failure(summary, "metadata_error")
                    progress(f"  metadata_error: {result.source_id}: {exc}")
                    continue

                accepted, reason = _acceptable(hydrated, cfg)
                clip_id = library.upsert_discovery(
                    source=hydrated.source,
                    source_id=hydrated.source_id,
                    source_url=hydrated.url,
                    term=term,
                    rank=hydrated.rank,
                    metadata=hydrated.metadata,
                )
                if not accepted:
                    summary.rejected += 1
                    library.mark_failure(
                        clip_id, "rejected", reason or "rejected by ingest policy"
                    )
                    progress(f"  reject: {hydrated.source_id}: {reason}")
                    continue

                duration = hydrated.metadata.get("duration")
                if (
                    duration is not None
                    and cfg.preferred_max_duration > 0
                    and float(duration) > cfg.preferred_max_duration
                ):
                    progress(
                        f"  soft-long: {hydrated.source_id}: {float(duration):.1f}s "
                        f"> preferred {cfg.preferred_max_duration:.1f}s; "
                        "trying because quota is not filled"
                    )

                summary.accepted += 1
                record = library.get_clip_by_id(clip_id)
                original: Path | None = None
                if record and record.original_path and not cfg.force:
                    candidate = library.root / record.original_path
                    if candidate.exists():
                        original = candidate

                try:
                    if original is None:
                        progress(
                            f"  download: {hydrated.source_id} "
                            f"{hydrated.metadata.get('title', '')}"
                        )
                        original, info_json, downloaded_metadata = source.download(
                            hydrated, library.originals_dir
                        )
                        original_hash = sha256_file(original)
                        canonical = library.find_by_original_sha256(
                            original_hash, exclude_clip_id=clip_id
                        )
                        if canonical and canonical.original_path:
                            original.unlink(missing_ok=True)
                            if info_json:
                                info_json.unlink(missing_ok=True)
                            library.mark_duplicate(clip_id, canonical)
                            summary.skipped_existing += 1
                            progress(
                                f"  duplicate: {hydrated.source_id} -> clip {canonical.id}"
                            )
                            continue
                        library.mark_downloaded(
                            clip_id,
                            original_path=original,
                            info_json_path=info_json,
                            sha256=original_hash,
                        )
                        summary.downloaded += 1

                    normalized = library.normalized_dir / f"{hydrated.source_id}.mp4"
                    if cfg.force or not normalized.exists():
                        progress(f"  normalize: {hydrated.source_id}")
                        try:
                            normalize_video(
                                original,
                                normalized,
                                width=cfg.normalize_width,
                                height=cfg.normalize_height,
                                fps=cfg.normalize_fps,
                                keep_audio=cfg.keep_audio,
                            )
                        except Exception as exc:
                            library.mark_failure(clip_id, "normalize_error", str(exc))
                            _record_failure(summary, "normalize_error")
                            progress(
                                f"  normalize_error: {hydrated.source_id}: {exc}"
                            )
                            continue
                    library.mark_normalized(
                        clip_id, normalized, sha256_file(normalized)
                    )

                    if cfg.detect_scenes:
                        scene_count = _index_scenes(
                            library,
                            clip_id,
                            hydrated.source_id,
                            normalized,
                            threshold=cfg.scene_threshold,
                            min_scene_seconds=cfg.min_scene_seconds,
                        )
                        summary.scenes += scene_count
                        if cfg.visual_index_scenes and scene_count:
                            summary.visual_feature_scenes += index_scene_visual_features(
                                library,
                                clip_id=clip_id,
                                force=cfg.force,
                                progress=progress,
                            )
                        if cfg.ai_discovery and cfg.ai_index_scenes and ai_cfg is not None and ai_embedder is not None:
                            summary.ai_scene_embeddings += index_clip_scene_embeddings(
                                library,
                                clip_id,
                                config=ai_cfg,
                                embedder=ai_embedder,
                                progress=progress,
                            )
                        progress(
                            f"  ready [{term_ready + 1}/{cfg.results_per_term}]: "
                            f"{hydrated.source_id} ({scene_count} scenes)"
                        )
                    else:
                        progress(
                            f"  ready [{term_ready + 1}/{cfg.results_per_term}]: "
                            f"{hydrated.source_id}"
                        )
                    summary.ready += 1
                    term_ready += 1

                except DownloadFailure as exc:
                    library.mark_failure(clip_id, exc.status, str(exc))
                    _record_failure(summary, exc.status)
                    progress(f"  {exc.status}: {hydrated.source_id}: {exc}")
                except Exception as exc:
                    library.mark_failure(clip_id, "download_error", str(exc))
                    _record_failure(summary, "download_error")
                    progress(f"  download_error: {hydrated.source_id}: {exc}")

            if term_ready >= cfg.results_per_term:
                break

            if cfg.ai_discovery:
                exhausted = True
            elif len(search_results) < search_limit:
                exhausted = True
            elif search_limit >= cfg.max_search_pool:
                exhausted = True
            else:
                next_limit = min(
                    cfg.max_search_pool, search_limit + cfg.search_pool_step
                )
                if next_limit <= search_limit:
                    exhausted = True
                else:
                    progress(
                        f"  quota not filled ({term_ready}/{cfg.results_per_term}); "
                        f"expanding search {search_limit}->{next_limit}"
                    )
                    search_limit = next_limit

        if term_ready < cfg.results_per_term:
            shortfall = cfg.results_per_term - term_ready
            summary.quota_shortfall += shortfall
            progress(
                f"  RESULT: ready={term_ready}/{cfg.results_per_term}; "
                f"unique_searched={len(candidates_by_id)}; attempted={attempted}; "
                f"shortfall={shortfall}"
            )
        else:
            progress(
                f"  RESULT: ready={term_ready}/{cfg.results_per_term}; "
                f"unique_searched={len(candidates_by_id)}; attempted={attempted}"
            )

    return summary


def _index_scenes(
    library: ClipLibrary,
    clip_id: int,
    source_id: str,
    normalized: Path,
    *,
    threshold: float,
    min_scene_seconds: float,
) -> int:
    media = probe(normalized)
    boundaries = detect_scene_boundaries(
        normalized,
        threshold=threshold,
        min_scene_seconds=min_scene_seconds,
    )
    boundaries = sorted({0.0, *[x for x in boundaries if 0.0 < x < media.duration], media.duration})

    scenes: list[tuple[float, float, str | None]] = []
    clip_thumb_dir = library.thumbnails_dir / source_id
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if end - start < 0.05:
            continue
        thumbnail = clip_thumb_dir / f"{index:04d}.jpg"
        make_thumbnail(normalized, thumbnail, time_seconds=start + (end - start) / 2.0)
        scenes.append((start, end, str(thumbnail.relative_to(library.root))))

    library.replace_scenes(clip_id, scenes)
    return len(scenes)
