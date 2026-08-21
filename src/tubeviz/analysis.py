from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
from scipy.ndimage import median_filter

from .models import EventType, MusicalEvent, Section, TempoPoint, TrackAnalysis


PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


@dataclass(frozen=True)
class AnalysisConfig:
    sample_rate: int = 22050
    hop_length: int = 512
    beats_per_bar: int = 4
    section_seconds: float = 16.0
    section_bars: int = 8
    onset_quantile: float = 0.80
    energy_quantile: float = 0.85
    harmonic_change_quantile: float = 0.90
    tempo_window_seconds: float = 8.0
    tempo_smoothing_seconds: float = 2.0
    tempo_curve_seconds: float = 2.0
    tempo_change_bpm: float = 4.0
    min_tempo: float = 55.0
    max_tempo: float = 210.0
    tempo_octave_min: float = 75.0
    tempo_octave_max: float = 190.0


def _normalise(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return values
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros_like(values)
    lo = float(np.quantile(finite, 0.02))
    hi = float(np.quantile(finite, 0.98))
    if hi <= lo:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def _resize_feature(values: np.ndarray, n_frames: int) -> np.ndarray:
    values = np.asarray(values, dtype=float).reshape(-1)
    if n_frames <= 0:
        return np.zeros(0, dtype=float)
    if values.size == n_frames:
        return values
    if values.size == 0:
        return np.zeros(n_frames, dtype=float)
    x_old = np.linspace(0.0, 1.0, values.size)
    x_new = np.linspace(0.0, 1.0, n_frames)
    return np.interp(x_new, x_old, values)


def _estimate_key(chroma: np.ndarray) -> str | None:
    if chroma.size == 0:
        return None
    profile = np.mean(chroma, axis=1)
    if not np.any(profile):
        return None

    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    profile = (profile - profile.mean()) / (profile.std() + 1e-12)

    best_score = -np.inf
    best_name: str | None = None
    for root in range(12):
        for template, suffix in ((major, "major"), (minor, "minor")):
            rotated = np.roll(template, root)
            rotated = (rotated - rotated.mean()) / (rotated.std() + 1e-12)
            score = float(np.dot(profile, rotated))
            if score > best_score:
                best_score = score
                best_name = f"{PITCH_CLASSES[root]} {suffix}"
    return best_name


def _frame_key(chroma: np.ndarray, frame_slice: slice) -> str | None:
    return _estimate_key(chroma[:, frame_slice])


def _fold_tempo_octaves(values: np.ndarray, cfg: AnalysisConfig) -> np.ndarray:
    """Fold octave-equivalent tempo estimates into a preferred DJ BPM range."""
    out = np.asarray(values, dtype=float).copy()
    if cfg.tempo_octave_min <= 0 or cfg.tempo_octave_max <= cfg.tempo_octave_min:
        return out
    for i, value in enumerate(out):
        while value < cfg.tempo_octave_min and value * 2.0 <= cfg.max_tempo:
            value *= 2.0
        while value > cfg.tempo_octave_max and value / 2.0 >= cfg.min_tempo:
            value /= 2.0
        out[i] = value
    return out


def _dynamic_tempo(
    onset_env: np.ndarray,
    *,
    sr: int,
    hop_length: int,
    cfg: AnalysisConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return smoothed frame-wise BPM, confidence, and pulse curve.

    librosa.feature.tempo(..., aggregate=None) produces an independent tempo
    estimate per analysis frame.  We median-smooth that trajectory and feed it
    back into beat_track's frame-wise ``bpm`` input.
    """
    n_frames = len(onset_env)
    raw = librosa.feature.tempo(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=hop_length,
        ac_size=max(2.0, cfg.tempo_window_seconds),
        max_tempo=cfg.max_tempo,
        aggregate=None,
    )
    raw = _resize_feature(np.asarray(raw, dtype=float), n_frames)
    raw = np.nan_to_num(raw, nan=120.0, posinf=cfg.max_tempo, neginf=cfg.min_tempo)
    raw = np.clip(raw, cfg.min_tempo, cfg.max_tempo)
    raw = _fold_tempo_octaves(raw, cfg)

    smooth_frames = max(1, int(round(cfg.tempo_smoothing_seconds * sr / hop_length)))
    if smooth_frames % 2 == 0:
        smooth_frames += 1
    bpm = median_filter(raw, size=smooth_frames, mode="nearest")
    bpm = np.clip(bpm, cfg.min_tempo, cfg.max_tempo)

    tg = librosa.feature.tempogram(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=hop_length,
        win_length=max(32, int(round(cfg.tempo_window_seconds * sr / hop_length))),
    )
    if tg.size:
        peak = np.max(tg, axis=0)
        mean = np.mean(tg, axis=0) + 1e-9
        sharpness = np.clip((peak / mean - 1.0) / 6.0, 0.0, 1.0)
        confidence = _resize_feature(sharpness, n_frames)
    else:
        confidence = np.zeros(n_frames, dtype=float)

    pulse = librosa.beat.plp(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=hop_length,
        win_length=max(32, int(round(cfg.tempo_window_seconds * sr / hop_length))),
        tempo_min=cfg.min_tempo,
        tempo_max=cfg.max_tempo,
    )
    pulse = _normalise(_resize_feature(np.asarray(pulse, dtype=float), n_frames))
    confidence = np.clip(0.72 * confidence + 0.28 * pulse, 0.0, 1.0)
    return bpm, confidence, pulse


def _band_flux(
    magnitude: np.ndarray,
    *,
    sr: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Frequency-aware transient strengths and bass energy ratio."""
    power = magnitude**2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=(magnitude.shape[0] - 1) * 2)
    low_mask = freqs < 180.0
    mid_mask = (freqs >= 180.0) & (freqs < 2800.0)
    high_mask = freqs >= 2800.0

    db = librosa.power_to_db(power + 1e-12, ref=np.max)
    delta = np.maximum(0.0, np.diff(db, axis=1, prepend=db[:, :1]))

    def flux(mask: np.ndarray) -> np.ndarray:
        if not np.any(mask):
            return np.zeros(power.shape[1], dtype=float)
        return _normalise(np.mean(delta[mask], axis=0))

    total = np.sum(power, axis=0) + 1e-12
    bass_weight = np.clip(np.sum(power[low_mask], axis=0) / total, 0.0, 1.0)
    return flux(low_mask), flux(mid_mask), flux(high_mask), bass_weight


def _infer_bar_times(
    beat_times: np.ndarray,
    beat_accents: np.ndarray,
    *,
    beats_per_bar: int,
    block_beats: int = 32,
) -> np.ndarray:
    """Choose a likely downbeat phase independently in long blocks.

    This does not claim full downbeat transcription; it prevents a single early
    phase mistake from controlling an hour-long mix and uses low-frequency /
    onset accents to re-establish bar phase as the mix evolves.
    """
    if len(beat_times) == 0:
        return np.zeros(0, dtype=float)
    if beats_per_bar <= 1:
        return beat_times.copy()

    bar_indices: list[int] = []
    n = len(beat_times)
    for block_start in range(0, n, block_beats):
        block_end = min(n, block_start + block_beats)
        if block_end - block_start < beats_per_bar:
            break
        best_phase = 0
        best_score = -np.inf
        for phase in range(beats_per_bar):
            indices = np.arange(block_start + phase, block_end, beats_per_bar)
            score = float(np.mean(beat_accents[indices])) if indices.size else -np.inf
            if score > best_score:
                best_score = score
                best_phase = phase
        bar_indices.extend(range(block_start + best_phase, block_end, beats_per_bar))

    if not bar_indices:
        bar_indices = list(range(0, n, beats_per_bar))
    bar_indices = sorted(set(i for i in bar_indices if 0 <= i < n))
    # Phase can legitimately re-lock between blocks, but do not emit two
    # "downbeats" only one beat apart at a block boundary.
    filtered: list[int] = []
    min_gap = max(2, beats_per_bar - 1)
    for index in bar_indices:
        if not filtered or index - filtered[-1] >= min_gap:
            filtered.append(index)
    return beat_times[np.asarray(filtered, dtype=int)]


def _vibe(
    *,
    energy: float,
    brightness: float,
    onset_density: float,
    bass_weight: float,
    percussive_ratio: float,
    tonal_stability: float,
    noisiness: float,
    tempo: float,
) -> str:
    if energy < 0.24 and percussive_ratio < 0.48:
        return "ambient"
    if noisiness > 0.50 and onset_density > 0.42:
        return "fractured"
    if tonal_stability > 0.70 and onset_density < 0.44:
        return "hypnotic"
    if bass_weight > 0.48 and percussive_ratio > 0.56:
        return "heavy"
    if brightness > 0.64 and energy > 0.58 and tonal_stability > 0.52:
        return "euphoric"
    if brightness < 0.34 and bass_weight > 0.34:
        return "dark"
    if percussive_ratio > 0.60 and tempo >= 112:
        return "driving"
    return "groove"


def analyze_track(path: str | Path, config: AnalysisConfig | None = None) -> TrackAnalysis:
    cfg = config or AnalysisConfig()
    source = str(Path(path).expanduser().resolve())

    y, sr = librosa.load(source, sr=cfg.sample_rate, mono=True)
    if y.size == 0:
        raise ValueError(f"audio file contains no samples: {source}")

    duration = float(librosa.get_duration(y=y, sr=sr))
    magnitude = np.abs(librosa.stft(y, hop_length=cfg.hop_length))
    n_frames = magnitude.shape[1]

    onset_env = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=cfg.hop_length
    )
    onset_env = _resize_feature(onset_env, n_frames)
    onset_norm = _normalise(onset_env)

    dynamic_bpm, tempo_confidence, pulse = _dynamic_tempo(
        onset_env, sr=sr, hop_length=cfg.hop_length, cfg=cfg
    )

    # librosa 0.11 beat_track accepts a frame-wise BPM array. This is the key
    # distinction from the previous global-BPM tracker.
    _, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=cfg.hop_length,
        bpm=dynamic_bpm,
        units="frames",
    )
    beat_frames = np.asarray(beat_frames, dtype=int)
    beat_times = librosa.frames_to_time(
        beat_frames, sr=sr, hop_length=cfg.hop_length
    ).astype(float)

    low_flux, mid_flux, high_flux, bass_weight = _band_flux(magnitude, sr=sr)
    beat_idx = np.minimum(beat_frames, n_frames - 1)
    beat_strengths = onset_norm[beat_idx]
    beat_accents = np.clip(
        0.48 * low_flux[beat_idx]
        + 0.22 * mid_flux[beat_idx]
        + 0.18 * beat_strengths
        + 0.12 * pulse[beat_idx],
        0.0,
        1.0,
    )
    bar_times = _infer_bar_times(
        beat_times,
        beat_accents,
        beats_per_bar=cfg.beats_per_bar,
    )

    rms = _resize_feature(
        librosa.feature.rms(S=magnitude, frame_length=(magnitude.shape[0] - 1) * 2)[0],
        n_frames,
    )
    rms_norm = _normalise(rms)
    centroid = _resize_feature(
        librosa.feature.spectral_centroid(S=magnitude, sr=sr)[0], n_frames
    )
    centroid_norm = _normalise(centroid)
    flatness = _normalise(
        _resize_feature(librosa.feature.spectral_flatness(S=magnitude)[0], n_frames)
    )
    contrast_raw = librosa.feature.spectral_contrast(S=magnitude, sr=sr)
    contrast = _normalise(np.mean(contrast_raw, axis=0))

    harmonic_mag, percussive_mag = librosa.decompose.hpss(magnitude)
    harmonic_energy = np.sum(harmonic_mag**2, axis=0)
    percussive_energy = np.sum(percussive_mag**2, axis=0)
    percussive_ratio = np.clip(
        percussive_energy / (percussive_energy + harmonic_energy + 1e-12),
        0.0,
        1.0,
    )

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=cfg.hop_length)
    if chroma.shape[1] != n_frames:
        chroma = np.vstack([_resize_feature(row, n_frames) for row in chroma])
    key = _estimate_key(chroma)

    chroma_unit = chroma / (np.linalg.norm(chroma, axis=0, keepdims=True) + 1e-12)
    global_chroma = np.mean(chroma_unit, axis=1)
    global_chroma /= np.linalg.norm(global_chroma) + 1e-12
    tonal_stability_frame = np.clip(global_chroma @ chroma_unit, 0.0, 1.0)

    events: list[MusicalEvent] = []

    onset_threshold = float(np.quantile(onset_norm, cfg.onset_quantile))
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=cfg.hop_length,
        units="frames",
    )
    for frame in np.asarray(onset_frames, dtype=int):
        frame = min(frame, n_frames - 1)
        strength = float(onset_norm[frame])
        if strength >= onset_threshold:
            bands = {
                "low": float(low_flux[frame]),
                "mid": float(mid_flux[frame]),
                "high": float(high_flux[frame]),
            }
            dominant = max(bands, key=bands.get)
            events.append(
                MusicalEvent(
                    time=float(librosa.frames_to_time(frame, sr=sr, hop_length=cfg.hop_length)),
                    type=EventType.ONSET,
                    strength=strength,
                    payload={"dominant_band": dominant, **bands},
                )
            )

    for i, (time, frame, strength, accent) in enumerate(
        zip(beat_times, beat_frames, beat_strengths, beat_accents, strict=True)
    ):
        frame = min(int(frame), n_frames - 1)
        bands = {
            "low": float(low_flux[frame]),
            "mid": float(mid_flux[frame]),
            "high": float(high_flux[frame]),
        }
        dominant = max(bands, key=bands.get)
        events.append(
            MusicalEvent(
                time=float(time),
                type=EventType.BEAT,
                strength=float(strength),
                payload={
                    "beat_index": i,
                    "local_bpm": float(dynamic_bpm[frame]),
                    "tempo_confidence": float(tempo_confidence[frame]),
                    "pulse": float(pulse[frame]),
                    "accent": float(accent),
                    "dominant_band": dominant,
                    **bands,
                },
            )
        )

    for i, time in enumerate(bar_times):
        nearest = int(np.argmin(np.abs(beat_times - time))) if beat_times.size else 0
        frame = beat_frames[min(nearest, len(beat_frames) - 1)] if len(beat_frames) else 0
        events.append(
            MusicalEvent(
                time=float(time),
                type=EventType.BAR,
                strength=float(beat_accents[min(nearest, len(beat_accents) - 1)]) if len(beat_accents) else 1.0,
                payload={
                    "bar_index": i,
                    "local_bpm": float(dynamic_bpm[min(frame, n_frames - 1)]),
                },
            )
        )

    # Persist a sparse tempo curve and emit meaningful tempo-change events.
    curve_step = max(1, int(round(cfg.tempo_curve_seconds * sr / cfg.hop_length)))
    tempo_curve: list[TempoPoint] = []
    previous_event_bpm: float | None = None
    previous_event_time = -1e9
    for frame in range(0, n_frames, curve_step):
        t = float(librosa.frames_to_time(frame, sr=sr, hop_length=cfg.hop_length))
        bpm = float(dynamic_bpm[frame])
        conf = float(tempo_confidence[frame])
        tempo_curve.append(TempoPoint(time=min(t, duration), bpm=bpm, confidence=conf))
        if (
            previous_event_bpm is not None
            and abs(bpm - previous_event_bpm) >= cfg.tempo_change_bpm
            and t - previous_event_time >= max(2.0, cfg.tempo_curve_seconds)
            and conf >= 0.20
        ):
            events.append(
                MusicalEvent(
                    time=min(t, duration),
                    type=EventType.TEMPO_CHANGE,
                    strength=min(1.0, abs(bpm - previous_event_bpm) / 24.0),
                    payload={
                        "from_bpm": previous_event_bpm,
                        "to_bpm": bpm,
                        "confidence": conf,
                    },
                )
            )
            previous_event_time = t
        if previous_event_bpm is None or conf >= 0.20:
            previous_event_bpm = bpm

    energy_threshold = float(np.quantile(rms_norm, cfg.energy_quantile))
    peak_frames = librosa.util.peak_pick(
        rms_norm, pre_max=3, post_max=3, pre_avg=8, post_avg=8, delta=0.05, wait=4
    )
    for frame in peak_frames:
        strength = float(rms_norm[frame])
        if strength >= energy_threshold:
            events.append(
                MusicalEvent(
                    time=float(librosa.frames_to_time(frame, sr=sr, hop_length=cfg.hop_length)),
                    type=EventType.ENERGY,
                    strength=strength,
                    payload={
                        "brightness": float(centroid_norm[frame]),
                        "bass_weight": float(bass_weight[frame]),
                        "percussive_ratio": float(percussive_ratio[frame]),
                    },
                )
            )

    similarity = np.sum(chroma_unit[:, 1:] * chroma_unit[:, :-1], axis=0)
    harmonic_change = _normalise(np.clip(1.0 - similarity, 0.0, 2.0))
    if harmonic_change.size:
        threshold = float(np.quantile(harmonic_change, cfg.harmonic_change_quantile))
        peaks = librosa.util.peak_pick(
            harmonic_change, pre_max=4, post_max=4, pre_avg=12, post_avg=12, delta=0.05, wait=8
        )
        for frame in peaks:
            strength = float(harmonic_change[frame])
            if strength >= threshold:
                events.append(
                    MusicalEvent(
                        time=float(librosa.frames_to_time(frame + 1, sr=sr, hop_length=cfg.hop_length)),
                        type=EventType.HARMONIC_CHANGE,
                        strength=strength,
                        payload={
                            "tonal_stability": float(tonal_stability_frame[min(frame + 1, n_frames - 1)]),
                            "brightness": float(centroid_norm[min(frame + 1, n_frames - 1)]),
                        },
                    )
                )

    sections: list[Section] = []
    previous_energy = 0.0

    # Prefer phrase boundaries expressed in bars. This makes sections stay
    # musically aligned when local BPM changes across a long DJ mix.
    if cfg.section_bars > 0 and len(bar_times) >= 2:
        boundary_times = [0.0]
        boundary_times.extend(float(x) for x in bar_times[cfg.section_bars::cfg.section_bars])
        boundary_times.append(duration)
        boundary_times = sorted(set(max(0.0, min(duration, x)) for x in boundary_times))
        if boundary_times[-1] < duration:
            boundary_times.append(duration)
        section_spans: list[tuple[int, int, float, float]] = []
        for start_t, end_t in zip(boundary_times, boundary_times[1:]):
            if end_t - start_t < 0.25:
                continue
            frame_start = int(librosa.time_to_frames(start_t, sr=sr, hop_length=cfg.hop_length))
            frame_end = int(librosa.time_to_frames(end_t, sr=sr, hop_length=cfg.hop_length))
            frame_start = max(0, min(n_frames - 1, frame_start))
            frame_end = max(frame_start + 1, min(n_frames, frame_end))
            section_spans.append((frame_start, frame_end, start_t, end_t))
    else:
        frames_per_section = max(1, int(round(cfg.section_seconds * sr / cfg.hop_length)))
        section_spans = []
        for frame_start in range(0, n_frames, frames_per_section):
            frame_end = min(frame_start + frames_per_section, n_frames)
            start_t = float(librosa.frames_to_time(frame_start, sr=sr, hop_length=cfg.hop_length))
            end_t = min(duration, float(librosa.frames_to_time(frame_end, sr=sr, hop_length=cfg.hop_length)))
            if end_t > start_t:
                section_spans.append((frame_start, frame_end, start_t, end_t))

    for index, (frame_start, frame_end, start, end) in enumerate(section_spans):

        sl = slice(frame_start, frame_end)
        section_energy = float(np.mean(rms_norm[sl]))
        section_brightness = float(np.mean(centroid_norm[sl]))
        section_key = _frame_key(chroma, sl)
        local_tempo = float(np.median(dynamic_bpm[sl]))
        local_confidence = float(np.mean(tempo_confidence[sl]))
        local_pulse = float(np.mean(pulse[sl]))
        local_bass = float(np.mean(bass_weight[sl]))
        local_percussive = float(np.mean(percussive_ratio[sl]))
        local_tonal = float(np.mean(tonal_stability_frame[sl]))
        local_noise = float(np.mean(flatness[sl]))
        local_contrast = float(np.mean(contrast[sl]))

        chroma_profile = np.mean(chroma[:, sl], axis=1)
        chroma_total = float(np.sum(chroma_profile))
        chroma_profile = chroma_profile / chroma_total if chroma_total > 1e-12 else np.zeros(12)

        section_onsets = onset_norm[sl]
        onset_density = float(np.mean(section_onsets > 0.42)) if section_onsets.size else 0.0

        delta = section_energy - previous_energy if sections else 0.0
        if section_energy < 0.23:
            label = "ambient"
        elif sections and delta <= -0.20:
            label = "breakdown"
        elif delta >= 0.12 and section_energy < 0.76:
            label = "build"
        elif section_energy >= 0.72:
            label = "peak"
        else:
            label = "drive"

        vibe = _vibe(
            energy=section_energy,
            brightness=section_brightness,
            onset_density=onset_density,
            bass_weight=local_bass,
            percussive_ratio=local_percussive,
            tonal_stability=local_tonal,
            noisiness=local_noise,
            tempo=local_tempo,
        )

        fingerprint = np.concatenate([
            chroma_profile * 3.0,
            np.array([
                section_energy,
                section_brightness,
                onset_density,
                local_bass,
                local_percussive,
                local_tonal,
            ]),
        ])

        section = Section(
            index=index,
            start=start,
            end=end,
            energy=section_energy,
            label=label,
            key=section_key,
            brightness=section_brightness,
            onset_density=onset_density,
            local_tempo_bpm=local_tempo,
            tempo_confidence=local_confidence,
            pulse_strength=local_pulse,
            bass_weight=local_bass,
            percussive_ratio=local_percussive,
            tonal_stability=local_tonal,
            noisiness=local_noise,
            spectral_contrast=local_contrast,
            vibe=vibe,
            chroma_profile=[float(v) for v in chroma_profile],
            fingerprint=[float(v) for v in fingerprint],
        )
        sections.append(section)
        previous_energy = section_energy

        events.append(
            MusicalEvent(
                time=start,
                type=EventType.SECTION,
                strength=section_energy,
                payload={
                    "section_index": index,
                    "label": label,
                    "vibe": vibe,
                    "end": end,
                    "key": section_key,
                    "local_bpm": local_tempo,
                    "tempo_confidence": local_confidence,
                    "bass_weight": local_bass,
                    "percussive_ratio": local_percussive,
                    "tonal_stability": local_tonal,
                    "brightness": section_brightness,
                },
            )
        )

    # Drop detection combines energy, bass and percussive arrival rather than
    # energy alone. This is much better for techno/EDM drops after breakdowns.
    for previous, current in zip(sections, sections[1:]):
        energy_delta = current.energy - previous.energy
        bass_delta = current.bass_weight - previous.bass_weight
        perc_delta = current.percussive_ratio - previous.percussive_ratio
        score = 0.62 * max(0.0, energy_delta) + 0.23 * max(0.0, bass_delta) + 0.15 * max(0.0, perc_delta)
        if score >= 0.16 and current.energy >= 0.52:
            nearest_bar = min(bar_times, key=lambda value: abs(float(value) - current.start), default=current.start)
            events.append(
                MusicalEvent(
                    time=float(nearest_bar),
                    type=EventType.DROP_CANDIDATE,
                    strength=min(1.0, score * 2.6 + current.energy * 0.25),
                    payload={
                        "from_section": previous.index,
                        "to_section": current.index,
                        "energy_delta": energy_delta,
                        "bass_delta": bass_delta,
                        "percussive_delta": perc_delta,
                        "vibe": current.vibe,
                    },
                )
            )

    events.sort(key=lambda event: (event.time, event.type.value))

    # A robust summary tempo is retained for display/backward compatibility.
    confident = dynamic_bpm[tempo_confidence >= 0.20]
    tempo = float(np.median(confident if confident.size else dynamic_bpm))

    return TrackAnalysis(
        source=source,
        duration=duration,
        sample_rate=sr,
        hop_length=cfg.hop_length,
        tempo_bpm=tempo,
        tempo_curve=tempo_curve,
        key=key,
        beats=[float(x) for x in beat_times],
        bars=[float(x) for x in bar_times],
        sections=sections,
        events=events,
    )
