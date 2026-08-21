from pathlib import Path

from tubeviz.library import ClipLibrary, sha256_file
from tubeviz.models import DirectedTimeline, Section, TrackAnalysis
from tubeviz.scene_selector import SceneSelectorConfig, build_scene_plan


def ready_clip(library: ClipLibrary, source_id: str, term: str, scene_seconds: float = 12.0):
    clip_id = library.upsert_discovery(
        source="youtube",
        source_id=source_id,
        source_url=f"https://example.invalid/{source_id}",
        term=term,
        rank=1,
        metadata={"title": source_id, "duration": scene_seconds},
    )
    path = library.normalized_dir / f"{source_id}.mp4"
    path.write_bytes((source_id * 20).encode())
    library.mark_normalized(clip_id, path, sha256_file(path))
    library.replace_scenes(clip_id, [(0.0, scene_seconds, None)])
    return clip_id


def timeline(duration: float = 16.0) -> DirectedTimeline:
    beats = [i * 0.5 for i in range(int(duration / 0.5))]
    section = Section(
        index=0,
        start=0.0,
        end=duration,
        energy=.72,
        label="drive",
        local_tempo_bpm=120,
        vibe="driving",
    )
    track = TrackAnalysis(
        source="/tmp/song.wav",
        duration=duration,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120,
        beats=beats,
        bars=[i * 2.0 for i in range(int(duration / 2.0))],
        sections=[section],
        events=[],
    )
    return DirectedTimeline(track=track, cues=[])


def test_dynamic_shots_subdivide_one_music_section(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    for i in range(12):
        ready_clip(library, f"clip{i:02d}", "archive")

    plan = build_scene_plan(
        timeline(16),
        library,
        SceneSelectorConfig(
            dynamic_shots=True,
            max_video_layers=1,
            target_unique_clips=8,
            clip_reuse_cooldown=8,
            scene_reuse_cooldown=16,
        ),
    )
    # 120 BPM driving section => about four beats / two seconds per shot.
    assert len(plan) >= 7
    assert len({shot.clip_id for shot in plan}) >= 7
    assert all(shot.section_index == 0 for shot in plan)


def test_source_excerpt_uses_only_small_piece_of_long_scene(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    for i in range(4):
        ready_clip(library, f"long{i}", "archive", scene_seconds=30.0)

    plan = build_scene_plan(
        timeline(8),
        library,
        SceneSelectorConfig(
            dynamic_shots=True,
            max_video_layers=1,
            source_excerpt_max_seconds=2.5,
            target_unique_clips=4,
        ),
    )
    assert len(plan) >= 3
    assert all((shot.end - shot.start) <= 2.5 + 1e-6 for shot in plan)
    assert any(shot.start > 0 for shot in plan)


def test_auto_target_explores_library_by_default(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    for i in range(20):
        ready_clip(library, f"clip{i:02d}", "archive")

    plan = build_scene_plan(
        timeline(20),
        library,
        SceneSelectorConfig(
            dynamic_shots=True,
            max_video_layers=1,
            target_unique_clips=0,
        ),
    )
    # Auto target is roughly duration / 2.4 and should strongly favor unseen clips.
    assert len({shot.clip_id for shot in plan}) >= 8


def test_dynamic_shots_can_be_disabled(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    ready_clip(library, "clip", "archive", scene_seconds=30.0)
    plan = build_scene_plan(
        timeline(16),
        library,
        SceneSelectorConfig(dynamic_shots=False, max_video_layers=1),
    )
    assert len(plan) == 1
