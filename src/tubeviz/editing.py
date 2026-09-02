# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass

from .beat_warp import beat_warp_parameters
from .models import DirectedTimeline, EventType, VisualCue


@dataclass(frozen=True)
class EditConfig:
    enabled: bool = True
    intensity: float = 1.0
    # Density controls *occurrence*. Normal presets deliberately stay below the
    # destructive threshold; Experimental/Glitch is expected to opt into it.
    density: float = 0.35
    retrigger_on_bars: bool = True
    onset_slices: bool = True


def attach_edit_plan(timeline: DirectedTimeline, config: EditConfig | None = None) -> DirectedTimeline:
    """Add sparse, musically timed movement/emphasis cues.

    Editing, source motion, semantic composition, and directed color are the
    primary visual grammar. Beat warp/punch are lightweight motion accents.
    Raster/glitch effects share a global spacing budget and destructive families
    require explicitly high effect density, so normal timelines cannot drift into
    persistent striping, kaleidoscope, datamosh, or chroma-noise wallpaper.
    """
    cfg = config or EditConfig()
    if not cfg.enabled or not timeline.scene_plan:
        return timeline

    intensity = max(0.0, min(2.0, cfg.intensity))
    density = max(0.0, min(2.5, cfg.density))
    accent_scale = min(1.35, density / 0.65) if density > 0.0 else 0.0
    destructive_scale = max(0.0, min(1.0, (density - 0.85) / 0.80))
    section_by_time = sorted(timeline.track.sections, key=lambda s: s.start)
    scene_sections = {s.section_index for s in timeline.scene_plan}
    cues = [c for c in timeline.cues if not c.action.startswith("video_edit_")]
    last_effect_time: dict[str, float] = {}
    last_visual_emphasis = -1.0e9
    last_destructive = -1.0e9

    destructive_actions = {
        "video_edit_strobe",
        "video_edit_kaleidoscope",
        "video_edit_edge",
        "video_edit_slitscan",
        "video_edit_solarize",
        "video_edit_datamosh",
        "video_edit_slice_recursion",
        "video_edit_chroma_delay",
        "video_edit_freeze",
    }
    visual_emphasis_actions = destructive_actions | {
        "video_edit_ripple",
        "video_edit_vortex",
        "video_edit_tunnel",
        "video_edit_corridor",
        "video_edit_mask",
        "video_edit_motion_trails",
        "video_edit_switch",
    }

    def section_at(t: float):
        for section in reversed(section_by_time):
            if section.start <= t < section.end:
                return section
        return section_by_time[-1] if section_by_time else None

    def deterministic_unit(time: float, action: str) -> float:
        # Stable across rebuilds and runtimes; exact cryptographic quality is not
        # useful here, only deterministic artistic decisions.
        key = sum((index + 1) * ord(ch) for index, ch in enumerate(action))
        value = (int(round(time * 1000.0)) * 1103515245 + key * 12345) & 0x7FFFFFFF
        return value / 0x7FFFFFFF

    def add_effect(
        time: float,
        action: str,
        parameters: dict,
        *,
        cooldown: float = 0.0,
        probability: float = 1.0,
        allow_pair: bool = False,
    ) -> bool:
        """Append one sparse cue if the shared treatment budget permits it."""
        nonlocal last_visual_emphasis, last_destructive
        last = last_effect_time.get(action, -1.0e9)
        if cooldown > 0.0 and time - last < cooldown - 1.0e-9:
            return False

        if action in destructive_actions:
            if destructive_scale <= 0.0:
                return False
            probability *= destructive_scale
            if time - last_destructive < 2.75:
                return False
        elif action in visual_emphasis_actions:
            probability *= accent_scale

        if action in visual_emphasis_actions:
            if probability <= 0.0 or deterministic_unit(time, action) > min(0.96, probability):
                return False
            if not allow_pair and time - last_visual_emphasis < 0.22:
                return False

        cues.append(VisualCue(time=time, action=action, parameters=parameters))
        last_effect_time[action] = time
        if action in visual_emphasis_actions:
            last_visual_emphasis = time
        if action in destructive_actions:
            last_destructive = time
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

            # Movement bed: short, topology-varying, and intentionally lower than
            # previous defaults so source motion remains legible.
            cues.append(VisualCue(
                time=event.time,
                action="video_edit_beat_warp",
                parameters=beat_warp_parameters(
                    event,
                    beat_index=beat_ord,
                    tempo_bpm=timeline.track.tempo_bpm,
                    section=section,
                    amount=min(0.62, intensity * (0.10 + 0.34 * accent)),
                ),
            ))

            if low + mid + high <= 1e-9:
                add_effect(
                    event.time,
                    "video_edit_punch",
                    {
                        "amount": min(0.72, intensity * (0.08 + energy * 0.16 + event.strength * 0.12)),
                        "duration": min(0.18, beat_seconds * 0.24),
                    },
                    cooldown=max(0.12, beat_seconds * 0.72),
                )
                if energy > 0.62 and beat_ord % 4 == 2:
                    add_effect(
                        event.time,
                        "video_edit_tunnel",
                        {"amount": min(0.46, intensity * energy * 0.30)},
                        cooldown=max(1.1, beat_seconds * 3.0),
                        probability=.34,
                    )
                continue

            if low >= max(mid, high) and low > 0.38:
                add_effect(
                    event.time,
                    "video_edit_punch",
                    {
                        "amount": min(0.76, intensity * (0.06 + low * 0.30 + accent * 0.14)),
                        "duration": min(0.18, beat_seconds * 0.24),
                    },
                    cooldown=max(0.12, beat_seconds * 0.68),
                )
                if beat_ord % 2 == 1 or (accent > 0.84 and beat_ord % 4 == 0):
                    add_effect(
                        event.time,
                        "video_edit_ripple",
                        {"amount": min(0.54, intensity * (0.06 + low * 0.30 + accent * 0.08))},
                        cooldown=max(0.62, beat_seconds * 1.5),
                        probability=.50,
                    )

            if high > max(low, mid) and high > 0.42:
                # RGB/chroma separation is digital damage, not the default way to
                # express treble. It is available only in high-density treatments.
                add_effect(
                    event.time,
                    "video_edit_chroma_delay",
                    {"amount": min(0.40, intensity * (0.04 + high * 0.24))},
                    cooldown=max(1.4, beat_seconds * 3.0),
                    probability=.16,
                )
                if high > 0.72 and accent > 0.68 and beat_ord % 8 == 6:
                    add_effect(
                        event.time,
                        "video_edit_slitscan",
                        {"amount": min(0.34, intensity * high * 0.24)},
                        cooldown=max(3.0, beat_seconds * 7.0),
                        probability=.10,
                    )

            if mid > max(low, high) and mid > 0.52 and accent > 0.56 and beat_ord % 4 == 0:
                add_effect(
                    event.time,
                    "video_edit_vortex",
                    {"amount": min(0.38, intensity * mid * 0.22)},
                    cooldown=max(1.2, beat_seconds * 3.0),
                    probability=.30,
                )

            if accent > 0.72 and energy > 0.66:
                if beat_ord % (4 if energy > 0.84 else 8) == 0:
                    add_effect(
                        event.time,
                        "video_edit_retrigger",
                        {
                            "back_seconds": min(beat_seconds * 0.30, 0.15),
                            "amount": min(0.72, intensity * accent * energy),
                        },
                        cooldown=max(0.9, beat_seconds * 2.2),
                    )
                if section.percussive_ratio > 0.72 and beat_ord % 16 == 14:
                    add_effect(
                        event.time,
                        "video_edit_datamosh",
                        {"amount": min(0.40, intensity * accent * section.percussive_ratio * 0.34)},
                        cooldown=max(4.0, beat_seconds * 9.0),
                        probability=.08,
                    )

            if section.label == "peak" and accent > 0.82 and beat_ord % 8 == 0:
                add_effect(
                    event.time,
                    "video_edit_switch",
                    {"amount": min(0.72, intensity * accent)},
                    cooldown=max(1.4, beat_seconds * 3.5),
                    probability=.18,
                )

        elif event.type == EventType.BAR and cfg.retrigger_on_bars:
            if section.label in {"build", "peak"}:
                # Source-time jump is editorial rather than raster treatment.
                add_effect(
                    event.time,
                    "video_edit_jump",
                    {
                        "fraction": ((section.index * 37 + int(event.time * 10)) % 73) / 100.0,
                        "amount": min(0.62, intensity * (0.24 + energy * 0.28)),
                    },
                    cooldown=1.0,
                )

                tonal_symmetry = (
                    (section.tonal_stability > 0.72 and section.vibe in {"hypnotic", "euphoric"})
                    or (section.tonal_stability == 0.0 and section.vibe == "neutral")
                )
                if density >= 1.45 and tonal_symmetry and (bar_ord - 1) % 4 == 0:
                    add_effect(
                        event.time,
                        "video_edit_kaleidoscope",
                        {"amount": min(0.30, intensity * (0.04 + section.tonal_stability * 0.12))},
                        cooldown=5.0,
                        probability=.08,
                    )
                if density >= 1.10 and bar_ord % 4 == 0:
                    add_effect(
                        event.time,
                        "video_edit_slitscan",
                        {"amount": min(0.32, intensity * (0.04 + energy * 0.20))},
                        cooldown=4.0,
                        probability=.08,
                    )
                if density >= 1.35 and energy > 0.84 and section.label == "peak" and bar_ord % 8 == 0:
                    add_effect(
                        event.time,
                        "video_edit_slice_recursion",
                        {"amount": min(0.30, intensity * (0.05 + energy * 0.20))},
                        cooldown=5.0,
                        probability=.06,
                    )

        elif event.type == EventType.TEMPO_CHANGE:
            add_effect(
                event.time,
                "video_edit_tempo_warp",
                {
                    "amount": min(0.58, intensity * (0.16 + event.strength * 0.36)),
                    "from_bpm": event.payload.get("from_bpm"),
                    "to_bpm": event.payload.get("to_bpm"),
                },
                cooldown=1.0,
            )

        elif event.type == EventType.HARMONIC_CHANGE:
            # Exactly one bridge treatment. Directed hue/saturation ramps carry
            # the color transition; this cue contributes one spatial punctuation.
            variant = (section.index + int(event.time * 10)) % 4
            if event.strength > 0.68 and density >= 1.10 and variant == 0:
                add_effect(
                    event.time,
                    "video_edit_edge",
                    {"amount": min(0.34, intensity * event.strength * 0.26)},
                    cooldown=3.0,
                    probability=.08,
                )
            elif variant == 1:
                add_effect(
                    event.time,
                    "video_edit_vortex",
                    {"amount": min(0.36, intensity * event.strength * 0.26)},
                    cooldown=1.5,
                    probability=.28,
                )
            else:
                add_effect(
                    event.time,
                    "video_edit_ripple",
                    {"amount": min(0.46, intensity * (0.10 + event.strength * 0.24))},
                    cooldown=1.2,
                    probability=.36,
                )

        elif event.type == EventType.ONSET and cfg.onset_slices and event.strength > 0.48:
            low = max(0.0, min(1.0, float(event.payload.get("low", 0.0))))
            mid = max(0.0, min(1.0, float(event.payload.get("mid", 0.0))))
            high = max(0.0, min(1.0, float(event.payload.get("high", 0.0))))
            dominant = event.payload.get("dominant_band")

            # The former video_edit_slice cue was interpreted by native as
            # horizontal slice_recursion. Onsets now use movement-only accents.
            if dominant == "low" and low > 0.38:
                add_effect(
                    event.time,
                    "video_edit_beat_warp",
                    {
                        "amount": min(0.46, intensity * event.strength * (0.20 + low * 0.30)),
                        "low": low,
                        "mid": mid,
                        "high": high,
                    },
                    cooldown=0.24,
                )
            elif dominant == "mid" and mid > 0.44 and event.strength > 0.64:
                add_effect(
                    event.time,
                    "video_edit_vortex",
                    {"amount": min(0.30, intensity * event.strength * mid * 0.22)},
                    cooldown=1.4,
                    probability=.22,
                )
            elif high > 0.52 and event.strength > 0.68:
                add_effect(
                    event.time,
                    "video_edit_chroma_delay",
                    {"amount": min(0.28, intensity * high * event.strength * 0.22)},
                    cooldown=2.2,
                    probability=.08,
                )

        elif event.type == EventType.DROP_CANDIDATE:
            strength = max(0.0, min(1.0, event.strength))
            # One visual punctuation. The cut, multi-source composition and color
            # trajectory do the heavy lifting at the drop.
            variant = (section.index + int(event.time * 10)) % 4
            if variant == 0:
                add_effect(
                    event.time,
                    "video_edit_tunnel",
                    {"amount": min(0.50, intensity * strength * 0.42)},
                    cooldown=2.0,
                    probability=.42,
                )
            elif variant == 1:
                add_effect(
                    event.time,
                    "video_edit_ripple",
                    {"amount": min(0.54, intensity * strength * 0.46)},
                    cooldown=1.6,
                    probability=.48,
                )
            elif variant == 2:
                add_effect(
                    event.time,
                    "video_edit_mask",
                    {"amount": min(0.40, intensity * strength * 0.34)},
                    cooldown=2.0,
                    probability=.36,
                )
            else:
                add_effect(
                    event.time,
                    "video_edit_motion_trails",
                    {"amount": min(0.38, intensity * strength * 0.32)},
                    cooldown=2.0,
                    probability=.32,
                )

    cues.sort(key=lambda cue: (cue.time, cue.action))
    return timeline.model_copy(update={"cues": cues})
