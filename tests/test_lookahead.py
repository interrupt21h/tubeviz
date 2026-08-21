from tubeviz.director import direct
from tubeviz.models import Section, TrackAnalysis
from tubeviz.motifs import MotifConfig


def test_director_builds_memory_and_foreshadowing():
    track = TrackAnalysis(
        source="/tmp/test.wav",
        duration=64,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120,
        beats=[],
        bars=[float(x) for x in range(0, 65, 2)],
        sections=[
            Section(index=0, start=0, end=16, energy=.4, label="drive", fingerprint=[1, 0, .4]),
            Section(index=1, start=16, end=32, energy=.2, label="ambient", fingerprint=[0, 1, .2]),
            Section(index=2, start=32, end=48, energy=.5, label="drive", fingerprint=[.99, .01, .4]),
            Section(index=3, start=48, end=64, energy=.8, label="peak", fingerprint=[0, 0, 1]),
        ],
        events=[],
    )
    timeline = direct(
        track,
        motif_config=MotifConfig(similarity_threshold=.97, min_separation_sections=2),
    )

    assert len(timeline.motifs) == 1
    assert len(timeline.visual_memory) == 1
    actions = [cue.action for cue in timeline.cues]
    assert "introduce_motif" in actions
    assert "foreshadow_motif" in actions
    assert "anticipate_motif" in actions
    assert "recall_motif" in actions

    recall = next(c for c in timeline.cues if c.action == "recall_motif")
    foreshadow = next(c for c in timeline.cues if c.action == "foreshadow_motif")
    assert foreshadow.time < recall.time
    assert recall.parameters["mutation"] == 1
    assert timeline.world_states[2].memory_depth == 1
