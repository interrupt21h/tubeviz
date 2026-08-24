# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
import secrets
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .analysis import AnalysisConfig, analyze_track
from .director import direct
from .ingest import IngestConfig, ingest_terms, read_search_terms
from .library import ClipLibrary
from .server import create_app
from .gui import create_gui_app
from .scene_selector import SceneSelectorConfig, attach_scene_plan
from .semantic import SemanticConfig, index_scene_embeddings
from .models import DirectedTimeline
from .transforms import MaterializeConfig, TransformConfig, materialize_timeline
from .render import RenderConfig, RenderError, render_timeline
from .native_render import (
    NativeRenderConfig,
    NativeRenderError,
    build_native_renderer,
    find_native_renderer,
    native_doctor,
    render_timeline_native,
)
from .youtube import YouTubeSource
from .visual_features import VisualFeatureConfig, index_scene_visual_features
from .audio_ai import AudioAIConfig, attach_audio_semantics, audio_ai_doctor
from .ai_music_director import AIDirectorConfig, attach_llm_directions, attach_semantic_directions
from .codec_glitch import (
    CodecGlitchConfig, CodecGlitchError, codec_doctor,
    index_codec_motion_features, materialize_codec_timeline,
)


def _cmd_analyze(args: argparse.Namespace) -> None:
    if getattr(args, "ai_director", False) and not getattr(args, "audio_ai", False):
        raise SystemExit("--ai-director requires --audio-ai so the whole-song plan is grounded in CLAP audio semantics")
    if getattr(args, "ai_director", False) and (not args.ai_director_base_url or not args.ai_director_model):
        raise SystemExit("--ai-director requires --ai-director-base-url and --ai-director-model")
    analysis = analyze_track(
        args.audio,
        AnalysisConfig(
            sample_rate=args.sample_rate,
            hop_length=args.hop_length,
            beats_per_bar=args.beats_per_bar,
            section_seconds=args.section_seconds,
            section_bars=args.section_bars,
            tempo_window_seconds=args.tempo_window_seconds,
            tempo_smoothing_seconds=args.tempo_smoothing_seconds,
            tempo_curve_seconds=args.tempo_curve_seconds,
            tempo_change_bpm=args.tempo_change_bpm,
            min_tempo=args.min_tempo,
            max_tempo=args.max_tempo,
            tempo_octave_min=args.tempo_octave_min,
            tempo_octave_max=args.tempo_octave_max,
        ),
    )
    if getattr(args, "audio_ai", False):
        analysis = attach_audio_semantics(
            analysis,
            args.audio,
            config=AudioAIConfig(
                model=args.audio_ai_model,
                device=args.audio_ai_device,
                window_seconds=args.audio_ai_window,
                hop_seconds=args.audio_ai_hop,
                batch_size=args.audio_ai_batch_size,
                temperature=args.audio_ai_temperature,
                cache_dir=args.audio_ai_cache_dir,
                force=args.audio_ai_force,
            ),
        )
        # CLAP semantics always get a deterministic section-level direction.
        analysis = attach_semantic_directions(analysis)
        if getattr(args, "ai_director", False):
            analysis = attach_llm_directions(
                analysis,
                config=AIDirectorConfig(
                    enabled=True,
                    base_url=args.ai_director_base_url,
                    model=args.ai_director_model,
                    api_key=args.ai_director_api_key,
                    timeout=args.ai_director_timeout,
                    cache_dir=args.ai_director_cache_dir,
                    force=args.ai_director_force,
                    semantic_strength=args.ai_director_strength,
                ),
            )
    timeline = direct(analysis)
    if args.library:
        library = ClipLibrary(args.library)
        library.initialize()
        timeline = attach_scene_plan(
            timeline,
            library,
            _selector_config(args),
        )
    output = Path(args.output).expanduser()
    output.write_text(timeline.model_dump_json(indent=2))
    tempo_values = sorted(point.bpm for point in analysis.tempo_curve)
    if len(tempo_values) >= 5:
        lo = tempo_values[int(len(tempo_values) * .10)]
        hi = tempo_values[min(len(tempo_values) - 1, int(len(tempo_values) * .90))]
        tempo_summary = f"{lo:.1f}-{hi:.1f} BPM variable" if hi - lo >= 3.0 else f"{analysis.tempo_bpm:.2f} BPM"
    else:
        tempo_summary = f"{analysis.tempo_bpm:.2f} BPM"
    vibes = sorted({section.vibe for section in analysis.sections})
    unique_sources = len({
        selection.clip_id
        for selection in timeline.scene_plan
    })
    all_source_ids = {
        selection.clip_id
        for selection in timeline.scene_plan
    }
    for selection in timeline.scene_plan:
        all_source_ids.update(layer.clip_id for layer in selection.layers)
    codec_shots = sum(bool(selection.direction.codec_effects) for selection in timeline.scene_plan)
    codec_effects = sum(len(selection.direction.codec_effects) for selection in timeline.scene_plan)
    audio_ai_sections = sum(bool(section.audio_semantics) for section in analysis.sections)
    ai_directed_sections = sum(section.ai_direction is not None for section in analysis.sections)
    print(
        f"Wrote {output}: "
        f"{analysis.duration:.1f}s, {tempo_summary}, "
        f"{len(analysis.events)} musical events, {len(timeline.cues)} visual cues, "
        f"{len(timeline.motifs)} recurring motifs, "
        f"{len(timeline.scene_plan)} planned shots, "
        f"{unique_sources} unique primary clips/{len(all_source_ids)} including companions, "
        f"codec_fx={codec_effects} across {codec_shots} shots, "
        f"audio_ai_sections={audio_ai_sections} ai_directed_sections={ai_directed_sections}, "
        f"vibes={','.join(vibes) if vibes else '-'}"
    )


