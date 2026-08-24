# SPDX-License-Identifier: Apache-2.0
from tubeviz.director import direct
from tubeviz.models import EventType, MusicalEvent, TrackAnalysis


def test_beat_maps_to_camera_impulse():
    track = TrackAnalysis(
        source="/tmp/test.wav",
        duration=1.0,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120.0,
        beats=[0.5],
        bars=[],
        sections=[],
        events=[
            MusicalEvent(
                time=0.5,
                type=EventType.BEAT,
                strength=0.8,
            )
        ],
    )
    timeline = direct(track)
    assert len(timeline.cues) == 1
    assert timeline.cues[0].action == "camera_impulse"
    assert timeline.cues[0].time == 0.5
    assert timeline.cues[0].parameters["amount"] > 0
