# SPDX-License-Identifier: Apache-2.0
from tubeviz.models import (
    DirectedTimeline,
    EventType,
    MusicalEvent,
    TrackAnalysis,
    VisualCue,
)
from tubeviz.timeline import TimelineCursor


def make_timeline():
    track = TrackAnalysis(
        source="/tmp/test.wav",
        duration=4.0,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120.0,
        beats=[0.5, 1.0, 1.5],
        bars=[0.5],
        sections=[],
        events=[
            MusicalEvent(time=0.5, type=EventType.BEAT),
            MusicalEvent(time=1.0, type=EventType.BEAT),
        ],
    )
    return DirectedTimeline(
        track=track,
        cues=[
            VisualCue(time=0.5, action="a"),
            VisualCue(time=1.0, action="b"),
            VisualCue(time=1.5, action="c"),
        ],
    )


def test_cursor_emits_crossed_cues_exactly_once():
    cursor = TimelineCursor(make_timeline())
    assert cursor.advance(0.49) == []
    assert [c.action for c in cursor.advance(0.50)] == ["a"]
    assert cursor.advance(0.75) == []
    assert [c.action for c in cursor.advance(1.50)] == ["b", "c"]
    assert cursor.advance(1.60) == []


def test_cursor_seek_resets_future_events():
    cursor = TimelineCursor(make_timeline())
    cursor.advance(1.5)
    cursor.reset(0.6)
    assert [c.action for c in cursor.advance(1.0)] == ["b"]
