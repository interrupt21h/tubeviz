# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass

from .beat_warp import beat_warp_parameters
from .models import DirectedTimeline, EventType, VisualCue


@dataclass(frozen=True)
class EditConfig:
    enabled: bool = True
    intensity: float = 1.0
    retrigger_on_bars: bool = True
    onset_slices: bool = True


def attach_edit_plan(timeline: DirectedTimeline, config: EditConfig | None = None) -> DirectedTimeline:
    """Add musically timed editing cues without turning every event into an FX stack.

    Beat warp is the lightweight rhythmic bed. Heavier spatial, temporal, glitch,
    symmetry, and color effects are punctuation: they are frequency-aware, use
    per-effect cooldowns, and avoid stacking several destructive treatments on
    the same musical event.
    """
    cfg = config or EditConfig()
    if not cfg.enabled or not timeline.scene_plan:
        return timeline

    intensity = max(0.0, min(2.0, cfg.intensity))
    section_by_time = sorted(timeline.track.sections, key=lambda s: s.start)
    scene_sections = {s.section_index for s in timeline.scene_plan}
    cues = [c for c in timeline.cues if not c.action.startswith("video_edit_")]
    last_effect_time: dict[str, float] = {}

    def section_at(t: float):
        for section in reversed(section_by_time):
            if section.start <= t < section.end:
                return section
        return section_by_time[-1] if section_by_time else None

    def add_effect(
        time: float,
        action: str,
        parameters: dict,
        *,
        cooldown: float = 0.0,
    ) -> bool:
        """Append one cue unless that effect fired too recently.

        Cooldowns are deliberately per effect rather than global: a bass ripple
        may coexist with a short punch, but repeated ripples/vortices/slit scans
        cannot become a continuously retriggered wallpaper.
        """
        last = last_effect_time.get(action, -1.0e9)
        if cooldown > 0.0 and time - last < cooldown - 1.0e-9:
            return False
        cues.append(VisualCue(time=time, action=action, parameters=parameters))
        last_effect_time[action] = time
        return True

    beat_ord = 0
    bar_ord = 0
    for event in timeline.track.events:
        if event.type == EventType.BEAT:
            beat_ord += 1
        elif event.type == EventType.BAR:
            bar_ord += 1

        section = section_at(event.time)
        if section is None or section.index not in scene_sections:
            continue
        energy = max(0.0, min(1.0, section.energy))

        if event.type == EventType.BEAT:
            accent = max(0.0, min(1.0, float(event.payload.get("accent", event.strength))))
            low = max(0.0, min(1.0, float(event.payload.get("low", 0.0))))
            mid = max(0.0, min(1.0, float(event.payload.get("mid", 0.0))))
            high = max(0.0, min(1.0, float(event.payload.get("high", 0.0))))
            bpm = max(1.0, float(event.payload.get("local_bpm", section.local_tempo_bpm)))
            beat_seconds = 60.0 / bpm

            # Lightweight beat-local topology is intentionally allowed on every
            # beat. The renderer uses a short attack/release envelope and changes
            # topology/center by phrase, so this remains rhythmic rather than a
            # permanently decaying global wobble.
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_beat_warp",
                parameters=beat_warp_parameters(
                    event,
                    beat_index=beat_ord,
                    tempo_bpm=timeline.track.tempo_bpm,
                    section=section,
                    amount=min(1.0, intensity * (0.16 + 0.52 * accent)),
                ),
            ))

            if low + mid + high <= 1e-9:
                # Legacy timelines have no spectral payload. Keep useful rhythmic
                # punctuation, but gate the expensive treatments by musical bars.
                add_effect(
                    event.time,
                    "video_edit_punch",
                    {
                        "amount": min(1.0, intensity * (0.10 + energy * 0.20 + event.strength * 0.16)),
                        "duration": min(0.20, beat_seconds * 0.26),
                    },
                    cooldown=max(0.10, beat_seconds * 0.72),
                )
                if energy > 0.70 and beat_ord % 4 == 0:
                    add_effect(
                        event.time,
                        "video_edit_strobe",
                        {"amount": min(0.72, intensity * energy * 0.48)},
                        cooldown=max(0.45, beat_seconds * 1.5),
                    )
                if energy > 0.58 and beat_ord % 4 == 2:
                    add_effect(
                        event.time,
                        "video_edit_tunnel",
                        {"amount": min(0.58, intensity * energy * 0.36)},
                        cooldown=max(0.90, beat_seconds * 2.5),
                    )
                if section.label == "peak" and energy > 0.62 and beat_ord % 2 == 0:
                    add_effect(
                        event.time,
                        "video_edit_switch",
                        {"amount": min(1.0, intensity * energy)},
                        cooldown=max(0.45, beat_seconds * 1.5),
                    )

            # Low-frequency energy gets a true radial pressure ripple. Do not fire
            # it on every kick: alternating/strong accents are enough to establish
            # the grammar while leaving room to see the source footage move.
            if low >= max(mid, high) and low > 0.38:
                add_effect(
                    event.time,
                    "video_edit_punch",
                    {
                        "amount": min(0.82, intensity * (0.07 + low * 0.34 + accent * 0.18)),
                        "duration": min(0.20, beat_seconds * 0.26),
                    },
                    cooldown=max(0.10, beat_seconds * 0.65),
                )
                if accent > 0.46 or beat_ord % 2 == 1:
                    add_effect(
                        event.time,
                        "video_edit_ripple",
                        {"amount": min(0.68, intensity * (0.08 + low * 0.38 + accent * 0.10))},
                        cooldown=max(0.34, beat_seconds * 0.72),
                    )

            # Treble punctuation is brief chromatic/temporal motion. Slit scan is
            # intentionally much rarer than the lightweight chroma displacement.
            if high > max(low, mid) and high > 0.38:
                add_effect(
                    event.time,
                    "video_edit_chroma_delay",
                    {"amount": min(0.62, intensity * (0.06 + high * 0.36))},
                    cooldown=max(0.24, beat_seconds * 0.55),
                )
                if high > 0.64 and accent > 0.52 and beat_ord % 4 == 2:
                    add_effect(
                        event.time,
                        "video_edit_slitscan",
                        {"amount": min(0.50, intensity * high * 0.34)},
                        cooldown=max(0.72, beat_seconds * 2.0),
                    )

            # Midrange twist is useful as punctuation but visually dominant. A
            # once-per-bar-ish cadence prevents the old continuous whirlpool look.
            if mid > max(low, high) and mid > 0.48 and accent > 0.50 and beat_ord % 4 == 0:
                add_effect(
                    event.time,
                    "video_edit_vortex",
                    {"amount": min(0.46, intensity * mid * 0.26)},
                    cooldown=max(0.82, beat_seconds * 2.0),
                )

            if accent > 0.68 and energy > 0.60:
                if beat_ord % (2 if energy > 0.84 else 4) == 0:
                    add_effect(
                        event.time,
                        "video_edit_retrigger",
                        {
                            "back_seconds": min(beat_seconds * 0.36, 0.18),
                            "amount": min(0.90, intensity * accent * energy),
                        },
                        cooldown=max(0.55, beat_seconds * 1.5),
                    )
                if section.percussive_ratio > 0.62 and beat_ord % 8 == 6:
                    add_effect(
                        event.time,
                        "video_edit_datamosh",
                        {"amount": min(0.62, intensity * accent * section.percussive_ratio * 0.52)},
                        cooldown=max(1.10, beat_seconds * 3.5),
                    )

            if section.label == "peak" and accent > 0.76 and beat_ord % 4 == 0:
                add_effect(
                    event.time,
                    "video_edit_switch",
                    {"amount": min(1.0, intensity * accent)},
                    cooldown=max(0.55, beat_seconds * 1.5),
                )

        elif event.type == EventType.BAR and cfg.retrigger_on_bars:
            if section.label in {"build", "peak"}:
                add_effect(
                    event.time,
                    "video_edit_jump",
                    {
                        "fraction": ((section.index * 37 + int(event.time * 10)) % 73) / 100.0,
                        "amount": min(0.78, intensity * (0.30 + energy * 0.38)),
                    },
                    cooldown=0.65,
                )

                tonal_symmetry = (
                    (section.tonal_stability > 0.66 and section.vibe in {"hypnotic", "euphoric"})
                    or (section.tonal_stability == 0.0 and section.vibe == "neutral")
                )
                if tonal_symmetry and (bar_ord - 1) % 2 == 0:
                    add_effect(
                        event.time,
                        "video_edit_kaleidoscope",
                        {"amount": min(0.42, intensity * (0.07 + section.tonal_stability * 0.18))},
                        cooldown=1.8,
                    )
                if bar_ord % 2 == 0:
                    add_effect(
                        event.time,
                        "video_edit_slitscan",
                        {"amount": min(0.48, intensity * (0.08 + energy * 0.34))},
                        cooldown=0.85,
                    )
                if energy > 0.78 and section.label == "peak" and bar_ord % 4 == 0:
                    add_effect(
                        event.time,
                        "video_edit_slice_recursion",
                        {"amount": min(0.52, intensity * (0.12 + energy * 0.38))},
                        cooldown=1.6,
                    )

        elif event.type == EventType.TEMPO_CHANGE:
            add_effect(
                event.time,
                "video_edit_tempo_warp",
                {
                    "amount": min(0.72, intensity * (0.20 + event.strength * 0.48)),
                    "from_bpm": event.payload.get("from_bpm"),
                    "to_bpm": event.payload.get("to_bpm"),
                },
                cooldown=0.70,
            )

        elif event.type == EventType.HARMONIC_CHANGE:
            # Harmonic movement gets one radial transition plus at most one strong
            # accent family. The old plan stacked edge + solarize + vortex together.
            add_effect(
                event.time,
                "video_edit_ripple",
                {"amount": min(0.72, intensity * (0.20 + event.strength * 0.42))},
                cooldown=0.42,
            )
            if event.strength > 0.62:
                variant = (section.index + int(event.time * 10)) % 3
                if variant == 0:
                    add_effect(
                        event.time,
                        "video_edit_edge",
                        {"amount": min(0.58, intensity * event.strength * 0.50)},
                        cooldown=0.90,
                    )
                elif variant == 1:
                    add_effect(
                        event.time,
                        "video_edit_vortex",
                        {"amount": min(0.48, intensity * event.strength * 0.38)},
                        cooldown=0.90,
                    )
                else:
                    add_effect(
                        event.time,
                        "video_edit_solarize",
                        {"amount": min(0.48, intensity * event.strength * 0.40)},
                        cooldown=1.0,
                    )

        elif event.type == EventType.ONSET and cfg.onset_slices and event.strength > 0.44:
            low = max(0.0, min(1.0, float(event.payload.get("low", 0.0))))
            mid = max(0.0, min(1.0, float(event.payload.get("mid", 0.0))))
            high = max(0.0, min(1.0, float(event.payload.get("high", 0.0))))
            dominant = event.payload.get("dominant_band")

            if dominant == "low" and low > 0.34:
                # Onsets reuse the same renderer-agnostic beat grammar, but with a
                # lower ceiling than beat events so duplicate detections do not pile up.
                add_effect(
                    event.time,
                    "video_edit_beat_warp",
                    {
                        "amount": min(0.62, intensity * event.strength * (0.28 + low * 0.42)),
                        "low": low, "mid": mid, "high": high,
                    },
                    cooldown=0.18,
                )
                add_effect(
                    event.time,
                    "video_edit_ripple",
                    {"amount": min(0.58, intensity * event.strength * low * 0.44)},
                    cooldown=0.36,
                )
            elif dominant == "mid" and mid > 0.38:
                if event.strength > 0.58:
                    add_effect(
                        event.time,
                        "video_edit_vortex",
                        {"amount": min(0.42, intensity * event.strength * mid * 0.30)},
                        cooldown=0.82,
                    )
                add_effect(
                    event.time,
                    "video_edit_slice",
                    {
                        "amount": min(0.52, intensity * event.strength * mid * 0.34),
                        "duration": 0.025 + 0.045 * event.strength,
                    },
                    cooldown=0.18,
                )
            else:
                add_effect(
                    event.time,
                    "video_edit_slice",
                    {
                        "amount": min(0.72, intensity * event.strength * (0.28 + energy * 0.28 + high * 0.20)),
                        "duration": 0.025 + 0.055 * event.strength,
                    },
                    cooldown=0.18,
                )
                if high > 0.42:
                    add_effect(
                        event.time,
                        "video_edit_chroma_delay",
                        {"amount": min(0.54, intensity * high * event.strength * 0.38)},
                        cooldown=0.25,
                    )

        elif event.type == EventType.DROP_CANDIDATE:
            strength = max(0.0, min(1.0, event.strength))
            add_effect(
                event.time,
                "video_edit_freeze",
                {
                    "duration": 0.07 + 0.16 * strength,
                    "amount": min(0.90, intensity * strength),
                },
                cooldown=0.75,
            )
            add_effect(
                event.time,
                "video_edit_strobe",
                {
                    "duration": 0.10 + 0.10 * strength,
                    "amount": min(0.82, intensity * strength * 0.82),
                },
                cooldown=0.55,
            )

            # A drop gets one spatial architecture and one temporal accent, not
            # six simultaneous treatments. Deterministic alternation still gives
            # repeated drops distinct visual identities.
            variant = (section.index + int(event.time * 10)) % 2
            if variant == 0:
                add_effect(
                    event.time,
                    "video_edit_tunnel",
                    {"amount": min(0.72, intensity * strength * 0.72)},
                    cooldown=1.2,
                )
                add_effect(
                    event.time,
                    "video_edit_motion_trails",
                    {"amount": min(0.64, intensity * strength * 0.62)},
                    cooldown=0.95,
                )
            else:
                add_effect(
                    event.time,
                    "video_edit_corridor",
                    {"amount": min(0.66, intensity * strength * 0.62)},
                    cooldown=1.5,
                )
                add_effect(
                    event.time,
                    "video_edit_mask",
                    {"amount": min(0.56, intensity * strength * 0.52)},
                    cooldown=1.25,
                )

    cues.sort(key=lambda cue: (cue.time, cue.action))
    return timeline.model_copy(update={"cues": cues})
