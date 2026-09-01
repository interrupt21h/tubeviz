# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json

from .library import ClipLibrary
from .semantic_compositing import SemanticAnalysisConfig, SemanticAssetStore, analyze_library_scene, iter_scene_ids
from .semantic_director import SemanticDirectionInput, direct_semantic_effects
from .semantic_entities import EntityDecompositionConfig, decompose_scene_entities
from .semantic_materialize import SemanticEffect, materialize_scene
from .semantic_pipeline import semanticize_timeline_file


def _config(args: argparse.Namespace) -> SemanticAnalysisConfig:
    return SemanticAnalysisConfig(
        sample_fps=args.sample_fps,
        mask_backend=args.mask_backend,
        depth_backend=args.depth_backend,
        sam2_model=args.sam2_model,
        video_depth_encoder=args.depth_encoder,
        video_depth_checkpoint=args.depth_checkpoint,
        device=args.device,
    )


def _entity_config(args: argparse.Namespace) -> EntityDecompositionConfig:
    labels = tuple(part.strip() for part in args.entity_labels.split(",") if part.strip())
    return EntityDecompositionConfig(
        backend=args.entity_detector,
        mask_backend=args.entity_tracker,
        detector_model=args.detector_model,
        sam2_model=args.sam2_model,
        labels=labels or EntityDecompositionConfig().labels,
        box_threshold=args.box_threshold,
        text_threshold=args.text_threshold,
        max_objects=args.max_entities,
        min_area=args.min_entity_area,
        device=args.device,
    )


def _add_analysis_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sample-fps", type=float, default=12.0)
    parser.add_argument("--mask-backend", choices=("auto", "sam2", "classical"), default="auto")
    parser.add_argument("--depth-backend", choices=("auto", "video-depth-anything", "classical"), default="auto")
    parser.add_argument("--sam2-model", default="facebook/sam2.1-hiera-small")
    parser.add_argument("--depth-encoder", choices=("vits", "vitl"), default="vits")
    parser.add_argument("--depth-checkpoint")
    parser.add_argument("--device", default="auto")


def _add_entity_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-multi-entity", action="store_true")
    parser.add_argument("--entity-detector", choices=("auto", "grounding-dino", "classical"), default="auto")
    parser.add_argument("--entity-tracker", choices=("auto", "sam2", "classical"), default="auto")
    parser.add_argument("--detector-model", default="IDEA-Research/grounding-dino-tiny")
    parser.add_argument(
        "--entity-labels",
        default="person,dancer,animal,car,vehicle,building,architecture,sky,water,tree,foreground object",
    )
    parser.add_argument("--box-threshold", type=float, default=0.30)
    parser.add_argument("--text-threshold", type=float, default=0.25)
    parser.add_argument("--max-entities", type=int, default=8)
    parser.add_argument("--min-entity-area", type=float, default=0.008)


def _cmd_index(args: argparse.Namespace) -> int:
    library = ClipLibrary(args.library)
    library.initialize()
    scene_ids = args.scene_id or list(iter_scene_ids(library, selected_only=args.selected_only))
    failures = 0
    for scene_id in scene_ids:
        try:
            result = analyze_library_scene(library, scene_id, _config(args), force=args.force)
            if not args.no_multi_entity:
                result = decompose_scene_entities(
                    library.root,
                    result,
                    _entity_config(args),
                    force=args.force,
                )
            print(json.dumps({
                "scene_id": result.scene_id,
                "mask_backend": result.mask_backend,
                "depth_backend": result.depth_backend,
                "entities": len(result.entities),
                "entity_labels": [entity.label for entity in result.entities],
                "frames": result.frame_count,
            }, sort_keys=True))
        except Exception as exc:
            failures += 1
            print(json.dumps({"scene_id": int(scene_id), "error": str(exc)}, sort_keys=True))
            if args.fail_fast:
                return 1
    return 1 if failures and failures == len(scene_ids) else 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    store = SemanticAssetStore(args.library)
    analysis = store.load(args.scene_id)
    if analysis is None:
        raise SystemExit(f"scene {args.scene_id} has not been semantically indexed")
    data = analysis.to_json()
    entity_manifest = store.scene_dir(args.scene_id) / "entities.json"
    if entity_manifest.exists():
        data["entity_manifest"] = json.loads(entity_manifest.read_text(encoding="utf-8"))
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def _cmd_materialize(args: argparse.Namespace) -> int:
    store = SemanticAssetStore(args.library)
    analysis = store.load(args.scene_id)
    if analysis is None:
        raise SystemExit(f"scene {args.scene_id} has not been semantically indexed")
    if args.auto_direct:
        effects = direct_semantic_effects(
            analysis,
            SemanticDirectionInput(
                energy=args.energy,
                bass_weight=args.bass,
                percussive_ratio=args.percussion,
                complexity=args.complexity,
                drop_probability=args.drop,
                build_probability=args.build,
            ),
        )
    else:
        effects = tuple(
            SemanticEffect(
                kind=kind,
                amount=args.amount,
                copies=args.copies,
                parallax_px=args.parallax_px,
                target_entity=args.target_entity,
                target_role=args.target_role,
                target_label=args.target_label,
                split_distance=args.split_distance,
                rotation_step=args.rotation_step,
            )
            for kind in args.effect
        )
    if not effects:
        raise SystemExit("no semantic effects were selected")
    output = materialize_scene(args.library, analysis, args.output, effects)
    print(json.dumps({
        "output": str(output),
        "scene_id": analysis.scene_id,
        "effects": [effect.__dict__ for effect in effects],
    }, indent=2, sort_keys=True))
    return 0


