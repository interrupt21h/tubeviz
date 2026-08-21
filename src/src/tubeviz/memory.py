from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .models import MusicalMotif, VisualMemoryItem, WorldSnapshot


_SHAPES = ("orb", "monolith", "portal", "lattice", "glyph", "satellite")


def _stable_u64(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def create_visual_memory(motifs: list[MusicalMotif]) -> list[VisualMemoryItem]:
    """Create deterministic visual identities for recurring musical motifs."""
    items: list[VisualMemoryItem] = []
    for motif in motifs:
        seed = _stable_u64(motif.id)
        first = motif.occurrences[0]
        items.append(
            VisualMemoryItem(
                id=f"visual_{motif.id}",
                motif_id=motif.id,
                introduced_at=first.start,
                shape=_SHAPES[seed % len(_SHAPES)],
                hue=float(seed % 360),
                scale=0.75 + ((seed >> 9) % 80) / 100.0,
            )
        )
    return items


@dataclass
class WorldStateBuilder:
    """
    Build serializable snapshots of the persistent visual world.

    Memory depth grows as motif callbacks happen. The renderer can use this to
    make later worlds visually denser rather than treating every section as a
    fresh scene.
    """

    seen_motifs: set[str] = field(default_factory=set)
    motif_recurrences: dict[str, int] = field(default_factory=dict)

    def build(
        self,
        *,
        section_index: int,
        section_start: float,
        section_label: str,
        energy: float,
        motifs_here: list[tuple[str, int]],
    ) -> WorldSnapshot:
        active: list[str] = []
        for motif_id, ordinal in motifs_here:
            active.append(motif_id)
            self.seen_motifs.add(motif_id)
            self.motif_recurrences[motif_id] = max(
                self.motif_recurrences.get(motif_id, 0), ordinal - 1
            )

        return WorldSnapshot(
            time=section_start,
            world_id=section_index + 1,
            section_index=section_index,
            section_label=section_label,
            energy=energy,
            active_motif_ids=active,
            memory_depth=sum(self.motif_recurrences.values()),
        )
