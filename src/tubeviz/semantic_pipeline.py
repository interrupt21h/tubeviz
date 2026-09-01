# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .library import ClipLibrary
from .models import DirectedTimeline
from .semantic_compositing import SemanticAssetStore, analyze_library_scene
from .semantic_director import SemanticDirectionInput, direct_semantic_effects
from .semantic_entities import EntityDecompositionConfig, decompose_scene_entities
from .semantic_materialize import materialize_scene


def _materialization_key(selection, analysis, effects) -> str:
    payload = {
        "scene_id": selection.scene_id,
        "start": selection.start,
        "end": selection.end,
        "analysis_version": analysis.version,
        "mask_backend": analysis.mask_backend,
        "depth_backend": analysis.depth_backend,
        "entities": [
            {
                "id": entity.entity_id,
                "label": entity.label,
                "role": entity.role,
                "confidence": round(float(entity.confidence), 5),
                "area": round(float(entity.mean_area), 5),
                "motion": round(float(entity.motion), 5),
            }
            for entity in analysis.entities
        ],
        "effects": [effect.__dict__ for effect in effects],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def semanticize_timeline(
    timeline: DirectedTimeline,
    library: ClipLibrary,
    *,
    auto_index: bool = False,
    force: bool = False,
    multi_entity: bool = True,
    entity_config: EntityDecompositionConfig | None = None,
) -> tuple[DirectedTimeline, dict[str, int]]:
    """Materialize semantic treatments and return a normal renderable timeline."""
    store = SemanticAssetStore(library.root)
    materialized_root = library.root / "semantic_materialized"
    materialized_root.mkdir(parents=True, exist_ok=True)
    sections = {section.index: section for section in timeline.track.sections}
    updated = []
    stats = {
        "shots": 0,
        "materialized": 0,
        "missing_analysis": 0,
        "no_effect": 0,
        "cached": 0,
        "multi_entity_scenes": 0,
    }

    for selection in timeline.scene_plan:
        stats["shots"] += 1
        analysis = store.load(selection.scene_id)
        if analysis is None and auto_index:
            analysis = analyze_library_scene(library, selection.scene_id, force=force)
        if analysis is not None and multi_entity and (auto_index or len(analysis.entities) <= 1):
            try:
                analysis = decompose_scene_entities(
                    library.root,
                    analysis,
                    entity_config or EntityDecompositionConfig(),
                    force=force,
                )
            except (RuntimeError, ImportError, ModuleNotFoundError, OSError, ValueError):
                # The original foreground/depth analysis remains valid when optional
                # open-vocabulary detection or SAM 2 dependencies are unavailable.
                pass
        if analysis is None:
            stats["missing_analysis"] += 1
            updated.append(selection)
            continue
        if len(analysis.entities) > 1:
            stats["multi_entity_scenes"] += 1
        section = sections.get(selection.section_index)
        if section is None:
            updated.append(selection)
            continue
        trajectory = section.trajectory
        direction = selection.direction
        effects = direct_semantic_effects(
            analysis,
            SemanticDirectionInput(
                energy=float(section.energy),
                bass_weight=float(section.bass_weight),
                percussive_ratio=float(section.percussive_ratio),
                complexity=float(direction.complexity),
                drop_probability=float(trajectory.drop_probability if trajectory else 0.0),
                build_probability=float(trajectory.build_probability if trajectory else 0.0),
            ),
        )
        if not effects:
            stats["no_effect"] += 1
            updated.append(selection)
            continue

        key = _materialization_key(selection, analysis, effects)
        target = materialized_root / f"scene-{selection.scene_id}-{key}.mp4"
        if target.exists() and not force:
            stats["cached"] += 1
        else:
            materialize_scene(library.root, analysis, target, effects)
        relative_start = max(0.0, float(selection.start) - float(analysis.start))
        relative_end = min(float(analysis.end - analysis.start), float(selection.end) - float(analysis.start))
        if relative_end <= relative_start:
            relative_start = 0.0
            relative_end = min(float(selection.duration), float(analysis.end - analysis.start))
        relative_path = str(target.relative_to(library.root))
        semantic_note = {
            "semantic_compositing": {
                "analysis_version": analysis.version,
                "mask_backend": analysis.mask_backend,
                "depth_backend": analysis.depth_backend,
                "entities": [
                    {
                        "id": entity.entity_id,
                        "label": entity.label,
                        "role": entity.role,
                        "confidence": entity.confidence,
                        "area": entity.mean_area,
                        "motion": entity.motion,
                    }
                    for entity in analysis.entities
                ],
                "effects": [effect.__dict__ for effect in effects],
                "cache_key": key,
            }
        }
        consultant = dict(selection.ai_consultant)
        consultant.update(semantic_note)
        updated.append(
            selection.model_copy(
                update={
                    "media_file": relative_path,
                    "media_url": target.resolve().as_uri(),
                    "start": relative_start,
                    "end": relative_end,
                    "ai_consultant": consultant,
                }
            )
        )
        stats["materialized"] += 1

    return timeline.model_copy(update={"scene_plan": updated}), stats


def semanticize_timeline_file(
    timeline_file: str | Path,
    library_root: str | Path,
    output_file: str | Path,
    *,
    auto_index: bool = False,
    force: bool = False,
    multi_entity: bool = True,
    entity_config: EntityDecompositionConfig | None = None,
) -> dict[str, int]:
    timeline_path = Path(timeline_file)
    timeline = DirectedTimeline.model_validate_json(timeline_path.read_text(encoding="utf-8"))
    library = ClipLibrary(library_root)
    library.initialize()
    updated, stats = semanticize_timeline(
        timeline,
        library,
        auto_index=auto_index,
        force=force,
        multi_entity=multi_entity,
        entity_config=entity_config,
    )
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return stats
