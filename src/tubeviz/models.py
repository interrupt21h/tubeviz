# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    BEAT = "beat"
    BAR = "bar"
    ONSET = "onset"
    ENERGY = "energy"
    HARMONIC_CHANGE = "harmonic_change"
    TEMPO_CHANGE = "tempo_change"
    SECTION = "section"
    DROP_CANDIDATE = "drop_candidate"


class MusicalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: float = Field(ge=0)
    type: EventType
    strength: float = Field(default=1.0, ge=0.0)
    payload: dict[str, Any] = Field(default_factory=dict)


class TempoPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: float = Field(ge=0)
    bpm: float = Field(gt=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SectionAIDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_world: str = ""
    motion_style: str = ""
    palette: str = ""
    effect_family: str | None = None
    desired_motion: float = Field(default=0.5, ge=0.0, le=1.0)
    desired_complexity: float = Field(default=0.5, ge=0.0, le=1.0)
    edit_density: float = Field(default=0.5, ge=0.0, le=1.0)
    continuity: float = Field(default=0.5, ge=0.0, le=1.0)
    target_hue: float | None = Field(default=None, ge=0.0, lt=360.0)
    vector_intensity: float = Field(default=1.0, ge=0.0, le=2.0)
    codec_intensity: float = Field(default=1.0, ge=0.0, le=2.0)
    notes: str = ""


class SectionTrajectory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tension: float = Field(default=0.0, ge=0.0, le=1.0)
    tension_slope: float = Field(default=0.0, ge=-1.0, le=1.0)
    build_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    drop_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    release_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    time_to_peak: float | None = Field(default=None, ge=0.0)
    phase: str = "space"
    anticipation: float = Field(default=0.0, ge=0.0, le=1.0)
    withholding: float = Field(default=0.0, ge=0.0, le=1.0)
    target_motion: float = Field(default=0.5, ge=0.0, le=1.0)
    target_complexity: float = Field(default=0.5, ge=0.0, le=1.0)
    target_contrast: float = Field(default=0.35, ge=0.0, le=1.0)
    target_edit_density: float = Field(default=0.5, ge=0.0, le=1.0)


class VisualArcPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_index: int = Field(ge=0)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    phase: str
    intensity: float = Field(default=0.0, ge=0.0, le=1.0)
    build: float = Field(default=0.0, ge=0.0, le=1.0)
    payoff: float = Field(default=0.0, ge=0.0, le=1.0)
    continuity: float = Field(default=0.5, ge=0.0, le=1.0)
    visual_world: str = ""


class AudioSemanticWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    scores: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    entropy: float = Field(default=1.0, ge=0.0, le=1.0)


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    energy: float = Field(ge=0.0)
    label: str
    key: str | None = None
    brightness: float = Field(default=0.0, ge=0.0, le=1.0)
    onset_density: float = Field(default=0.0, ge=0.0)
    local_tempo_bpm: float = Field(default=120.0, gt=0)
    tempo_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pulse_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    bass_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    percussive_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    tonal_stability: float = Field(default=0.0, ge=0.0, le=1.0)
    noisiness: float = Field(default=0.0, ge=0.0, le=1.0)
    spectral_contrast: float = Field(default=0.0, ge=0.0, le=1.0)
    vibe: str = "neutral"
    chroma_profile: list[float] = Field(default_factory=list)
    fingerprint: list[float] = Field(default_factory=list)
    audio_semantics: dict[str, float] = Field(default_factory=dict)
    audio_semantic_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    audio_semantic_entropy: float = Field(default=1.0, ge=0.0, le=1.0)
    ai_direction: SectionAIDirection | None = None
    trajectory: SectionTrajectory | None = None
    music_embedding_novelty: float = Field(default=0.0, ge=0.0, le=1.0)
    music_embedding_velocity: float = Field(default=0.0, ge=0.0, le=1.0)


class TrackAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    duration: float = Field(gt=0)
    sample_rate: int = Field(gt=0)
    hop_length: int = Field(gt=0)
    tempo_bpm: float = Field(gt=0)
    tempo_curve: list[TempoPoint] = Field(default_factory=list)
    key: str | None = None
    beats: list[float]
    bars: list[float]
    sections: list[Section]
    events: list[MusicalEvent]
    audio_ai_model: str | None = None
    audio_ai_concepts: list[str] = Field(default_factory=list)
    audio_ai_windows: list[AudioSemanticWindow] = Field(default_factory=list)
    visual_arc: list[VisualArcPoint] = Field(default_factory=list)
    music_ai_model: str | None = None
    music_ai_device: str | None = None
    music_ai_warning: str | None = None


class MotifOccurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_index: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    similarity: float = Field(ge=-1.0, le=1.0)
    ordinal: int = Field(ge=1)


class MusicalMotif(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    prototype_section: int = Field(ge=0)
    fingerprint: list[float]
    occurrences: list[MotifOccurrence]


class VisualMemoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    motif_id: str
    introduced_at: float = Field(ge=0)
    shape: str
    hue: float = Field(ge=0.0, lt=360.0)
    scale: float = Field(gt=0.0)
    mutation: int = Field(default=0, ge=0)


class WorldSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: float = Field(ge=0)
    world_id: int = Field(ge=1)
    section_index: int = Field(ge=0)
    section_label: str
    energy: float = Field(ge=0.0)
    active_motif_ids: list[str] = Field(default_factory=list)
    memory_depth: int = Field(default=0, ge=0)


class VisualCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: float = Field(ge=0)
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class SceneIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_index: int = Field(ge=0)
    query: str
    concepts: list[str] = Field(default_factory=list)
    section_label: str
    vibe: str = "neutral"
    key: str | None = None
    energy: float = Field(ge=0.0)
    local_tempo_bpm: float = Field(default=120.0, gt=0)
    bass_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    percussive_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    motif_id: str | None = None


class VideoTransform(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playback_rate: float = Field(default=1.0, ge=0.25, le=4.0)
    reverse: bool = False
    mirror: bool = False
    zoom: float = Field(default=1.0, ge=1.0, le=2.5)
    pan_x: float = Field(default=0.0, ge=-1.0, le=1.0)
    pan_y: float = Field(default=0.0, ge=-1.0, le=1.0)
    rotation_degrees: float = Field(default=0.0, ge=-12.0, le=12.0)
    brightness: float = Field(default=1.0, ge=0.25, le=2.0)
    contrast: float = Field(default=1.0, ge=0.25, le=2.5)
    saturation: float = Field(default=1.0, ge=0.0, le=3.0)
    hue_degrees: float = Field(default=0.0, ge=-180.0, le=180.0)
    blur_px: float = Field(default=0.0, ge=0.0, le=20.0)
    grayscale: float = Field(default=0.0, ge=0.0, le=1.0)
    feedback: float = Field(default=0.0, ge=0.0, le=1.0)
    glitch: float = Field(default=0.0, ge=0.0, le=1.0)
    noise: float = Field(default=0.0, ge=0.0, le=1.0)
    pixelate: float = Field(default=0.0, ge=0.0, le=1.0)
    rgb_split: float = Field(default=0.0, ge=0.0, le=1.0)
    scanlines: float = Field(default=0.0, ge=0.0, le=1.0)
    vignette: float = Field(default=0.0, ge=0.0, le=1.0)
    ripple: float = Field(default=0.0, ge=0.0, le=1.0)
    kaleidoscope: float = Field(default=0.0, ge=0.0, le=1.0)
    tiles: float = Field(default=0.0, ge=0.0, le=1.0)
    tunnel: float = Field(default=0.0, ge=0.0, le=1.0)
    posterize: float = Field(default=0.0, ge=0.0, le=1.0)
    edge: float = Field(default=0.0, ge=0.0, le=1.0)
    strobe: float = Field(default=0.0, ge=0.0, le=1.0)
    shutter: float = Field(default=0.0, ge=0.0, le=1.0)
    # Temporal / recursive rendered-video effects.
    slit_scan: float = Field(default=0.0, ge=0.0, le=1.0)
    frame_echo: float = Field(default=0.0, ge=0.0, le=1.0)
    mirror_corridor: float = Field(default=0.0, ge=0.0, le=1.0)
    mask_wipe: float = Field(default=0.0, ge=0.0, le=1.0)
    solarize: float = Field(default=0.0, ge=0.0, le=1.0)
    # v0.12 spatial/temporal video synthesis.
    datamosh: float = Field(default=0.0, ge=0.0, le=1.0)
    block_displace: float = Field(default=0.0, ge=0.0, le=1.0)
    chroma_delay: float = Field(default=0.0, ge=0.0, le=1.0)
    vhs_tracking: float = Field(default=0.0, ge=0.0, le=1.0)
    vortex: float = Field(default=0.0, ge=0.0, le=1.0)
    motion_trails: float = Field(default=0.0, ge=0.0, le=1.0)
    slice_recursion: float = Field(default=0.0, ge=0.0, le=1.0)
    effect_style: str = "cinematic"
    blend_mode: str = "normal"
    materialized: bool = False
    transform_id: str | None = None


class CompositeLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = "companion"
    clip_id: int = Field(gt=0)
    scene_id: int = Field(gt=0)
    scene_index: int = Field(ge=0)
    source_id: str
    title: str | None = None
    media_file: str
    media_url: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    duration: float = Field(gt=0)
    opacity: float = Field(default=0.65, ge=0, le=1)
    blend_mode: str = "screen"
    transform: VideoTransform = Field(default_factory=VideoTransform)

class ColorDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_hue: float = Field(default=0.0, ge=0.0, lt=360.0)
    target_hue: float = Field(default=0.0, ge=0.0, lt=360.0)
    hue_shift_degrees: float = Field(default=0.0, ge=-180.0, le=180.0)
    saturation_scale: float = Field(default=1.0, ge=0.0, le=3.0)
    contrast_scale: float = Field(default=1.0, ge=0.25, le=3.0)
    brightness_scale: float = Field(default=1.0, ge=0.25, le=2.0)
    chromatic_aberration: float = Field(default=0.0, ge=0.0, le=1.0)
    warmth: float = Field(default=0.5, ge=0.0, le=1.0)
    palette: list[str] = Field(default_factory=list)


class VectorEffect(BaseModel):
    """First-class vector scene-graph primitive scheduled by the Visual Director."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    amount: float = Field(default=0.0, ge=0.0, le=1.0)
    opacity: float = Field(default=0.5, ge=0.0, le=1.0)
    blend_mode: str = "screen"
    seed: int = 0
    count: int = Field(default=24, ge=1, le=512)
    line_width: float = Field(default=1.5, ge=0.1, le=32.0)
    color_role: str = "target"
    source: str = "video"
    visible: bool = True
    displace: bool = False
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    automation: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)


class CodecEffect(BaseModel):
    """Codec-space motion-vector effect scheduled by the Visual Director."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    amount: float = Field(default=0.0, ge=0.0, le=1.5)
    start: float = Field(default=0.0, ge=0.0, le=1.0)
    end: float = Field(default=1.0, ge=0.0, le=1.0)
    attack: float = Field(default=0.12, ge=0.0, le=1.0)
    release: float = Field(default=0.18, ge=0.0, le=1.0)
    pulse: float = Field(default=0.0, ge=0.0, le=32.0)
    angle: float = 0.0
    limit: int = Field(default=96, ge=4, le=512)
    seed: int = 0
    materialized: bool = False


class CodecMaterialization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materialized: bool = False
    cache_key: str | None = None
    original_media_file: str | None = None
    original_media_url: str | None = None
    original_start: float | None = None
    original_end: float | None = None
    media_file: str | None = None
    media_url: str | None = None
    ffedit_version: str | None = None


class VisualDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rhythm_alignment: float = Field(default=0.0, ge=0.0, le=1.0)
    transition_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    source_playback_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    motion_match: float = Field(default=0.0, ge=0.0, le=1.0)
    motion: float = Field(default=0.0, ge=0.0, le=1.0)
    complexity: float = Field(default=0.0, ge=0.0, le=1.0)
    visual_entropy: float = Field(default=0.0, ge=0.0, le=1.0)
    effect_family: str = "cinematic"
    narrative_role: str = "develop"
    color: ColorDirection = Field(default_factory=ColorDirection)
    # Curve values are normalized to shot progress 0..1.
    automation: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)
    vector_effects: list[VectorEffect] = Field(default_factory=list)
    codec_effects: list[CodecEffect] = Field(default_factory=list)


class SceneSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_index: int = Field(ge=0)
    time: float = Field(ge=0)
    term: str
    motif_id: str | None = None
    occurrence: int = Field(default=1, ge=1)
    clip_id: int = Field(gt=0)
    scene_id: int = Field(gt=0)
    scene_index: int = Field(ge=0)
    source_id: str
    title: str | None = None
    media_file: str
    media_url: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    duration: float = Field(gt=0)
    crossfade_seconds: float = Field(default=1.25, ge=0)
    opacity: float = Field(default=0.92, ge=0, le=1)
    intent_query: str | None = None
    semantic_score: float = 0.0
    direction: VisualDirection = Field(default_factory=VisualDirection)
    transform: VideoTransform = Field(default_factory=VideoTransform)
    composition_mode: str = "single"
    layers: list[CompositeLayer] = Field(default_factory=list)
    codec_materialization: CodecMaterialization = Field(default_factory=CodecMaterialization)


class DirectedTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track: TrackAnalysis
    cues: list[VisualCue]
    motifs: list[MusicalMotif] = Field(default_factory=list)
    visual_memory: list[VisualMemoryItem] = Field(default_factory=list)
    world_states: list[WorldSnapshot] = Field(default_factory=list)
    scene_plan: list[SceneSelection] = Field(default_factory=list)
    scene_intents: list[SceneIntent] = Field(default_factory=list)
