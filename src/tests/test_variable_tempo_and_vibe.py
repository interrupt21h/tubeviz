import numpy as np

from tubeviz.analysis import AnalysisConfig, _dynamic_tempo, _fold_tempo_octaves
from tubeviz.models import EventType, MusicalEvent, Section


def _synthetic_onset_curve():
    sr = 22050
    hop = 512
    fps = sr / hop
    seconds = 40
    onset = np.zeros(int(seconds * fps), dtype=float)
    for bpm, start, end in ((90.0, 0.0, 20.0), (140.0, 20.0, 40.0)):
        step = 60.0 / bpm * fps
        position = start * fps
        while position < end * fps:
            onset[int(round(position))] = 1.0
            position += step
    return onset, sr, hop, fps


def test_dynamic_tempo_tracks_two_tempo_regions():
    onset, sr, hop, fps = _synthetic_onset_curve()
    bpm, confidence, pulse = _dynamic_tempo(
        onset,
        sr=sr,
        hop_length=hop,
        cfg=AnalysisConfig(
            tempo_window_seconds=6.0,
            tempo_smoothing_seconds=1.0,
        ),
    )
    first = float(np.median(bpm[int(5 * fps):int(17 * fps)]))
    second = float(np.median(bpm[int(25 * fps):int(37 * fps)]))
    assert 84 <= first <= 96
    assert 132 <= second <= 148
    assert confidence.shape == bpm.shape == pulse.shape


def test_octave_folding_converts_half_time_dj_estimate():
    cfg = AnalysisConfig(tempo_octave_min=75, tempo_octave_max=190)
    folded = _fold_tempo_octaves(np.array([69.8, 89.0, 140.0, 200.0]), cfg)
    assert folded[0] == 139.6
    assert folded[1] == 89.0
    assert folded[2] == 140.0
    assert folded[3] == 100.0


def test_section_model_carries_vibe_and_local_rhythm_features():
    section = Section(
        index=0,
        start=0,
        end=16,
        energy=.7,
        label="drive",
        local_tempo_bpm=128,
        tempo_confidence=.8,
        pulse_strength=.7,
        bass_weight=.45,
        percussive_ratio=.72,
        tonal_stability=.6,
        noisiness=.2,
        spectral_contrast=.5,
        vibe="driving",
    )
    assert section.vibe == "driving"
    assert section.local_tempo_bpm == 128


def test_tempo_change_event_type_exists():
    event = MusicalEvent(
        time=10,
        type=EventType.TEMPO_CHANGE,
        strength=.5,
        payload={"from_bpm": 120, "to_bpm": 128},
    )
    assert event.type == EventType.TEMPO_CHANGE
