# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import math
from typing import Any

from .models import MusicalEvent, Section

WARP_MODES = (
    "radial_push",
    "radial_pinch",
    "shear",
    "twist",
    "wave",
    "saddle",
    "lens",
    "spiral",
)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _unit(seed: str, lane: int) -> float:
    digest = hashlib.blake2s(f"{seed}:{lane}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") / float(2**64 - 1)


def _dominant_band(low: float, mid: float, high: float, payload: dict[str, Any]) -> str:
    named = str(payload.get("dominant_band", "")).lower()
    if named in {"low", "mid", "high"}:
        return named
    if low >= mid and low >= high:
        return "low"
    if high >= low and high >= mid:
        return "high"
    return "mid"


def beat_warp_parameters(
    event: MusicalEvent,
    *,
    beat_index: int,
    tempo_bpm: float,
    section: Section | None = None,
    amount: float | None = None,
) -> dict[str, Any]:
    """Build one deterministic, musically informed deformation event.

    The descriptor intentionally contains renderer-agnostic geometry. Browser
    WebGPU, Canvas2D fallback, and the native renderer consume the same mode,
    center, direction, polarity, frequency, and envelope instead of inventing
    unrelated random warps at render time.
    """
    payload = event.payload
    accent = _clamp(float(payload.get("accent", event.strength)))
    low = _clamp(float(payload.get("low", 0.0)))
    mid = _clamp(float(payload.get("mid", 0.0)))
    high = _clamp(float(payload.get("high", 0.0)))
    pulse = _clamp(float(payload.get("pulse", 0.0)))
    bpm = max(1.0, float(payload.get("local_bpm", section.local_tempo_bpm if section else tempo_bpm)))
    beat_seconds = 60.0 / bpm
    section_index = int(section.index if section else 0)
    section_energy = _clamp(float(section.energy if section else event.strength))
    bar_position = max(0, beat_index - 1) % 4
    phrase_index = max(0, beat_index - 1) // 8
    family = (section_index + phrase_index) % 4
    band = _dominant_band(low, mid, high, payload)

    # Each spectral band receives a family of related deformations. Phrase-level
    # family rotation keeps a section coherent while changing the visual grammar
    # every few bars. Downbeats/accented lows deliberately favor impact modes.
    families = {
        "low": (
            (0, 6, 1, 0),
            (6, 0, 1, 7),
            (0, 1, 6, 3),
            (6, 7, 0, 1),
        ),
        "mid": (
            (2, 3, 5, 2),
            (3, 5, 2, 4),
            (5, 2, 3, 7),
            (2, 4, 5, 3),
        ),
        "high": (
            (4, 2, 5, 4),
            (2, 4, 3, 5),
            (5, 4, 2, 7),
            (4, 5, 3, 2),
        ),
    }
    mode_id = families[band][family][bar_position]
    if accent > 0.82 and bar_position == 0:
        mode_id = 6 if band != "mid" else 3
    elif accent > 0.88 and band == "low":
        mode_id = 0 if (beat_index + section_index) % 2 else 1

    seed = f"{section_index}:{beat_index}:{event.time:.6f}:{band}:{family}"
    r0, r1, r2, r3 = (_unit(seed, lane) for lane in range(4))
    polarity = 1.0 if ((beat_index + section_index + family) % 2 == 0) else -1.0

    # Keep strong impact centers nearer the composition center; directional and
    # high-frequency warps are allowed to wander farther for visible variety.
    spread = 0.12 if mode_id in {0, 1, 6} else 0.24
    center_x = _clamp(0.5 + (r0 - 0.5) * spread * 2.0, 0.16, 0.84)
    center_y = _clamp(0.5 + (r1 - 0.5) * spread * 1.6, 0.18, 0.82)
    direction = ((bar_position * math.pi / 2.0) + (r2 - 0.5) * 0.85 + family * 0.31) % (2.0 * math.pi)
    spectral_speed = 0.75 * low + 1.15 * mid + 1.65 * high
    frequency = _clamp(0.72 + spectral_speed + 0.32 * r3 + 0.18 * pulse, 0.65, 2.8)

    # Short local envelopes make each hit an event instead of a permanently
    # decaying global wobble. Accents get faster attacks and a little rebound.
    duration = _clamp(beat_seconds * (0.30 + 0.16 * pulse + 0.10 * accent), 0.075, 0.42)
    attack = _clamp(0.12 - 0.065 * accent, 0.035, 0.12)
    overshoot = _clamp(0.08 + 0.22 * accent + 0.10 * low, 0.06, 0.34)
    resolved_amount = _clamp(amount if amount is not None else 0.18 + 0.68 * accent)

    return {
        "amount": resolved_amount,
        "low": low,
        "mid": mid,
        "high": high,
        "pulse": pulse,
        "local_bpm": bpm,
        "dominant_band": band,
        "warp_mode": WARP_MODES[mode_id],
        "warp_mode_id": mode_id,
        "warp_family": family,
        "warp_variant": (beat_index + family * 3 + bar_position) % 8,
        "bar_position": bar_position,
        "phrase_index": phrase_index,
        "center_x": center_x,
        "center_y": center_y,
        "direction": direction,
        "frequency": frequency,
        "polarity": polarity,
        "duration": duration,
        "attack": attack,
        "overshoot": overshoot,
        "section_energy": section_energy,
    }
