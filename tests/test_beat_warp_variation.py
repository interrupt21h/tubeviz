# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from tubeviz.beat_warp import WARP_MODES, beat_warp_parameters
from tubeviz.models import EventType, MusicalEvent, Section


def _beat(time: float, *, low: float, mid: float, high: float, accent: float = 0.8) -> MusicalEvent:
    return MusicalEvent(
        time=time,
        type=EventType.BEAT,
        strength=accent,
        payload={
            "accent": accent,
            "low": low,
            "mid": mid,
            "high": high,
            "pulse": 0.7,
            "local_bpm": 128.0,
        },
    )


def test_beat_warp_descriptor_is_deterministic_but_changes_across_beats():
    section = Section(index=2, start=0, end=16, energy=.86, label="peak", local_tempo_bpm=128)
    events = [_beat(i * .46875, low=.85, mid=.25, high=.12) for i in range(1, 9)]
    params = [
        beat_warp_parameters(event, beat_index=i, tempo_bpm=128, section=section)
        for i, event in enumerate(events, 1)
    ]
    repeat = beat_warp_parameters(events[3], beat_index=4, tempo_bpm=128, section=section)
    assert repeat == params[3]
    assert len({p["warp_mode_id"] for p in params}) >= 3
    assert len({round(p["direction"], 4) for p in params}) >= 4
    assert len({(round(p["center_x"], 4), round(p["center_y"], 4)) for p in params}) >= 6
    assert {p["polarity"] for p in params} == {-1.0, 1.0}
    assert all(p["warp_mode"] in WARP_MODES for p in params)


def test_spectrum_changes_warp_vocabulary_and_frequency():
    section = Section(index=0, start=0, end=8, energy=.72, label="body", local_tempo_bpm=120)
    low = beat_warp_parameters(_beat(.5, low=.92, mid=.12, high=.04), beat_index=2, tempo_bpm=120, section=section)
    mid = beat_warp_parameters(_beat(.5, low=.10, mid=.90, high=.08), beat_index=2, tempo_bpm=120, section=section)
    high = beat_warp_parameters(_beat(.5, low=.05, mid=.12, high=.94), beat_index=2, tempo_bpm=120, section=section)
    assert low["dominant_band"] == "low"
    assert mid["dominant_band"] == "mid"
    assert high["dominant_band"] == "high"
    assert len({low["warp_mode_id"], mid["warp_mode_id"], high["warp_mode_id"]}) >= 2
    assert high["frequency"] > low["frequency"]
    assert .075 <= low["duration"] <= .42
    assert .035 <= low["attack"] <= .12
