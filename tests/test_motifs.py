# SPDX-License-Identifier: Apache-2.0
from tubeviz.models import Section, TrackAnalysis
from tubeviz.motifs import MotifConfig, cosine_similarity, discover_motifs


def make_track():
    sections = [
        Section(index=0, start=0, end=16, energy=.4, label="drive", fingerprint=[1, 0, 0, .4]),
        Section(index=1, start=16, end=32, energy=.7, label="build", fingerprint=[0, 1, 0, .7]),
        Section(index=2, start=32, end=48, energy=.5, label="drive", fingerprint=[.99, .01, 0, .4]),
        Section(index=3, start=48, end=64, energy=.3, label="ambient", fingerprint=[0, 0, 1, .3]),
        Section(index=4, start=64, end=80, energy=.6, label="drive", fingerprint=[.98, .02, 0, .4]),
    ]
    return TrackAnalysis(
        source="/tmp/test.wav", duration=80, sample_rate=22050, hop_length=512,
        tempo_bpm=120, beats=[], bars=[0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58, 60, 62, 64],
        sections=sections, events=[]
    )


def test_cosine_similarity():
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0


def test_discover_recurring_motif():
    motifs = discover_motifs(
        make_track(),
        MotifConfig(similarity_threshold=.97, min_separation_sections=2),
    )
    assert len(motifs) == 1
    assert [o.section_index for o in motifs[0].occurrences] == [0, 2, 4]