def _cmd_ingest(args: argparse.Namespace) -> None:
    terms = read_search_terms(args.terms)
    if not terms:
        raise SystemExit(f"No search terms found in {args.terms}")

    library = ClipLibrary(args.library)
    source = YouTubeSource(
        quiet=not args.verbose_ytdlp,
        cookies_from_browser=args.cookies_from_browser,
        socket_timeout=args.download_socket_timeout,
        concurrent_fragments=args.concurrent_fragments,
        retries=args.download_retries,
        fragment_retries=args.fragment_retries,
    )
    summary = ingest_terms(
        terms,
        library,
        config=IngestConfig(
            results_per_term=args.results_per_term,
            min_duration=args.min_duration,
            preferred_max_duration=args.preferred_max_duration,
            hard_max_duration=args.hard_max_duration,
            search_pool=args.search_pool,
            max_search_pool=args.max_search_pool,
            search_pool_step=args.search_pool_step,
            min_width=args.min_width,
            normalize_width=args.width,
            normalize_height=args.height,
            normalize_fps=args.fps,
            scene_threshold=args.scene_threshold,
            min_scene_seconds=args.min_scene_seconds,
            keep_audio=args.keep_audio,
            detect_scenes=not args.no_scenes,
            force=args.force,
            ai_discovery=args.ai_discovery,
            ai_query_expansion=args.ai_query_expansion,
            ai_query_count=args.ai_query_count,
            ai_candidates_per_term=args.ai_candidates_per_term,
            ai_model=args.ai_model,
            ai_pretrained=args.ai_pretrained,
            ai_device=args.ai_device,
            ai_batch_size=args.ai_batch_size,
            ai_diversity_weight=args.ai_diversity_weight,
            ai_near_duplicate_threshold=args.ai_near_duplicate_threshold,
            ai_negative_weight=args.ai_negative_weight,
            ai_metadata_weight=args.ai_metadata_weight,
            ai_min_score=args.ai_min_score,
            ai_negative_concepts=tuple(
                x.strip() for x in args.ai_negative_concepts.split(",") if x.strip()
            ),
            ai_llm_base_url=args.ai_llm_base_url,
            ai_llm_model=args.ai_llm_model,
            ai_llm_api_key=args.ai_llm_api_key,
            ai_index_scenes=args.ai_index_scenes,
            visual_index_scenes=args.visual_index_scenes,
        ),
        source=source,
    )
    print(
        "Ingest complete: "
        f"terms={summary.terms} discovered={summary.discovered} accepted={summary.accepted} "
        f"existing={summary.skipped_existing} rejected={summary.rejected} "
        f"downloaded={summary.downloaded} ready={summary.ready} failed={summary.failed} "
        f"blocked_403={summary.blocked_403} unavailable={summary.unavailable} "
        f"metadata_error={summary.metadata_error} download_error={summary.download_error} "
        f"live_stream={summary.live_stream} no_finite_format={summary.no_finite_format} "
        f"ai_queries={summary.ai_queries} ai_scored={summary.ai_scored} ai_rejected={summary.ai_rejected} "
        f"ai_scene_embeddings={summary.ai_scene_embeddings} "
        f"visual_feature_scenes={summary.visual_feature_scenes} "
        f"manual_rejected={summary.manual_rejected} "
        f"quota_shortfall={summary.quota_shortfall} scenes={summary.scenes}"
    )
    print(f"Library: {library.root}")
    print(f"Database: {library.db_path}")


