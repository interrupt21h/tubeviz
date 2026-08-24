# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.library import ClipLibrary, sha256_file
from tubeviz.models import (
    DirectedTimeline,
    MotifOccurrence,
    MusicalMotif,
    Section,
    TrackAnalysis,
)
from tubeviz.scene_selector import SceneSelectorConfig, attach_scene_plan, build_scene_plan


def _ready_clip(library: ClipLibrary, source_id: str, term: str, durations: list[float]) -> int:
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id=source_id,
        source_url=f"https://www.youtube.com/watch?v={source_id}",
        term=term,
        rank=1,
        metadata={"title": source_id, "duration": sum(durations)},
    )
    path = library.normalized_dir / f"{source_id}.mp4"
    path.write_bytes((source_id * 8).encode())
    library.mark_normalized(clip_id, path, sha256_file(path))
    start = 0.0
    scenes = []
    for duration in durations:
        scenes.append((start, start + duration, None))
        start += duration
    library.replace_scenes(clip_id, scenes)
    return clip_id


def _timeline() -> DirectedTimeline:
    sections = [
        Section(index=0, start=0.0, end=8.0, energy=.4, label="drive"),
        Section(index=1, start=8.0, end=16.0, energy=.7, label="build"),
        Section(index=2, start=16.0, end=24.0, energy=.4, label="drive"),
    ]
    track = TrackAnalysis(
        source="/tmp/song.wav",
        duration=24.0,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120.0,
        key="C minor",
        beats=[], bars=[], sections=sections, events=[],
    )
    motif = MusicalMotif(
        id="motif_01",
        prototype_section=0,
        fingerprint=[1.0, 0.0],
        occurrences=[
            MotifOccurrence(section_index=0, start=0.0, end=8.0, similarity=1.0, ordinal=1),
            MotifOccurrence(section_index=2, start=16.0, end=24.0, similarity=.96, ordinal=2),
        ],
    )
    return DirectedTimeline(track=track, cues=[], motifs=[motif])


def test_scene_plan_uses_ready_library_and_reuses_clip_for_motif(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    _ready_clip(library, "clipA", "abandoned mall", [7.5, 8.5, 5.0])
    _ready_clip(library, "clipB", "abandoned mall", [4.0, 12.0])

    plan = build_scene_plan(_timeline(), library, SceneSelectorConfig(recent_scene_window=2))
    assert len(plan) == 3
    motif_scenes = [scene for scene in plan if scene.motif_id == "motif_01"]
    assert len(motif_scenes) == 2
    assert motif_scenes[0].clip_id == motif_scenes[1].clip_id
    assert motif_scenes[0].scene_id != motif_scenes[1].scene_id
    assert motif_scenes[0].media_url.startswith("/media/")


def test_attach_scene_plan_adds_renderer_cues(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    _ready_clip(library, "clipA", "archive", [10.0, 10.0, 10.0])
    timeline = attach_scene_plan(_timeline(), library)
    scene_actions = [cue.action for cue in timeline.cues if cue.action.endswith("scene")]
    assert scene_actions[0] == "play_scene"
    assert scene_actions[1:] == ["crossfade_scene", "crossfade_scene"]
    assert len(timeline.scene_plan) == 3


def test_scene_plan_adds_distinct_composite_video_layers(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    _ready_clip(library, "clipA", "archive", [8.0, 8.0])
    _ready_clip(library, "clipB", "archive", [8.0, 8.0])
    _ready_clip(library, "clipC", "archive", [8.0, 8.0])
    timeline = _timeline()
    plan = build_scene_plan(
        timeline,
        library,
        SceneSelectorConfig(max_video_layers=3, composition_intensity=1.0),
    )
    assert len(plan) == 3
    build = plan[1]
    assert build.composition_mode in {"flow", "luma", "strips"}
    assert len(build.layers) >= 1
    assert len({build.clip_id, *(layer.clip_id for layer in build.layers)}) >= 2
