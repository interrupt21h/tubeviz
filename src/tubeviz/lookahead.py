from __future__ import annotations

from dataclasses import dataclass

from .models import MusicalMotif, TrackAnalysis, VisualCue, VisualMemoryItem


@dataclass(frozen=True)
class LookaheadConfig:
    foreshadow_bars: int = 4
    anticipation_bars: int = 1


def _bar_before(track: TrackAnalysis, target: float, bars_back: int) -> float:
    previous = [value for value in track.bars if value < target]
    if not previous:
        return max(0.0, target - bars_back * 60.0 / track.tempo_bpm * 4.0)
    index = max(0, len(previous) - bars_back)
    return previous[index]


def plan_lookahead_cues(
    track: TrackAnalysis,
    motifs: list[MusicalMotif],
    visual_memory: list[VisualMemoryItem],
    config: LookaheadConfig | None = None,
) -> list[VisualCue]:
    """
    Pre-plan visual foreshadowing and motif callbacks using knowledge of the
    complete track. This is the layer a future LLM director can enrich.
    """
    cfg = config or LookaheadConfig()
    visual_by_motif = {item.motif_id: item for item in visual_memory}
    cues: list[VisualCue] = []

    for motif in motifs:
        visual = visual_by_motif[motif.id]
        first = motif.occurrences[0]
        cues.append(
            VisualCue(
                time=first.start,
                action="introduce_motif",
                parameters={
                    "motif_id": motif.id,
                    "visual_id": visual.id,
                    "shape": visual.shape,
                    "hue": visual.hue,
                    "scale": visual.scale,
                    "occurrence": 1,
                },
            )
        )

        for occurrence in motif.occurrences[1:]:
            foreshadow_time = _bar_before(track, occurrence.start, cfg.foreshadow_bars)
            anticipation_time = _bar_before(track, occurrence.start, cfg.anticipation_bars)

            if foreshadow_time < occurrence.start:
                cues.append(
                    VisualCue(
                        time=foreshadow_time,
                        action="foreshadow_motif",
                        parameters={
                            "motif_id": motif.id,
                            "visual_id": visual.id,
                            "shape": visual.shape,
                            "hue": visual.hue,
                            "target_time": occurrence.start,
                            "occurrence": occurrence.ordinal,
                            "similarity": occurrence.similarity,
                            "opacity": 0.12,
                        },
                    )
                )

            if anticipation_time > foreshadow_time and anticipation_time < occurrence.start:
                cues.append(
                    VisualCue(
                        time=anticipation_time,
                        action="anticipate_motif",
                        parameters={
                            "motif_id": motif.id,
                            "visual_id": visual.id,
                            "target_time": occurrence.start,
                            "occurrence": occurrence.ordinal,
                            "amount": 0.35 + 0.35 * occurrence.similarity,
                        },
                    )
                )

            cues.append(
                VisualCue(
                    time=occurrence.start,
                    action="recall_motif",
                    parameters={
                        "motif_id": motif.id,
                        "visual_id": visual.id,
                        "shape": visual.shape,
                        "hue": visual.hue,
                        "scale": visual.scale * (1.0 + 0.12 * (occurrence.ordinal - 1)),
                        "occurrence": occurrence.ordinal,
                        "similarity": occurrence.similarity,
                        "mutation": occurrence.ordinal - 1,
                    },
                )
            )

    return sorted(cues, key=lambda cue: (cue.time, cue.action))