def _cmd_library_list(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    rows = library.list_clips(
        status=args.status,
        term=args.term,
        source=args.source,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    if not rows:
        print("No clips matched.")
        return
    print("STATUS            SCENES  EMBED  SOURCE ID        DURATION   TITLE")
    for row in rows:
        duration = (
            f"{float(row['duration']):7.1f}s"
            if row["duration"] is not None else "       -"
        )
        print(
            f"{row['status'][:16]:16}  "
            f"{row['scene_count']:6d}  "
            f"{row['embedded_scene_count']:5d}  "
            f"{row['source_id'][:16]:16}  "
            f"{duration:>9}  "
            f"{str(row['title'] or '')[:80]}"
        )


def _cmd_library_show(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    details = library.clip_details(args.source, args.source_id)
    if details is None:
        raise SystemExit(f"clip not found: {args.source}:{args.source_id}")
    if args.json:
        print(json.dumps(details, indent=2, ensure_ascii=False))
        return

    print(f"{details['source']}:{details['source_id']}  [{details['status']}]")
    print(f"title: {details['title'] or '-'}")
    print(f"channel: {details['channel'] or '-'}")
    print(f"duration: {details['duration'] if details['duration'] is not None else '-'}")
    print(f"dimensions: {details['width'] or '-'}x{details['height'] or '-'}")
    print(f"scenes: {details['scene_count']}  embedded: {details['embedded_scene_count']}")
    print(f"original: {details['original_path'] or '-'}")
    print(f"normalized: {details['normalized_path'] or '-'}")
    print(f"info-json: {details['info_json_path'] or '-'}")
    print(f"error/reason: {details['error'] or '-'}")
    if details["terms"]:
        print("terms:")
        for item in details["terms"]:
            print(f"  rank={item['rank']!s:>4}  {item['term']}")
    if details["duplicate_aliases"]:
        print("duplicate aliases:")
        for item in details["duplicate_aliases"]:
            print(f"  {item['source']}:{item['source_id']} [{item['status']}] {item['title'] or ''}")
    ai = details["metadata"]
    if "_tubeviz_ai_score" in ai:
        print(
            "AI: "
            f"score={float(ai.get('_tubeviz_ai_score', 0)):+.3f} "
            f"visual={float(ai.get('_tubeviz_ai_visual_score', 0)):+.3f} "
            f"negative={float(ai.get('_tubeviz_ai_negative_score', 0)):+.3f} "
            f"diversity={float(ai.get('_tubeviz_ai_diversity_penalty', 0)):.3f}"
        )


def _cmd_library_reject(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    try:
        record = library.reject_clip(
            args.source,
            args.source_id,
            reason=args.reason or "manually rejected",
        )
    except KeyError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"Rejected {record.source}:{record.source_id}; files retained. "
        "Future ingest will skip this clip until restored."
    )


def _cmd_library_restore(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    try:
        record = library.restore_clip(args.source, args.source_id)
    except KeyError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"Restored {record.source}:{record.source_id} -> status={record.status}"
    )


def _cmd_library_delete(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    try:
        plan = library.delete_clip(
            args.source,
            args.source_id,
            dry_run=True,
            keep_original=args.keep_original,
        )
    except KeyError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        f"Delete plan for {args.source}:{args.source_id}: "
        f"{len(plan['records'])} DB record(s), {len(plan['files'])} tracked path(s)"
    )
    for record in plan["records"]:
        print(f"  record: {record['source']}:{record['source_id']}")
    for path in plan["files"]:
        print(f"  file:   {path}")
    if args.keep_original:
        print("  original source media will be retained")

    if args.dry_run:
        print("Dry run only; nothing deleted.")
        return

    if not args.yes:
        answer = input("Permanently delete this clip and tracked derived files? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled.")
            return

    plan = library.delete_clip(
        args.source,
        args.source_id,
        dry_run=False,
        keep_original=args.keep_original,
    )
    print(
        f"Deleted {len(plan['records'])} DB record(s) and "
        f"{len(plan['files'])} tracked path(s)."
    )


def _cmd_library_stats(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    stats = library.stats()
    print(" ".join(f"{key}={value}" for key, value in sorted(stats.items())))


def _cmd_library_visual_index(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    count = index_scene_visual_features(
        library,
        clip_id=args.clip_id,
        force=args.force,
        config=VisualFeatureConfig(
            width=args.width,
            height=args.height,
            fps=args.fps,
            max_frames=args.max_frames,
        ),
    )
    print(f"Visual features indexed: {count}")


def _cmd_library_ai_report(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    rows = library.ai_report(term=args.term, limit=args.limit)
    if not rows:
        print("No persisted AI discovery scores found.")
        return
    print("SCORE   VISUAL  NEG     DIV     STATUS        SOURCE ID       TITLE")
    for row in rows:
        print(
            f"{float(row['score'] or 0):+0.3f}  "
            f"{float(row['visual'] or 0):+0.3f}  "
            f"{float(row['negative'] or 0):+0.3f}  "
            f"{float(row['diversity'] or 0):0.3f}  "
            f"{row['status'][:12]:12}  "
            f"{row['source_id'][:15]:15} "
            f"{str(row['title'] or '')[:72]}"
        )


def _cmd_library_embed(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    summary = index_scene_embeddings(
        library,
        config=SemanticConfig(
            model=args.model,
            pretrained=args.pretrained,
            device=args.device,
            batch_size=args.batch_size,
        ),
        force=args.force,
    )
    print(
        "Embedding complete: "
        f"total_scenes={summary.total_scenes} indexed={summary.indexed} "
        f"existing={summary.skipped_existing} "
        f"missing_thumbnails={summary.missing_thumbnails}"
    )


def _selector_config(args: argparse.Namespace) -> SceneSelectorConfig:
    seed = int(getattr(args, "selection_seed", 0) or 0)
    if getattr(args, "reshuffle", False):
        seed = secrets.randbits(63) or 1
        print(f"Scene selection seed: {seed}")
    return SceneSelectorConfig(
        crossfade_seconds=args.scene_crossfade,
        opacity=args.clip_opacity,
        min_scene_seconds=args.min_play_scene_seconds,
        semantic=getattr(args, "semantic", False),
        semantic_model=getattr(args, "semantic_model", "ViT-B-32"),
        semantic_pretrained=getattr(
            args, "semantic_pretrained", "laion2b_s34b_b79k"
        ),
        semantic_device=getattr(args, "semantic_device", "auto"),
        transforms=not getattr(args, "no_transforms", False),
        transform_intensity=getattr(args, "transform_intensity", 1.0),
        max_video_layers=getattr(args, "max_video_layers", 3),
        composition_intensity=getattr(args, "composition_intensity", 1.0),
        selection_seed=seed,
        selection_variation=max(0.0, getattr(args, "selection_variation", 0.30)),
        target_unique_clips=max(0, getattr(args, "target_unique_clips", 0)),
        novelty_weight=max(0.0, getattr(args, "novelty_weight", 0.65)),
        novelty_candidate_fraction=min(
            1.0, max(0.05, getattr(args, "novelty_candidate_fraction", 0.30))
        ),
        clip_reuse_cooldown=max(0, getattr(args, "clip_reuse_cooldown", 20)),
        scene_reuse_cooldown=max(0, getattr(args, "scene_reuse_cooldown", 48)),
        dynamic_shots=getattr(args, "dynamic_shots", True),
        min_shot_seconds=max(0.1, getattr(args, "min_shot_seconds", 0.65)),
        max_shot_seconds=max(0.1, getattr(args, "max_shot_seconds", 6.0)),
        source_excerpt_max_seconds=max(
            0.1, getattr(args, "source_excerpt_max_seconds", 5.0)
        ),
        visual_match_weight=max(0.0, getattr(args, "visual_match_weight", 1.25)),
        transition_weight=max(0.0, getattr(args, "transition_weight", 0.70)),
        rhythm_alignment=getattr(args, "rhythm_alignment", True),
        visual_auto_index=getattr(args, "visual_auto_index", True),
        vector_effects=getattr(args, "vector_effects", True),
        vector_intensity=max(0.0, getattr(args, "vector_intensity", 1.0)),
        codec_glitch_mode=getattr(args, "codec_glitch", "off"),
        codec_glitch_intensity=max(0.0, getattr(args, "codec_glitch_intensity", 0.65)),
        audio_visual_match_weight=max(0.0, getattr(args, "audio_visual_match_weight", 1.10)),
    )



def _cmd_materialize(args: argparse.Namespace) -> None:
    timeline_path = Path(args.timeline).expanduser().resolve()
    timeline = DirectedTimeline.model_validate_json(timeline_path.read_text())
    library = ClipLibrary(args.library)
    library.initialize()
    if not timeline.scene_plan:
        raise SystemExit("timeline has no scene plan; run tubeviz analyze --library ... first")
    rendered = materialize_timeline(
        timeline,
        library_root=library.root,
        config=MaterializeConfig(
            width=args.width, height=args.height, fps=args.fps,
            crf=args.crf, preset=args.preset,
        ),
        force=args.force,
    )
    output = Path(args.output).expanduser()
    output.write_text(rendered.model_dump_json(indent=2))
    materialized = sum(1 for scene in rendered.scene_plan if scene.transform.materialized)
    print(f"Wrote {output}: materialized={materialized} cached_dir={library.root / 'transforms'}")

def _cmd_render(args: argparse.Namespace) -> None:
    render_timeline_path = args.timeline
    if getattr(args, "codec_materialize", False):
        source_path = Path(args.timeline).expanduser().resolve()
        source_timeline = DirectedTimeline.model_validate_json(source_path.read_text())
        library = ClipLibrary(args.library)
        library.initialize()
        try:
            source_timeline = materialize_codec_timeline(
                source_timeline, library_root=library.root,
                config=CodecGlitchConfig(
                    ffedit=args.codec_ffedit, ffmpeg=args.codec_ffmpeg,
                    width=args.codec_width, height=args.codec_height, fps=args.codec_fps,
                    qscale=args.codec_qscale, gop=args.codec_gop, threads=args.codec_threads,
                    output_crf=args.codec_crf, output_preset=args.codec_preset,
                ),
                force=args.codec_force,
            )
        except CodecGlitchError as exc:
            raise SystemExit(f"codec materialize failed: {exc}") from exc
        codec_timeline = Path(args.codec_timeline_output).expanduser() if args.codec_timeline_output else Path(args.output).with_suffix(".codec.timeline.json")
        codec_timeline.parent.mkdir(parents=True, exist_ok=True)
        codec_timeline.write_text(source_timeline.model_dump_json(indent=2))
        render_timeline_path = str(codec_timeline)
        print(f"Codec-space timeline: {codec_timeline}")

    backend = args.backend
    if backend == "auto":
        backend = "native" if find_native_renderer(
            args.native_binary, build_dir=args.native_build_dir
        ) else "browser"
        print(f"Render backend: {backend}")

    try:
        if backend == "native":
            output = render_timeline_native(
                render_timeline_path,
                library_path=args.library,
                audio_path=args.audio,
                output_path=args.output,
                config=NativeRenderConfig(
                    width=args.width,
                    height=args.height,
                    fps=args.fps,
                    crf=args.crf,
                    preset=args.native_preset,
                    video_codec=args.video_codec,
                    pixel_format=args.pixel_format,
                    audio_codec=args.audio_codec,
                    audio_bitrate=args.audio_bitrate,
                    binary=args.native_binary,
                    build_dir=args.native_build_dir,
                    build_if_missing=args.native_build_if_missing,
                    keep_manifest=args.native_keep_manifest,
                    decoder_cache=args.native_decoder_cache,
                    threads=args.native_threads,
                ),
            )
        else:
            output = render_timeline(
                render_timeline_path,
                library_path=args.library,
                audio_path=args.audio,
                output_path=args.output,
                config=RenderConfig(
                    width=args.width,
                    height=args.height,
                    fps=args.fps,
                    crf=args.crf,
                    preset=args.preset,
                    video_codec=args.video_codec,
                    pixel_format=args.pixel_format,
                    audio_codec=args.audio_codec,
                    audio_bitrate=args.audio_bitrate,
                    frame_format=args.frame_format,
                    jpeg_quality=args.jpeg_quality,
                    browser_channel=args.browser_channel,
                    browser_executable=args.browser_executable,
                    headed=args.headed,
                    seed=args.seed,
                    page_timeout_ms=args.page_timeout * 1000,
                ),
            )
    except (RenderError, NativeRenderError, ValueError) as exc:
        raise SystemExit(f"render failed: {exc}") from exc
    print(f"Render complete: {output}")


def _codec_config_from_args(args: argparse.Namespace) -> CodecGlitchConfig:
    return CodecGlitchConfig(
        ffedit=getattr(args, "ffedit", "ffedit"),
        ffmpeg=getattr(args, "ffmpeg", "ffmpeg"),
        ffgac=getattr(args, "ffgac", None),
        width=getattr(args, "width", 1280),
        height=getattr(args, "height", 720),
        fps=float(getattr(args, "fps", 30.0)),
        qscale=getattr(args, "qscale", 3),
        gop=getattr(args, "gop", 18),
        threads=getattr(args, "threads", 0),
        output_crf=getattr(args, "crf", 18),
        output_preset=getattr(args, "preset", "fast"),
    )


def _cmd_codec_doctor(args: argparse.Namespace) -> None:
    print(json.dumps(codec_doctor(_codec_config_from_args(args)), indent=2))


def _cmd_codec_inspect(args: argparse.Namespace) -> None:
    timeline = DirectedTimeline.model_validate_json(Path(args.timeline).expanduser().read_text())
    rows = []
    for selection in timeline.scene_plan:
        if not selection.direction.codec_effects:
            continue
        rows.append({
            "time": selection.time, "source_id": selection.source_id,
            "title": selection.title, "role": selection.direction.narrative_role,
            "family": selection.direction.effect_family,
            "materialized": selection.codec_materialization.materialized,
            "effects": [e.model_dump(mode="json") for e in selection.direction.codec_effects],
        })
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No codec-space effects scheduled in this timeline.")
        return
    print("TIME     ROLE      FAMILY      MATERIALIZED  SOURCE          CODEC EFFECTS")
    for row in rows:
        effects = ", ".join(f"{e['kind']}:{e['amount']:.2f}@{e['start']:.2f}-{e['end']:.2f}" for e in row["effects"])
        print(f"{row['time']:7.2f}  {row['role'][:9]:9} {row['family'][:10]:10} {str(row['materialized']):12}  {row['source_id'][:14]:14}  {effects}")


def _cmd_codec_materialize(args: argparse.Namespace) -> None:
    timeline_path = Path(args.timeline).expanduser().resolve()
    timeline = DirectedTimeline.model_validate_json(timeline_path.read_text())
    library = ClipLibrary(args.library)
    library.initialize()
    try:
        rendered = materialize_codec_timeline(
            timeline, library_root=library.root, config=_codec_config_from_args(args),
            force=args.force,
        )
    except CodecGlitchError as exc:
        raise SystemExit(f"codec materialize failed: {exc}") from exc
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered.model_dump_json(indent=2))
    count = sum(s.codec_materialization.materialized for s in rendered.scene_plan)
    print(f"Wrote {output}: codec_materialized={count} cache={library.root / 'codec-glitch'}")


def _cmd_library_codec_motion(args: argparse.Namespace) -> None:
    library = ClipLibrary(args.library)
    library.initialize()
    try:
        count = index_codec_motion_features(
            library, clip_id=args.clip_id, force=args.force,
            config=CodecGlitchConfig(
                ffedit=args.ffedit, ffmpeg=args.ffmpeg,
                width=args.width, height=args.height, fps=args.fps,
                qscale=args.qscale, gop=args.gop, threads=args.threads,
            ),
        )
    except CodecGlitchError as exc:
        raise SystemExit(f"codec-motion indexing failed: {exc}") from exc
    print(f"Codec-motion features indexed: {count}")


def _cmd_native_build(args: argparse.Namespace) -> None:
    try:
        binary = build_native_renderer(
            build_dir=args.build_dir,
            clean=args.clean,
            jobs=args.jobs,
        )
    except NativeRenderError as exc:
        raise SystemExit(f"native build failed: {exc}") from exc
    print(f"Native renderer: {binary}")


def _cmd_native_doctor(args: argparse.Namespace) -> None:
    try:
        info = native_doctor(binary=args.binary, build_dir=args.build_dir)
    except NativeRenderError as exc:
        raise SystemExit(f"native doctor failed: {exc}") from exc
    print(json.dumps(info, indent=2))


def _cmd_serve(args: argparse.Namespace) -> None:
    if (args.reshuffle or args.selection_seed) and not args.replan_scenes:
        raise SystemExit("--selection-seed/--reshuffle require --replan-scenes for serve")
    serve_timeline_path = args.timeline
    if getattr(args, "codec_materialize", False):
        source_path = Path(args.timeline).expanduser().resolve()
        timeline = DirectedTimeline.model_validate_json(source_path.read_text())
        library = ClipLibrary(args.library or "./library")
        library.initialize()
        try:
            timeline = materialize_codec_timeline(
                timeline, library_root=library.root,
                config=CodecGlitchConfig(
                    ffedit=args.codec_ffedit, ffmpeg=args.codec_ffmpeg,
                    width=args.codec_width, height=args.codec_height, fps=args.codec_fps,
                    qscale=args.codec_qscale, gop=args.codec_gop, threads=args.codec_threads,
                    output_crf=args.codec_crf, output_preset=args.codec_preset,
                ),
                force=args.codec_force,
            )
        except CodecGlitchError as exc:
            raise SystemExit(f"codec preview materialize failed: {exc}") from exc
        preview_path = source_path.with_name(source_path.stem + ".codec-preview.json")
        preview_path.write_text(timeline.model_dump_json(indent=2))
        serve_timeline_path = str(preview_path)
        print(f"Codec preview timeline: {preview_path}")
    uvicorn.run(
        create_app(
            serve_timeline_path,
            args.audio,
            args.library,
            replan_scenes=args.replan_scenes,
            scene_config=_selector_config(args),
            replan_transforms=args.replan_transforms,
        ),
        host=args.host,
        port=args.port,
    )


def _cmd_gui(args: argparse.Namespace) -> None:
    app = create_gui_app(
        default_library=args.library,
        project_root=args.project_root,
    )
    if not args.no_open:
        url = f"http://{args.host}:{args.port}/"
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port)


def _cmd_audio_ai_doctor(args: argparse.Namespace) -> None:
    print(json.dumps(audio_ai_doctor(args.model, args.device), indent=2, sort_keys=True))


def _cmd_audio_ai_inspect(args: argparse.Namespace) -> None:
    timeline = DirectedTimeline.model_validate_json(Path(args.timeline).expanduser().read_text())
    rows = []
    for section in timeline.track.sections:
        top = sorted(section.audio_semantics.items(), key=lambda item: item[1], reverse=True)[:args.top]
        rows.append({
            "index": section.index, "start": section.start, "end": section.end,
            "label": section.label, "vibe": section.vibe,
            "confidence": section.audio_semantic_confidence,
            "entropy": section.audio_semantic_entropy,
            "concepts": top,
            "direction": section.ai_direction.model_dump(mode="json") if section.ai_direction else None,
        })
    if args.json:
        print(json.dumps({"model": timeline.track.audio_ai_model, "sections": rows}, indent=2))
        return
    print(f"Audio AI model: {timeline.track.audio_ai_model or '-'}")
    for row in rows:
        concepts = ", ".join(f"{key}:{value:.2f}" for key, value in row["concepts"]) or "-"
        direction = row["direction"] or {}
        print(
            f"{row['index']:3d} {row['start']:7.2f}-{row['end']:7.2f}s "
            f"conf={row['confidence']:.2f} H={row['entropy']:.2f} "
            f"{row['label']}/{row['vibe']} | {concepts}"
        )
        if direction:
            print(
                f"    world={direction.get('visual_world','-')} "
                f"motion={direction.get('desired_motion',0):.2f} "
                f"edit={direction.get('edit_density',0):.2f} "
                f"continuity={direction.get('continuity',0):.2f} "
                f"fx={direction.get('effect_family') or '-'}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tubeviz",
        description="Music-aware visualizer and searchable local video-clip ingestion pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Search YouTube and build/update a local clip library")
    ingest.add_argument("--terms", required=True, help="Text file containing one search term per line")
    ingest.add_argument("--library", default="./library", help="Persistent tubeviz clip library")
    ingest.add_argument("--results-per-term", type=int, default=10, help="Desired READY clips per term")
    ingest.add_argument("--search-pool", type=int, default=50, help="Initial ytsearch result window per term")
    ingest.add_argument("--max-search-pool", type=int, default=250, help="Maximum progressively expanded ytsearch window per term")
    ingest.add_argument("--search-pool-step", type=int, default=50, help="How many additional search results to request when the READY quota is not filled")
    ingest.add_argument("--min-duration", type=float, default=3.0, help="Reject shorter videos, seconds")
    ingest.add_argument("--preferred-max-duration", type=float, default=1200.0, help="Soft preference for shorter source videos; seconds; 0 disables")
    ingest.add_argument("--hard-max-duration", type=float, default=3600.0, help="Actually reject source videos longer than this; seconds; 0 disables")
    ingest.add_argument("--min-width", type=int, default=0, help="Reject videos narrower than this; 0 disables")
    ingest.add_argument("--width", type=int, default=1280, help="Normalized frame width")
    ingest.add_argument("--height", type=int, default=720, help="Normalized frame height")
    ingest.add_argument("--fps", type=int, default=30, help="Normalized frame rate")
    ingest.add_argument("--scene-threshold", type=float, default=0.40, help="FFmpeg scene score threshold")
    ingest.add_argument("--min-scene-seconds", type=float, default=1.5)
    ingest.add_argument("--keep-audio", action="store_true", help="Keep AAC audio in normalized clips")
    ingest.add_argument("--no-scenes", action="store_true", help="Skip scene detection and thumbnails")
    ingest.add_argument("--force", action="store_true", help="Redownload/renormalize already-ready clips")
    ingest.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="Pass a browser name to yt-dlp cookies-from-browser (for content you can access)",
    )
    ingest.add_argument(
        "--download-socket-timeout",
        type=float,
        default=20.0,
        help="yt-dlp network socket timeout in seconds",
    )
    ingest.add_argument(
        "--concurrent-fragments",
        type=int,
        default=4,
        help="Concurrent DASH/HLS-native fragments for finite media",
    )
    ingest.add_argument(
        "--download-retries",
        type=int,
        default=2,
        help="HTTP/extractor retry count per candidate",
    )
    ingest.add_argument(
        "--fragment-retries",
        type=int,
        default=2,
        help="Fragment retry count per candidate",
    )
    ingest.add_argument(
        "--ai-discovery",
        action="store_true",
        help="AI-rank metadata/thumbnails before downloading; requires the semantic extra",
    )
    ingest.add_argument(
        "--ai-query-expansion",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Expand each seed visual concept into diverse search queries",
    )
    ingest.add_argument("--ai-query-count", type=int, default=8)
    ingest.add_argument(
        "--ai-candidates-per-term",
        type=int,
        default=100,
        help="Broad candidate pool to rank before downloading",
    )
    ingest.add_argument("--ai-model", default="ViT-B-32")
    ingest.add_argument("--ai-pretrained", default="laion2b_s34b_b79k")
    ingest.add_argument("--ai-device", default="auto")
    ingest.add_argument("--ai-batch-size", type=int, default=32)
    ingest.add_argument("--ai-diversity-weight", type=float, default=0.28)
    ingest.add_argument(
        "--ai-near-duplicate-threshold",
        type=float,
        default=0.86,
        help="Thumbnail cosine similarity above which diversity penalties ramp sharply",
    )
    ingest.add_argument("--ai-negative-weight", type=float, default=0.45)
    ingest.add_argument("--ai-metadata-weight", type=float, default=0.22)
    ingest.add_argument(
        "--ai-min-score",
        type=float,
        default=-0.05,
        help="Discard AI-ranked candidates below this final score",
    )
    ingest.add_argument(
        "--ai-negative-concepts",
        default="talking head presenter,podcast interview,static slideshow,text only screen,logo title card,modern youtube host,powerpoint presentation",
        help="Comma-separated visual concepts to penalize",
    )
    ingest.add_argument(
        "--ai-llm-base-url",
        help="Optional OpenAI-compatible base URL, e.g. http://localhost:8000/v1",
    )
    ingest.add_argument("--ai-llm-model", help="Optional model name for AI query expansion")
    ingest.add_argument("--ai-llm-api-key", help="Optional bearer token for the LLM endpoint")
    ingest.add_argument(
        "--ai-index-scenes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Embed newly detected scenes with the already-loaded OpenCLIP model",
    )
    ingest.add_argument(
        "--visual-index-scenes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Analyze motion, palette, complexity, and visual accents for newly detected scenes",
    )
    ingest.add_argument("--verbose-ytdlp", action="store_true")
    ingest.set_defaults(func=_cmd_ingest)

    library = sub.add_parser("library", help="Inspect the local clip library")
    library_sub = library.add_subparsers(dest="library_command", required=True)
    list_cmd = library_sub.add_parser("list", help="List and filter library clips")
    list_cmd.add_argument("--library", default="./library")
    list_cmd.add_argument("--status")
    list_cmd.add_argument("--term")
    list_cmd.add_argument("--source")
    list_cmd.add_argument("--limit", type=int, default=100)
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=_cmd_library_list)

    show = library_sub.add_parser("show", help="Show one clip and its provenance/files")
    show.add_argument("source_id")
    show.add_argument("--source", default="youtube")
    show.add_argument("--library", default="./library")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=_cmd_library_show)

    reject = library_sub.add_parser(
        "reject",
        help="Non-destructively reject a clip and prevent future ingest reuse",
    )
    reject.add_argument("source_id")
    reject.add_argument("--source", default="youtube")
    reject.add_argument("--library", default="./library")
    reject.add_argument("--reason")
    reject.set_defaults(func=_cmd_library_reject)

    restore = library_sub.add_parser(
        "restore",
        help="Restore a manually rejected clip to the best usable status",
    )
    restore.add_argument("source_id")
    restore.add_argument("--source", default="youtube")
    restore.add_argument("--library", default="./library")
    restore.set_defaults(func=_cmd_library_restore)

    delete = library_sub.add_parser(
        "delete",
        help="Hard-delete a clip, duplicate aliases, and tracked derived files",
    )
    delete.add_argument("source_id")
    delete.add_argument("--source", default="youtube")
    delete.add_argument("--library", default="./library")
    delete.add_argument("--dry-run", action="store_true")
    delete.add_argument("--keep-original", action="store_true")
    delete.add_argument("-y", "--yes", action="store_true", help="Do not prompt for confirmation")
    delete.set_defaults(func=_cmd_library_delete)

    stats = library_sub.add_parser("stats", help="Show clip-library counts")
    stats.add_argument("--library", default="./library")
    stats.set_defaults(func=_cmd_library_stats)

    ai_report = library_sub.add_parser(
        "ai-report",
        help="Inspect persisted AI discovery/ranking scores",
    )
    ai_report.add_argument("--library", default="./library")
    ai_report.add_argument("--term")
    ai_report.add_argument("--limit", type=int, default=50)
    ai_report.set_defaults(func=_cmd_library_ai_report)

    visual_index = library_sub.add_parser(
        "visual-index",
        help="Index temporal visual fingerprints, palette, motion, and visual accents",
    )
    visual_index.add_argument("--library", default="./library")
    visual_index.add_argument("--clip-id", type=int)
    visual_index.add_argument("--width", type=int, default=160)
    visual_index.add_argument("--height", type=int, default=90)
    visual_index.add_argument("--fps", type=float, default=6.0)
    visual_index.add_argument("--max-frames", type=int, default=180)
    visual_index.add_argument("--force", action="store_true")
    visual_index.set_defaults(func=_cmd_library_visual_index)

    codec_motion = library_sub.add_parser(
        "codec-motion-index",
        help="Index FFglitch MPEG-4 motion-vector statistics into scene fingerprints",
    )
    codec_motion.add_argument("--library", default="./library")
    codec_motion.add_argument("--clip-id", type=int)
    codec_motion.add_argument("--ffedit", default="ffedit")
    codec_motion.add_argument("--ffmpeg", default="ffmpeg")
    codec_motion.add_argument("--width", type=int, default=320)
    codec_motion.add_argument("--height", type=int, default=180)
    codec_motion.add_argument("--fps", type=float, default=12.0)
    codec_motion.add_argument("--qscale", type=int, default=4)
    codec_motion.add_argument("--gop", type=int, default=18)
    codec_motion.add_argument("--threads", type=int, default=0)
    codec_motion.add_argument("--force", action="store_true")
    codec_motion.set_defaults(func=_cmd_library_codec_motion)

    embed = library_sub.add_parser(
        "embed",
        help="Index scene thumbnails with optional OpenCLIP visual embeddings",
    )
    embed.add_argument("--library", default="./library")
    embed.add_argument("--model", default="ViT-B-32")
    embed.add_argument("--pretrained", default="laion2b_s34b_b79k")
    embed.add_argument("--device", default="auto", help="auto, cpu, cuda, cuda:0, ...")
    embed.add_argument("--batch-size", type=int, default=32)
    embed.add_argument("--force", action="store_true")
    embed.set_defaults(func=_cmd_library_embed)

    audio_ai = sub.add_parser("audio-ai", help="CLAP audio-semantic analysis tools")
    audio_ai_sub = audio_ai.add_subparsers(dest="audio_ai_command", required=True)
    audio_ai_doc = audio_ai_sub.add_parser("doctor", help="Inspect CLAP/Transformers runtime availability")
    audio_ai_doc.add_argument("--model", default="laion/clap-htsat-fused")
    audio_ai_doc.add_argument("--device", default="auto")
    audio_ai_doc.set_defaults(func=_cmd_audio_ai_doctor)
    audio_ai_inspect = audio_ai_sub.add_parser("inspect", help="Inspect CLAP semantics and AI direction stored in a timeline")
    audio_ai_inspect.add_argument("timeline")
    audio_ai_inspect.add_argument("--top", type=int, default=5)
    audio_ai_inspect.add_argument("--json", action="store_true")
    audio_ai_inspect.set_defaults(func=_cmd_audio_ai_inspect)

    analyze = sub.add_parser("analyze", help="Analyze an audio file and build a directed timeline")
    analyze.add_argument("audio")
    analyze.add_argument("--output", "-o", default="timeline.json")
    analyze.add_argument("--sample-rate", type=int, default=22050)
    analyze.add_argument("--hop-length", type=int, default=512)
    analyze.add_argument("--beats-per-bar", type=int, default=4)
    analyze.add_argument("--section-seconds", type=float, default=16.0, help="Fallback section size when --section-bars is 0")
    analyze.add_argument("--section-bars", type=int, default=8, help="Musical phrase size in bars; 0 uses fixed --section-seconds")
    analyze.add_argument("--tempo-window-seconds", type=float, default=8.0, help="Local tempo autocorrelation window for variable-BPM tracks")
    analyze.add_argument("--tempo-smoothing-seconds", type=float, default=2.0, help="Median smoothing applied to the frame-wise tempo curve")
    analyze.add_argument("--tempo-curve-seconds", type=float, default=2.0, help="Spacing of tempo points persisted in the timeline")
    analyze.add_argument("--tempo-change-bpm", type=float, default=4.0, help="Emit tempo-change events after this local BPM shift")
    analyze.add_argument("--min-tempo", type=float, default=55.0)
    analyze.add_argument("--max-tempo", type=float, default=210.0)
    analyze.add_argument("--tempo-octave-min", type=float, default=75.0, help="Fold half-time estimates upward below this BPM; 0 disables octave folding")
    analyze.add_argument("--tempo-octave-max", type=float, default=190.0, help="Fold double-time estimates downward above this BPM")
    analyze.add_argument("--library", help="Attach a deterministic video-scene plan from this tubeviz library")
    analyze.add_argument("--scene-crossfade", type=float, default=1.25, help="Video crossfade duration in seconds")
    analyze.add_argument("--clip-opacity", type=float, default=0.92, help="Video layer opacity (0..1)")
    analyze.add_argument("--min-play-scene-seconds", type=float, default=1.0, help="Ignore indexed scenes shorter than this")
    analyze.add_argument("--semantic", action="store_true", help="Use OpenCLIP scene embeddings plus metadata for SceneIntent retrieval")
    analyze.add_argument("--semantic-model", default="ViT-B-32")
    analyze.add_argument("--semantic-pretrained", default="laion2b_s34b_b79k")
    analyze.add_argument("--semantic-device", default="auto")
    analyze.add_argument("--audio-ai", action=argparse.BooleanOptionalAction, default=False, help="Use CLAP sliding-window audio semantics to direct scene selection and effects")
    analyze.add_argument("--audio-ai-model", default="laion/clap-htsat-fused")
    analyze.add_argument("--audio-ai-device", default="auto")
    analyze.add_argument("--audio-ai-window", type=float, default=8.0, help="CLAP semantic analysis window in seconds")
    analyze.add_argument("--audio-ai-hop", type=float, default=4.0, help="CLAP semantic analysis hop in seconds")
    analyze.add_argument("--audio-ai-batch-size", type=int, default=8)
    analyze.add_argument("--audio-ai-temperature", type=float, default=0.075, help="Concept-score softmax temperature")
    analyze.add_argument("--audio-ai-cache-dir")
    analyze.add_argument("--audio-ai-force", action="store_true", help="Ignore cached CLAP analysis")
    analyze.add_argument("--audio-visual-match-weight", type=float, default=1.10, help="Weight CLAP↔OpenCLIP common-concept alignment in scene ranking")
    analyze.add_argument("--ai-director", action=argparse.BooleanOptionalAction, default=False, help="Refine CLAP section directions with a whole-song OpenAI-compatible LLM plan")
    analyze.add_argument("--ai-director-base-url", help="OpenAI-compatible base URL, e.g. http://localhost:8000/v1")
    analyze.add_argument("--ai-director-model")
    analyze.add_argument("--ai-director-api-key")
    analyze.add_argument("--ai-director-timeout", type=float, default=90.0)
    analyze.add_argument("--ai-director-cache-dir")
    analyze.add_argument("--ai-director-force", action="store_true")
    analyze.add_argument("--ai-director-strength", type=float, default=0.75, help="How strongly the whole-song LLM plan may alter the deterministic CLAP baseline")
    analyze.add_argument("--no-transforms", action="store_true", help="Disable per-scene video transform planning")
    analyze.add_argument("--transform-intensity", type=float, default=1.0, help="Transform strength; 0 disables, 1 normal, up to 2 aggressive")
    analyze.add_argument("--max-video-layers", type=int, default=3, help="Maximum simultaneous source videos per section (1..4)")
    analyze.add_argument("--composition-intensity", type=float, default=1.0, help="Multi-source compositing strength; 0 disables companions")
    analyze.add_argument("--selection-seed", type=int, default=0, help="Reproducible alternate scene-selection seed; 0 preserves the canonical cut")
    analyze.add_argument("--selection-variation", type=float, default=0.30, help="Seeded candidate variation strength; 0 changes term mapping/ties only")
    analyze.add_argument("--reshuffle", action="store_true", help="Generate and print a fresh scene-selection seed")
    analyze.add_argument("--target-unique-clips", type=int, default=0, help="Target unique source clips; 0=auto (~1 unique source per 2.4s, capped by library)")
    analyze.add_argument("--novelty-weight", type=float, default=0.65, help="Reward unseen source clips while preserving semantic relevance")
    analyze.add_argument("--visual-match-weight", type=float, default=1.25, help="Weight scene motion/color/complexity compatibility with musical state")
    analyze.add_argument("--transition-weight", type=float, default=0.70, help="Weight continuity/contrast between adjacent shots based on musical role")
    analyze.add_argument("--rhythm-alignment", action=argparse.BooleanOptionalAction, default=True, help="Phase-align natural visual motion accents to musical beats")
    analyze.add_argument("--visual-auto-index", action=argparse.BooleanOptionalAction, default=True, help="Backfill missing scene visual fingerprints before planning")
    analyze.add_argument("--vector-effects", action=argparse.BooleanOptionalAction, default=True, help="Enable vector scene-graph effects")
    analyze.add_argument("--vector-intensity", type=float, default=1.0, help="Global vector-effect strength; 0 disables, 1 normal, >1 aggressive")
    analyze.add_argument("--codec-glitch", choices=("off", "subtle", "musical", "aggressive"), default="off", help="Schedule sparse FFglitch codec-space motion-vector effects")
    analyze.add_argument("--codec-glitch-intensity", type=float, default=0.65, help="Codec-space effect strength; normally 0.35..1.0")
    analyze.add_argument("--novelty-candidate-fraction", type=float, default=0.30, help="Only explore unseen clips from this strongest semantic fraction of candidates")
    analyze.add_argument("--clip-reuse-cooldown", type=int, default=20, help="Primary/composite shot uses before a source clip is preferred again")
    analyze.add_argument("--scene-reuse-cooldown", type=int, default=48, help="Shot uses before an exact indexed scene is preferred again")
    analyze.add_argument("--dynamic-shots", action=argparse.BooleanOptionalAction, default=True, help="Subdivide musical sections into beat-aligned shots")
    analyze.add_argument("--min-shot-seconds", type=float, default=0.65, help="Minimum planned visual shot duration")
    analyze.add_argument("--max-shot-seconds", type=float, default=6.0, help="Maximum planned visual shot duration before subdivision")
    analyze.add_argument("--source-excerpt-max-seconds", type=float, default=5.0, help="Use at most this many seconds from a selected source scene before looping/reselecting")
    analyze.set_defaults(func=_cmd_analyze)

    materialize = sub.add_parser("materialize", help="Pre-render planned scene transforms with FFmpeg into a reusable cache")
    materialize.add_argument("timeline")
    materialize.add_argument("--library", default="./library")
    materialize.add_argument("--output", "-o", default="timeline.materialized.json")
    materialize.add_argument("--width", type=int, default=1280)
    materialize.add_argument("--height", type=int, default=720)
    materialize.add_argument("--fps", type=int, default=30)
    materialize.add_argument("--crf", type=int, default=20)
    materialize.add_argument("--preset", default="medium")
    materialize.add_argument("--force", action="store_true")
    materialize.set_defaults(func=_cmd_materialize)

    render = sub.add_parser(
        "render",
        help="Offline-render the complete browser visualization to a video file",
    )
    render.add_argument("timeline")
    render.add_argument("--library", default="./library")
    render.add_argument("--audio", help="Original music file; defaults to timeline track source when it exists")
    render.add_argument("--output", "-o", default="tubeviz-output.mp4")
    render.add_argument("--width", type=int, default=1920)
    render.add_argument("--height", type=int, default=1080)
    render.add_argument("--fps", type=float, default=60.0)
    render.add_argument("--video-codec", default="libx264")
    render.add_argument("--crf", type=int, default=18)
    render.add_argument("--preset", default="medium")
    render.add_argument("--pixel-format", default="yuv420p")
    render.add_argument("--audio-codec", default="aac")
    render.add_argument("--audio-bitrate", default="320k")
    render.add_argument(
        "--backend",
        choices=("auto", "native", "browser"),
        default="auto",
        help="Render backend; auto prefers the native executable when available",
    )
    render.add_argument("--native-binary", help="Explicit tubeviz-native-render executable")
    render.add_argument("--native-build-dir", help="Native CMake build directory")
    render.add_argument("--native-build-if-missing", action="store_true", help="Run CMake automatically if native backend is requested but no executable exists")
    render.add_argument("--native-keep-manifest", action="store_true", help="Keep the generated native TSV manifest beside the output video")
    render.add_argument("--native-preset", default="veryfast", help="FFmpeg encoder preset for native rendering; separate from browser --preset")
    render.add_argument("--native-decoder-cache", type=int, default=16, help="Number of native decoder contexts retained across rapid cuts")
    render.add_argument("--native-threads", type=int, default=0, help="OpenMP effect workers; 0 lets the runtime use all available cores")
    render.add_argument(
        "--frame-format",
        choices=("png", "jpeg"),
        default="png",
        help="Browser-to-FFmpeg frame transport; PNG is lossless, JPEG is faster",
    )
    render.add_argument("--jpeg-quality", type=int, default=95)
    render.add_argument(
        "--browser-channel",
        default="chrome",
        help="Playwright browser channel; chrome is recommended for H.264 media",
    )
    render.add_argument("--browser-executable", help="Explicit Chromium/Chrome executable path")
    render.add_argument("--headed", action="store_true", help="Show the render browser for debugging")
    render.add_argument("--seed", type=int, default=0x51F15E, help="Deterministic offline FX seed")
    render.add_argument("--page-timeout", type=int, default=30, help="Browser operation timeout in seconds")
    render.add_argument("--codec-materialize", action="store_true", help="Materialize scheduled FFglitch codec effects before rendering")
    render.add_argument("--codec-timeline-output", help="Where to keep the materialized codec timeline; defaults beside output")
    render.add_argument("--codec-ffedit", default="ffedit")
    render.add_argument("--codec-ffmpeg", default="ffmpeg")
    render.add_argument("--codec-width", type=int, default=1280)
    render.add_argument("--codec-height", type=int, default=720)
    render.add_argument("--codec-fps", type=float, default=30.0)
    render.add_argument("--codec-qscale", type=int, default=3)
    render.add_argument("--codec-gop", type=int, default=18)
    render.add_argument("--codec-threads", type=int, default=0)
    render.add_argument("--codec-crf", type=int, default=18)
    render.add_argument("--codec-preset", default="fast")
    render.add_argument("--codec-force", action="store_true")
    render.set_defaults(func=_cmd_render)

    codec = sub.add_parser("codec", help="FFglitch codec-space effects and motion-vector tools")
    codec_sub = codec.add_subparsers(dest="codec_command", required=True)

    codec_doctor_cmd = codec_sub.add_parser("doctor", help="Inspect ffedit/ffmpeg/ffgac availability")
    codec_doctor_cmd.add_argument("--ffedit", default="ffedit")
    codec_doctor_cmd.add_argument("--ffmpeg", default="ffmpeg")
    codec_doctor_cmd.add_argument("--ffgac")
    codec_doctor_cmd.set_defaults(func=_cmd_codec_doctor)

    codec_inspect = codec_sub.add_parser("inspect", help="Show the codec-space effect schedule embedded in a timeline")
    codec_inspect.add_argument("timeline")
    codec_inspect.add_argument("--json", action="store_true")
    codec_inspect.set_defaults(func=_cmd_codec_inspect)

    codec_mat = codec_sub.add_parser("materialize", help="Bake scheduled codec-space effects into cached MP4 shot assets")
    codec_mat.add_argument("timeline")
    codec_mat.add_argument("--library", default="./library")
    codec_mat.add_argument("--output", "-o", default="timeline.codec.json")
    codec_mat.add_argument("--ffedit", default="ffedit")
    codec_mat.add_argument("--ffmpeg", default="ffmpeg")
    codec_mat.add_argument("--ffgac")
    codec_mat.add_argument("--width", type=int, default=1280)
    codec_mat.add_argument("--height", type=int, default=720)
    codec_mat.add_argument("--fps", type=float, default=30.0)
    codec_mat.add_argument("--qscale", type=int, default=3)
    codec_mat.add_argument("--gop", type=int, default=18)
    codec_mat.add_argument("--threads", type=int, default=0)
    codec_mat.add_argument("--crf", type=int, default=18)
    codec_mat.add_argument("--preset", default="fast")
    codec_mat.add_argument("--force", action="store_true")
    codec_mat.set_defaults(func=_cmd_codec_materialize)

    native = sub.add_parser("native", help="Build and inspect the native C++ renderer")
    native_sub = native.add_subparsers(dest="native_command", required=True)

    native_build = native_sub.add_parser("build", help="Configure and build tubeviz-native-render")
    native_build.add_argument("--build-dir")
    native_build.add_argument("--clean", action="store_true")
    native_build.add_argument("--jobs", type=int)
    native_build.set_defaults(func=_cmd_native_build)

    native_doctor_cmd = native_sub.add_parser("doctor", help="Inspect native renderer/toolchain availability")
    native_doctor_cmd.add_argument("--binary")
    native_doctor_cmd.add_argument("--build-dir")
    native_doctor_cmd.set_defaults(func=_cmd_native_doctor)

    gui = sub.add_parser("gui", help="Launch the local tubeviz Studio GUI")
    gui.add_argument("--library", default="./library")
    gui.add_argument("--project-root", default=".")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=8090)
    gui.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    gui.set_defaults(func=_cmd_gui)

    serve = sub.add_parser("serve", help="Serve an analyzed timeline and browser renderer")
    serve.add_argument("timeline")
    serve.add_argument("--audio")
    serve.add_argument("--library", help="Clip library to serve and use for scene planning")
    serve.add_argument("--replan-scenes", action="store_true", help="Rebuild the scene plan from the current library even if one is embedded")
    serve.add_argument("--scene-crossfade", type=float, default=1.25, help="Video crossfade duration in seconds")
    serve.add_argument("--clip-opacity", type=float, default=0.92, help="Video layer opacity (0..1)")
    serve.add_argument("--min-play-scene-seconds", type=float, default=1.0, help="Ignore indexed scenes shorter than this")
    serve.add_argument("--semantic", action="store_true", help="Use OpenCLIP scene embeddings plus metadata for SceneIntent retrieval")
    serve.add_argument("--semantic-model", default="ViT-B-32")
    serve.add_argument("--semantic-pretrained", default="laion2b_s34b_b79k")
    serve.add_argument("--semantic-device", default="auto")
    serve.add_argument("--no-transforms", action="store_true", help="Disable transforms when replanning scenes")
    serve.add_argument("--transform-intensity", type=float, default=1.0, help="Transform strength when replanning")
    serve.add_argument("--max-video-layers", type=int, default=3, help="Maximum simultaneous source videos per section (1..4)")
    serve.add_argument("--composition-intensity", type=float, default=1.0, help="Multi-source compositing strength when replanning")
    serve.add_argument("--selection-seed", type=int, default=0, help="Reproducible alternate scene-selection seed; use with --replan-scenes")
    serve.add_argument("--selection-variation", type=float, default=0.30, help="Seeded candidate variation strength")
    serve.add_argument("--reshuffle", action="store_true", help="Generate and print a fresh scene-selection seed; use with --replan-scenes")
    serve.add_argument("--target-unique-clips", type=int, default=0, help="Target unique source clips while replanning; 0=auto")
    serve.add_argument("--novelty-weight", type=float, default=0.65)
    serve.add_argument("--visual-match-weight", type=float, default=1.25)
    serve.add_argument("--transition-weight", type=float, default=0.70)
    serve.add_argument("--rhythm-alignment", action=argparse.BooleanOptionalAction, default=True)
    serve.add_argument("--visual-auto-index", action=argparse.BooleanOptionalAction, default=True)
    serve.add_argument("--vector-effects", action=argparse.BooleanOptionalAction, default=True)
    serve.add_argument("--vector-intensity", type=float, default=1.0)
    serve.add_argument("--codec-glitch", choices=("off", "subtle", "musical", "aggressive"), default="off")
    serve.add_argument("--codec-glitch-intensity", type=float, default=0.65)
    serve.add_argument("--novelty-candidate-fraction", type=float, default=0.30)
    serve.add_argument("--clip-reuse-cooldown", type=int, default=20)
    serve.add_argument("--scene-reuse-cooldown", type=int, default=48)
    serve.add_argument("--dynamic-shots", action=argparse.BooleanOptionalAction, default=True, help="Create beat-aligned shots inside sections when replanning")
    serve.add_argument("--min-shot-seconds", type=float, default=0.65)
    serve.add_argument("--max-shot-seconds", type=float, default=6.0)
    serve.add_argument("--source-excerpt-max-seconds", type=float, default=5.0)
    serve.add_argument("--codec-materialize", action="store_true", help="Materialize scheduled FFglitch effects before starting preview")
    serve.add_argument("--codec-ffedit", default="ffedit")
    serve.add_argument("--codec-ffmpeg", default="ffmpeg")
    serve.add_argument("--codec-width", type=int, default=1280)
    serve.add_argument("--codec-height", type=int, default=720)
    serve.add_argument("--codec-fps", type=float, default=30.0)
    serve.add_argument("--codec-qscale", type=int, default=3)
    serve.add_argument("--codec-gop", type=int, default=18)
    serve.add_argument("--codec-threads", type=int, default=0)
    serve.add_argument("--codec-crf", type=int, default=18)
    serve.add_argument("--codec-preset", default="fast")
    serve.add_argument("--codec-force", action="store_true")
    serve.add_argument("--replan-transforms", action="store_true", help="Recompute transform plans for an existing scene plan")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.set_defaults(func=_cmd_serve)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
