from pathlib import Path

from tubeviz.models import DirectedTimeline, SceneSelection, TrackAnalysis, VectorEffect, VisualDirection
from tubeviz.native_render import write_native_manifest


def test_native_manifest_serializes_vector_effects(tmp_path: Path):
    library = tmp_path / "library"
    normalized = library / "normalized"
    normalized.mkdir(parents=True)
    media = normalized / "a.mp4"
    media.write_bytes(b"video")

    track = TrackAnalysis(
        source=str(tmp_path / "song.wav"),
        duration=4.0,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120,
        beats=[0, .5, 1],
        bars=[0],
        sections=[],
        events=[],
    )
    scene = SceneSelection(
        section_index=0,
        time=0,
        term="test",
        clip_id=1,
        scene_id=1,
        scene_index=0,
        source_id="a",
        media_file="a.mp4",
        media_url="/media/a.mp4",
        start=0,
        end=2,
        duration=2,
        direction=VisualDirection(
            vector_effects=[
                VectorEffect(
                    kind="delaunay_fracture",
                    amount=.8,
                    opacity=.3,
                    seed=42,
                    count=24,
                    line_width=1.5,
                    displace=True,
                    parameters={"motion_x": .4, "motion_y": -.2},
                    automation={
                        "amount": [(0, .1), (.5, .5), (1, .8)],
                        "explode": [(0, 0), (1, .7)],
                    },
                )
            ]
        ),
    )
    timeline = DirectedTimeline(track=track, cues=[], scene_plan=[scene])
    text = write_native_manifest(timeline, library, tmp_path / "native.tsv").read_text()
    vec = next(line for line in text.splitlines() if line.startswith("VEC\t"))
    fields = vec.split("\t")
    assert fields[1] == "delaunay_fracture"
    assert fields[4] == "42"
    assert fields[8] == "1"
    assert float(fields[15]) == .7
