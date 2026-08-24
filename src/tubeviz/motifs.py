# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import MotifOccurrence, MusicalMotif, Section, TrackAnalysis


@dataclass(frozen=True)
class MotifConfig:
    similarity_threshold: float = 0.90
    min_separation_sections: int = 2
    minimum_occurrences: int = 2


def cosine_similarity(a: list[float], b: list[float]) -> float:
    av = np.asarray(a, dtype=float)
    bv = np.asarray(b, dtype=float)
    if av.size == 0 or bv.size == 0 or av.shape != bv.shape:
        return -1.0
    denominator = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denominator <= 1e-12:
        return -1.0
    return float(np.dot(av, bv) / denominator)


def _eligible(candidate: Section, occurrence_sections: list[int], cfg: MotifConfig) -> bool:
    return all(
        abs(candidate.index - previous) >= cfg.min_separation_sections
        for previous in occurrence_sections
    )


def discover_motifs(
    track: TrackAnalysis,
    config: MotifConfig | None = None,
) -> list[MusicalMotif]:
    """
    Greedily group recurring section fingerprints.

    Each retained motif must occur at least twice and occurrences are forced to
    be separated in time so adjacent windows are not mistaken for recurrence.
    """
    cfg = config or MotifConfig()
    assigned: set[int] = set()
    motifs: list[MusicalMotif] = []

    for prototype in track.sections:
        if prototype.index in assigned or not prototype.fingerprint:
            continue

        matches: list[tuple[Section, float]] = [(prototype, 1.0)]
        occurrence_sections = [prototype.index]

        for candidate in track.sections[prototype.index + 1 :]:
            if candidate.index in assigned or not candidate.fingerprint:
                continue
            if not _eligible(candidate, occurrence_sections, cfg):
                continue

            similarity = cosine_similarity(prototype.fingerprint, candidate.fingerprint)
            if similarity >= cfg.similarity_threshold:
                matches.append((candidate, similarity))
                occurrence_sections.append(candidate.index)

        if len(matches) < cfg.minimum_occurrences:
            continue

        motif_id = f"motif_{len(motifs) + 1:02d}"
        occurrences = [
            MotifOccurrence(
                section_index=section.index,
                start=section.start,
                end=section.end,
                similarity=similarity,
                ordinal=ordinal,
            )
            for ordinal, (section, similarity) in enumerate(matches, start=1)
        ]
        motifs.append(
            MusicalMotif(
                id=motif_id,
                prototype_section=prototype.index,
                fingerprint=list(prototype.fingerprint),
                occurrences=occurrences,
            )
        )
        assigned.update(section.index for section, _ in matches)

    return motifs
