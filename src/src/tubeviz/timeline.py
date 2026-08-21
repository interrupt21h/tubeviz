from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from .models import DirectedTimeline, VisualCue


@dataclass
class TimelineCursor:
    timeline: DirectedTimeline

    def __post_init__(self) -> None:
        self._times = [cue.time for cue in self.timeline.cues]
        self._index = 0
        self._last_time = 0.0

    def reset(self, at: float = 0.0) -> None:
        self._index = bisect_right(self._times, at)
        self._last_time = at

    def advance(self, now: float) -> list[VisualCue]:
        if now < self._last_time:
            self.reset(now)
            return []

        end = bisect_right(self._times, now, lo=self._index)
        cues = self.timeline.cues[self._index:end]
        self._index = end
        self._last_time = now
        return cues
