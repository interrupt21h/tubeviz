from __future__ import annotations

from collections import defaultdict

from .lookahead import LookaheadConfig, plan_lookahead_cues
from .memory import WorldStateBuilder, create_visual_memory
from .models import DirectedTimeline, EventType, TrackAnalysis, VisualCue
from .motifs import MotifConfig, discover_motifs


def _reactive_cues(track: TrackAnalysis) -> list[VisualCue]:
    cues: list[VisualCue] = []
    section_world = 0

    for event in track.events:
        if event.type == EventType.BEAT:
            accent = float(event.payload.get("accent", event.strength))
            low = float(event.payload.get("low", 0.0))
            mid = float(event.payload.get("mid", 0.0))
            high = float(event.payload.get("high", 0.0))
            cues.append(
                VisualCue(
                    time=event.time,
                    action="camera_impulse",
                    parameters={
                        "amount": 0.010 + 0.045 * min(1.0, accent),
                        "decay": 0.16,
                    },
                )
            )
            if any(key in event.payload for key in ("low", "mid", "high", "pulse", "local_bpm")):
                cues.append(
                    VisualCue(
                        time=event.time,
                        action="beat_warp",
                        parameters={
                            "amount": min(1.0, 0.18 + 0.68 * accent),
                            "low": low,
                            "mid": mid,
                            "high": high,
                            "pulse": float(event.payload.get("pulse", 0.0)),
                            "local_bpm": float(event.payload.get("local_bpm", track.tempo_bpm)),
                            "dominant_band": event.payload.get("dominant_band", "mid"),
                        },
                    )
                )

        elif event.type == EventType.BAR:
            cues.append(
                VisualCue(
                    time=event.time,
                    action="bar_pulse",
                    parameters={"amount": 0.22},
                )
            )

        elif event.type == EventType.ONSET:
            cues.append(
                VisualCue(
                    time=event.time,
                    action="spawn_fragment",
                    parameters={
                        "count": max(1, int(round(2 + 8 * event.strength))),
                        "velocity": 0.35 + event.strength,
                    },
                )
            )

        elif event.type == EventType.ENERGY:
            cues.append(
                VisualCue(
                    time=event.time,
                    action="energy_bloom",
                    parameters={
                        "amount": event.strength,
                        "brightness": event.payload.get("brightness", 0.5),
                        "bass_weight": event.payload.get("bass_weight", 0.0),
                        "percussive_ratio": event.payload.get("percussive_ratio", 0.0),
                    },
                )
            )

        elif event.type == EventType.HARMONIC_CHANGE:
            cues.append(
                VisualCue(
                    time=event.time,
                    action="harmonic_warp",
                    parameters={
                        "amount": event.strength,
                        "duration": 0.65 + 1.5 * event.strength,
                        "brightness": event.payload.get("brightness", 0.5),
                        "tonal_stability": event.payload.get("tonal_stability", 0.5),
                    },
                )
            )

        elif event.type == EventType.TEMPO_CHANGE:
            cues.append(
                VisualCue(
                    time=event.time,
                    action="tempo_shift",
                    parameters={
                        "amount": event.strength,
                        **event.payload,
                    },
                )
            )

        elif event.type == EventType.SECTION:
            section_world += 1
            cues.append(
                VisualCue(
                    time=event.time,
                    action="enter_section",
                    parameters={
                        "world": section_world,
                        "label": event.payload["label"],
                        "vibe": event.payload.get("vibe", "neutral"),
                        "key": event.payload.get("key"),
                        "energy": event.strength,
                        "local_bpm": event.payload.get("local_bpm", track.tempo_bpm),
                        "bass_weight": event.payload.get("bass_weight", 0.0),
                        "percussive_ratio": event.payload.get("percussive_ratio", 0.0),
                        "tonal_stability": event.payload.get("tonal_stability", 0.0),
                        "brightness": event.payload.get("brightness", 0.0),
                    },
                )
            )

        elif event.type == EventType.DROP_CANDIDATE:
            cues.append(
                VisualCue(
                    time=event.time,
                    action="phase_transition",
                    parameters={
                        "amount": event.strength,
                        **event.payload,
                    },
                )
            )

    return cues


def direct(
    track: TrackAnalysis,
    *,
    motif_config: MotifConfig | None = None,
    lookahead_config: LookaheadConfig | None = None,
) -> DirectedTimeline:
    """
    Build the complete deterministic direction plan.

    Two timing classes are intentionally merged here:

    * reactive cues: objective beat/onset/energy events that must land exactly;
    * narrative cues: precomputed motif introduction, foreshadowing and recall.

    A future LLM can add scene semantics to the narrative layer without owning
    the hard real-time clock.
    """
    motifs = discover_motifs(track, motif_config)
    visual_memory = create_visual_memory(motifs)

    occurrences_by_section: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for motif in motifs:
        for occurrence in motif.occurrences:
            occurrences_by_section[occurrence.section_index].append(
                (motif.id, occurrence.ordinal)
            )

    world_builder = WorldStateBuilder()
    world_states = [
        world_builder.build(
            section_index=section.index,
            section_start=section.start,
            section_label=section.label,
            energy=section.energy,
            motifs_here=occurrences_by_section.get(section.index, []),
        )
        for section in track.sections
    ]

    cues = _reactive_cues(track)
    cues.extend(plan_lookahead_cues(track, motifs, visual_memory, lookahead_config))

    # World-state snapshots are emitted as cues as well as retained as metadata,
    # so a stateless renderer can reconstruct persistent memory after a seek.
    for snapshot in world_states:
        cues.append(
            VisualCue(
                time=snapshot.time,
                action="world_state",
                parameters=snapshot.model_dump(mode="json"),
            )
        )

    cues.sort(key=lambda cue: (cue.time, cue.action))
    return DirectedTimeline(
        track=track,
        cues=cues,
        motifs=motifs,
        visual_memory=visual_memory,
        world_states=world_states,
    )