def _cmd_timeline(args: argparse.Namespace) -> int:
    stats = semanticize_timeline_file(
        args.timeline,
        args.library,
        args.output,
        auto_index=args.auto_index,
        force=args.force,
        multi_entity=not args.no_multi_entity,
        entity_config=_entity_config(args),
    )
    print(json.dumps({"output": args.output, **stats}, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tubeviz-semantic", description="Semantic object/depth analysis and materialization for Tubeviz")
    parser.add_argument("--library", default="./library")
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser("index", help="Generate cached masks, depth and multi-entity tracks for library scenes")
    index.add_argument("--scene-id", type=int, action="append")
    index.add_argument("--selected-only", action="store_true")
    index.add_argument("--force", action="store_true")
    index.add_argument("--fail-fast", action="store_true")
    _add_analysis_options(index)
    _add_entity_options(index)
    index.set_defaults(func=_cmd_index)

    inspect = sub.add_parser("inspect", help="Show cached semantic analysis for a scene")
    inspect.add_argument("scene_id", type=int)
    inspect.set_defaults(func=_cmd_inspect)

    materialize = sub.add_parser("materialize", help="Render an entity/depth-aware treatment to an intermediate video asset")
    materialize.add_argument("scene_id", type=int)
    materialize.add_argument("--output", required=True)
    materialize.add_argument(
        "--effect",
        action="append",
        choices=("subject_isolate", "subject_echo", "entity_split", "entity_outline", "depth_parallax"),
        default=[],
    )
    materialize.add_argument("--amount", type=float, default=0.8)
    materialize.add_argument("--copies", type=int, default=4)
    materialize.add_argument("--parallax-px", type=float, default=44.0)
    materialize.add_argument("--target-entity")
    materialize.add_argument("--target-role")
    materialize.add_argument("--target-label")
    materialize.add_argument("--split-distance", type=float, default=0.08)
    materialize.add_argument("--rotation-step", type=float, default=5.0)
    materialize.add_argument("--auto-direct", action="store_true")
    materialize.add_argument("--energy", type=float, default=0.7)
    materialize.add_argument("--bass", type=float, default=0.7)
    materialize.add_argument("--percussion", type=float, default=0.6)
    materialize.add_argument("--complexity", type=float, default=0.5)
    materialize.add_argument("--drop", type=float, default=0.0)
    materialize.add_argument("--build", type=float, default=0.0)
    materialize.set_defaults(func=_cmd_materialize)

    timeline = sub.add_parser("timeline", help="Rewrite a directed timeline to use cached semantic materializations")
    timeline.add_argument("timeline")
    timeline.add_argument("--output", required=True)
    timeline.add_argument("--auto-index", action="store_true")
    timeline.add_argument("--force", action="store_true")
    _add_entity_options(timeline)
    # Entity decomposition only needs these two shared model/runtime controls.
    timeline.add_argument("--sam2-model", default="facebook/sam2.1-hiera-small")
    timeline.add_argument("--device", default="auto")
    timeline.set_defaults(func=_cmd_timeline)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
