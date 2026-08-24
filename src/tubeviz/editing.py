# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass

from .models import DirectedTimeline, EventType, VisualCue


@dataclass(frozen=True)
class EditConfig:
    enabled: bool = True
    intensity: float = 1.0
    retrigger_on_bars: bool = True
    onset_slices: bool = True


def attach_edit_plan(timeline: DirectedTimeline, config: EditConfig | None = None) -> DirectedTimeline:
    """Add beat-accurate video editing cues over the already-selected footage.

    These cues never select new media. They transform/re-time the currently rendered
    video, which keeps tubeviz video-first while allowing the musical clock to edit it.
    """
    cfg = config or EditConfig()
    if not cfg.enabled or not timeline.scene_plan:
        return timeline

    intensity = max(0.0, min(2.0, cfg.intensity))
    section_by_time = sorted(timeline.track.sections, key=lambda s: s.start)
    scene_sections = {s.section_index for s in timeline.scene_plan}
    cues = [c for c in timeline.cues if not c.action.startswith("video_edit_")]

    def section_at(t: float):
        for section in reversed(section_by_time):
            if section.start <= t < section.end:
                return section
        return section_by_time[-1] if section_by_time else None

    beat_ord = 0
    for event in timeline.track.events:
        section = section_at(event.time)
        if section is None or section.index not in scene_sections:
            continue
        energy = max(0.0, min(1.0, section.energy))

        if event.type == EventType.BEAT:
            beat_ord += 1
            accent = max(0.0, min(1.0, float(event.payload.get("accent", event.strength))))
            low = max(0.0, min(1.0, float(event.payload.get("low", 0.0))))
            mid = max(0.0, min(1.0, float(event.payload.get("mid", 0.0))))
            high = max(0.0, min(1.0, float(event.payload.get("high", 0.0))))
            pulse = max(0.0, min(1.0, float(event.payload.get("pulse", 0.0))))
            bpm = max(1.0, float(event.payload.get("local_bpm", section.local_tempo_bpm)))
            beat_seconds = 60.0 / bpm

            # One frequency-aware beat warp replaces the old generic "everything
            # punches the same way" behavior. Low transients act radially, mids
            # shear, highs split/chromatic-shimmer.
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_beat_warp",
                parameters={
                    "amount": min(1.0, intensity * (0.18 + 0.58 * accent)),
                    "low": low,
                    "mid": mid,
                    "high": high,
                    "pulse": pulse,
                    "duration": min(0.30, max(0.05, beat_seconds * 0.32)),
                    "local_bpm": bpm,
                },
            ))

            if low + mid + high <= 1e-9:
                # Backward compatibility for timelines created before
                # frequency-aware beat payloads existed.
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_punch",
                    parameters={
                        "amount": min(1.0, intensity * (0.10 + energy * 0.22 + event.strength * 0.18)),
                        "duration": min(0.22, beat_seconds * 0.28),
                    },
                ))
                if energy > 0.68 and beat_ord % 4 == 0:
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_strobe",
                        parameters={"amount": min(1.0, intensity * energy * .55)},
                    ))
                if energy > 0.55 and beat_ord % 2 == 0:
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_tunnel",
                        parameters={"amount": min(1.0, intensity * energy * .45)},
                    ))
                if section.label == "peak" and energy > 0.62 and beat_ord % 2 == 0:
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_switch",
                        parameters={"amount": min(1.0, intensity * energy)},
                    ))

            if low >= max(mid, high) and low > 0.30:
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_punch",
                    parameters={
                        "amount": min(1.0, intensity * (0.08 + low * 0.44 + accent * 0.20)),
                        "duration": min(0.22, beat_seconds * 0.28),
                    },
                ))
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_ripple",
                    parameters={"amount": min(1.0, intensity * (0.12 + low * 0.55))},
                ))

            if high > max(low, mid) and high > 0.28:
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_chroma_delay",
                    parameters={"amount": min(1.0, intensity * (0.08 + high * 0.48))},
                ))
                if high > 0.58:
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_slitscan",
                        parameters={"amount": min(1.0, intensity * high * 0.42)},
                    ))

            if mid > max(low, high) and mid > 0.38:
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_vortex",
                    parameters={"amount": min(1.0, intensity * mid * 0.28)},
                ))

            # Only strong accented beats trigger editing operations. This keeps
            # long mixes rhythmic without cutting on every quarter note.
            if accent > 0.66 and energy > 0.58:
                if beat_ord % (2 if energy > 0.82 else 4) == 0:
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_retrigger",
                        parameters={
                            "back_seconds": min(beat_seconds * 0.42, 0.22),
                            "amount": min(1.0, intensity * accent * energy),
                        },
                    ))
                if section.percussive_ratio > 0.58 and beat_ord % 4 == 2:
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_datamosh",
                        parameters={
                            "amount": min(1.0, intensity * accent * section.percussive_ratio * 0.66)
                        },
                    ))

            if section.label == "peak" and accent > 0.72 and beat_ord % 4 == 0:
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_switch",
                    parameters={"amount": min(1.0, intensity * accent)},
                ))

        elif event.type == EventType.BAR and cfg.retrigger_on_bars:
            if section.label in {"build", "peak"}:
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_jump",
                    parameters={
                        "fraction": ((section.index * 37 + int(event.time * 10)) % 73) / 100.0,
                        "amount": min(1.0, intensity * (0.35 + energy * 0.45)),
                    },
                ))
                if (
                    (section.tonal_stability > 0.64 and section.vibe in {"hypnotic", "euphoric"})
                    or (section.tonal_stability == 0.0 and section.vibe == "neutral")
                ):
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_kaleidoscope",
                        parameters={"amount": min(0.55, intensity * (0.08 + section.tonal_stability * 0.24))},
                    ))
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_slitscan",
                    parameters={"amount": min(1.0, intensity * (0.12 + energy * 0.50))},
                ))
                if energy > 0.70:
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_slice_recursion",
                        parameters={"amount": min(1.0, intensity * (0.18 + energy * 0.58))},
                    ))

        elif event.type == EventType.TEMPO_CHANGE:
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_tempo_warp",
                parameters={
                    "amount": min(1.0, intensity * (0.25 + event.strength * 0.65)),
                    "from_bpm": event.payload.get("from_bpm"),
                    "to_bpm": event.payload.get("to_bpm"),
                },
            ))

        elif event.type == EventType.HARMONIC_CHANGE:
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_ripple",
                parameters={"amount": min(1.0, intensity * (0.30 + event.strength * 0.60))},
            ))
            if event.strength > 0.62:
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_edge",
                    parameters={"amount": min(1.0, intensity * event.strength * 0.75)},
                ))
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_solarize",
                    parameters={"amount": min(1.0, intensity * event.strength * 0.70)},
                ))
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_vortex",
                    parameters={"amount": min(1.0, intensity * event.strength * 0.58)},
                ))

        elif event.type == EventType.ONSET and cfg.onset_slices and event.strength > 0.42:
            low = max(0.0, min(1.0, float(event.payload.get("low", 0.0))))
            mid = max(0.0, min(1.0, float(event.payload.get("mid", 0.0))))
            high = max(0.0, min(1.0, float(event.payload.get("high", 0.0))))
            dominant = event.payload.get("dominant_band")

            if dominant == "low" and low > 0.28:
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_beat_warp",
                    parameters={
                        "amount": min(1.0, intensity * event.strength * (.35 + low * .55)),
                        "low": low, "mid": mid, "high": high,
                    },
                ))
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_ripple",
                    parameters={"amount": min(1.0, intensity * event.strength * low * .58)},
                ))
            elif dominant == "mid" and mid > 0.28:
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_vortex",
                    parameters={"amount": min(.65, intensity * event.strength * mid * .38)},
                ))
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_slice",
                    parameters={
                        "amount": min(.65, intensity * event.strength * mid * .42),
                        "duration": 0.025 + 0.055 * event.strength,
                    },
                ))
            else:
                # High-frequency or legacy onset: short temporal/chromatic tear.
                cues.append(VisualCue(
                    time=event.time,
                    action="video_edit_slice",
                    parameters={
                        "amount": min(1.0, intensity * event.strength * (0.35 + energy * 0.40 + high * .28)),
                        "duration": 0.025 + 0.065 * event.strength,
                    },
                ))
                if high > .35:
                    cues.append(VisualCue(
                        time=event.time,
                        action="video_edit_chroma_delay",
                        parameters={"amount": min(.7, intensity * high * event.strength * .50)},
                    ))

        elif event.type == EventType.DROP_CANDIDATE:
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_freeze",
                parameters={
                    "duration": 0.08 + 0.22 * min(1.0, event.strength),
                    "amount": min(1.0, intensity * event.strength),
                },
            ))
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_strobe",
                parameters={
                    "duration": 0.12 + 0.12 * min(1.0, event.strength),
                    "amount": min(1.0, intensity * event.strength),
                },
            ))
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_tunnel",
                parameters={"amount": min(1.0, intensity * event.strength)},
            ))
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_corridor",
                parameters={"amount": min(1.0, intensity * event.strength * 0.90)},
            ))
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_motion_trails",
                parameters={"amount": min(1.0, intensity * event.strength)},
            ))
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_mask",
                parameters={"amount": min(1.0, intensity * event.strength * 0.75)},
            ))

    cues.sort(key=lambda cue: (cue.time, cue.action))
    return timeline.model_copy(update={"cues": cues})
