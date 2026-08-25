# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import librosa
import numpy as np

from .torch_device import resolve_torch_device
from .models import AudioSemanticWindow, Section, TrackAnalysis


# A shared semantic basis bridges CLAP audio semantics and OpenCLIP scene
# semantics without pretending the two embedding spaces are directly aligned.
CONCEPT_PROMPTS: dict[str, str] = {
    # emotional / narrative state
    "dark": "dark ominous threatening music and imagery",
    "euphoric": "euphoric uplifting ecstatic festival energy",
    "dreamlike": "dreamlike surreal floating ethereal atmosphere",
    "tense": "tense suspenseful anxious rising tension",
    "aggressive": "aggressive violent forceful intense energy",
    "serene": "serene calm peaceful spacious atmosphere",
    "melancholic": "melancholic lonely introspective emotional mood",
    "mysterious": "mysterious uncanny enigmatic atmosphere",
    "hypnotic": "hypnotic repetitive trance-like mesmerizing motion",
    "futuristic": "futuristic technological cybernetic science fiction",
    # motion / temporal character
    "kinetic": "fast kinetic energetic physical motion",
    "slow_drift": "slow drifting graceful minimal motion",
    "pulsing": "pulsing rhythmic repetitive visual motion",
    "explosive": "explosive sudden impact burst destruction",
    "flowing": "fluid flowing continuous organic motion",
    "chaotic": "chaotic erratic fragmented turbulent movement",
    "mechanical": "mechanical repetitive machine motion gears motors",
    "floating": "floating weightless suspended gentle movement",
    "forward_motion": "strong forward travel tunnel vehicle motion",
    "swirling": "swirling vortex spiral rotational movement",
    # worlds / subjects
    "industrial": "industrial factory warehouse machinery infrastructure",
    "urban_night": "urban city at night neon streets architecture",
    "rave": "underground rave club festival lasers crowd dancing",
    "space": "outer space stars planets spacecraft cosmic imagery",
    "nature": "natural landscapes forest mountains organic environment",
    "ocean": "ocean water waves underwater fluid scenery",
    "machinery": "machines motors robotics mechanical equipment closeup",
    "retro_tv": "retro television analog CRT broadcast archival video",
    "surveillance": "surveillance CCTV security camera monitoring imagery",
    "abstract": "abstract experimental generative nonrepresentational visuals",
    "architecture": "architecture buildings interiors geometric structures",
    "crowd": "crowd people dancing gathering collective movement",
    # color / texture
    "neon": "neon luminous saturated colored light",
    "monochrome": "monochrome black and white desaturated imagery",
    "warm_amber": "warm amber orange gold cinematic palette",
    "cold_blue": "cold blue cyan steel cinematic palette",
    "magenta_cyan": "magenta cyan ultraviolet club palette",
    "acid_green": "acid green fluorescent toxic digital palette",
    "metallic": "metallic chrome steel reflective hard surface texture",
    "liquid": "liquid fluid viscous glossy organic texture",
    "grainy_analog": "grainy analog film VHS noisy textured image",
    "clean_digital": "clean crisp modern digital high definition imagery",
    "high_contrast": "high contrast deep shadows bright highlights",
    # cinematography / composition
    "closeup": "extreme closeup macro intimate detail framing",
    "wide": "wide cinematic establishing shot large scale environment",
    "tunnel": "tunnel corridor vanishing point forward perspective",
    "aerial": "aerial overhead drone satellite viewpoint",
    "macro": "macro microscopic detailed texture close photography",
    "handheld": "handheld unstable documentary camera movement",
    "smooth_camera": "smooth stabilized cinematic camera movement",
    "strobing": "strobing flashing rapid light pulses",
    "symmetrical": "symmetrical centered geometric composition",
    "fragmented": "fragmented broken glitch mosaic fractured composition",
}

CONCEPT_KEYS = tuple(CONCEPT_PROMPTS)


@dataclass(frozen=True)
class AudioAIConfig:
    model: str = "laion/clap-htsat-fused"
    device: str = "auto"
    window_seconds: float = 8.0
    hop_seconds: float = 4.0
    batch_size: int = 8
    sample_rate: int = 48_000
    temperature: float = 0.075
    cache_dir: str | None = None
    force: bool = False


def _normalize_rows(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    if values.ndim == 1:
        values = values[None, :]
    denom = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(denom, 1e-12)


def _softmax(values: np.ndarray, temperature: float) -> np.ndarray:
    x = np.asarray(values, dtype=np.float64) / max(1e-4, temperature)
    x -= np.max(x, axis=-1, keepdims=True)
    e = np.exp(x)
    return e / np.maximum(np.sum(e, axis=-1, keepdims=True), 1e-12)


def _entropy_confidence(probabilities: np.ndarray) -> tuple[float, float]:
    p = np.asarray(probabilities, dtype=np.float64)
    p = p / max(1e-12, float(p.sum()))
    entropy = -float(np.sum(p * np.log(np.maximum(p, 1e-12))))
    max_entropy = math.log(max(2, len(p)))
    normalized = min(1.0, max(0.0, entropy / max_entropy))
    # Confidence combines low entropy with separation of the two strongest
    # concepts so ambiguous music never dominates deterministic choreography.
    ordered = np.sort(p)[::-1]
    margin = float(ordered[0] - ordered[1]) if len(ordered) > 1 else float(ordered[0])
    confidence = min(1.0, max(0.0, .72 * (1.0 - normalized) + .28 * min(1.0, margin * 8.0)))
    return normalized, confidence


def _cache_root(cfg: AudioAIConfig) -> Path:
    if cfg.cache_dir:
        return Path(cfg.cache_dir).expanduser().resolve()
    root = os.environ.get("XDG_CACHE_HOME")
    if root:
        return Path(root).expanduser().resolve() / "tubeviz" / "audio-ai"
    return Path.home() / ".cache" / "tubeviz" / "audio-ai"


def _cache_key(audio: Path, cfg: AudioAIConfig) -> str:
    stat = audio.stat()
    payload = {
        "path": str(audio.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "model": cfg.model,
        "window": cfg.window_seconds,
        "hop": cfg.hop_seconds,
        "sample_rate": cfg.sample_rate,
        "temperature": cfg.temperature,
        "concepts": CONCEPT_PROMPTS,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class ClapSemanticAnalyzer:
    """Current Hugging Face CLAP inference wrapper.

    The implementation follows Transformers' documented ClapModel +
    AutoProcessor APIs: processor(audio=..., sampling_rate=...) followed by
    model.get_audio_features(), and processor(text=...) followed by
    model.get_text_features().
    """

    def __init__(self, config: AudioAIConfig | None = None):
        self.config = config or AudioAIConfig()
        try:
            import torch
            from transformers import AutoProcessor, ClapModel
        except ImportError as exc:
            raise RuntimeError(
                "CLAP audio AI is not installed. Install with: "
                "pip install -e '.[audio-ai]'"
            ) from exc

        self.torch = torch
        self.device, self.device_warning = resolve_torch_device(torch, self.config.device)

        self.processor = AutoProcessor.from_pretrained(self.config.model)
        self.model = ClapModel.from_pretrained(self.config.model).to(self.device)
        self.model.eval()

    def _move(self, inputs):
        return {key: value.to(self.device) if hasattr(value, "to") else value for key, value in inputs.items()}

    @staticmethod
    def _feature_tensor(features, *, modality: str):
        """Return the projected CLAP embedding tensor across Transformers APIs.

        Recent Transformers releases return BaseModelOutputWithPooling from
        ClapModel.get_text_features()/get_audio_features(), with the projected
        embedding stored in pooler_output. Older releases returned a Tensor
        directly. Accept both shapes so tubeviz works across the supported
        Transformers range instead of assuming one return type.
        """
        # Current Transformers API: BaseModelOutputWithPooling. ClapModel
        # replaces pooler_output with the projection-space embedding.
        pooled = getattr(features, "pooler_output", None)
        if pooled is not None:
            return pooled

        # Projection model outputs use explicit modality embedding fields.
        explicit = getattr(features, f"{modality}_embeds", None)
        if explicit is not None:
            return explicit

        # Older Transformers releases returned a tensor directly.
        if hasattr(features, "float") and hasattr(features, "cpu"):
            return features

        # Be tolerant of return_dict=False. Prefer a 2-D tensor, which is the
        # projected batch embedding rather than a sequence hidden-state tensor.
        if isinstance(features, (tuple, list)):
            candidates = [
                value for value in features
                if hasattr(value, "float") and hasattr(value, "cpu")
            ]
            for value in reversed(candidates):
                if getattr(value, "ndim", None) == 2:
                    return value
            if candidates:
                return candidates[-1]

        raise TypeError(
            f"Unsupported CLAP {modality} feature output type: "
            f"{type(features).__module__}.{type(features).__name__}"
        )

    @classmethod
    def _feature_array(cls, features, *, modality: str) -> np.ndarray:
        tensor = cls._feature_tensor(features, modality=modality)
        return _normalize_rows(tensor.float().cpu().numpy())

    def encode_text(self, texts: Iterable[str]) -> np.ndarray:
        texts = list(texts)
        inputs = self.processor(text=texts, return_tensors="pt", padding=True)
        inputs = self._move(inputs)
        # get_text_features only consumes text arguments; processor can return
        # modality-specific entries depending on Transformers version.
        allowed = {k: v for k, v in inputs.items() if k in {"input_ids", "attention_mask", "position_ids"}}
        with self.torch.inference_mode():
            features = self.model.get_text_features(**allowed)
        return self._feature_array(features, modality="text")

    def encode_audio(self, audio_batch: list[np.ndarray]) -> np.ndarray:
        inputs = self.processor(
            audio=audio_batch,
            sampling_rate=self.config.sample_rate,
            return_tensors="pt",
            padding=True,
        )
        inputs = self._move(inputs)
        allowed = {k: v for k, v in inputs.items() if k in {"input_features", "is_longer", "attention_mask"}}
        with self.torch.inference_mode():
            features = self.model.get_audio_features(**allowed)
        return self._feature_array(features, modality="audio")


def _window_audio(y: np.ndarray, sr: int, duration: float, window: float, hop: float) -> list[tuple[float, float, np.ndarray]]:
    if duration <= 0:
        return []
    window = max(.5, float(window))
    hop = max(.25, float(hop))
    starts = list(np.arange(0.0, max(0.001, duration), hop))
    if starts and starts[-1] + window < duration - .25:
        starts.append(max(0.0, duration - window))
    out: list[tuple[float, float, np.ndarray]] = []
    seen: set[int] = set()
    for start in starts:
        sample_start = max(0, int(round(start * sr)))
        if sample_start in seen:
            continue
        seen.add(sample_start)
        end = min(duration, start + window)
        sample_end = min(len(y), int(round(end * sr)))
        segment = np.asarray(y[sample_start:sample_end], dtype=np.float32)
        if segment.size < int(sr * .25):
            continue
        out.append((float(start), float(end), segment))
    return out


def analyze_audio_semantics(
    audio: str | Path,
    *,
    config: AudioAIConfig | None = None,
    progress=print,
) -> tuple[list[AudioSemanticWindow], list[str]]:
    cfg = config or AudioAIConfig()
    path = Path(audio).expanduser().resolve()
    cache_dir = _cache_root(cfg)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{_cache_key(path, cfg)}.json"
    if cache.is_file() and not cfg.force:
        data = json.loads(cache.read_text())
        windows = [AudioSemanticWindow.model_validate(item) for item in data.get("windows", [])]
        if windows:
            progress(f"Audio AI: loaded {len(windows)} cached CLAP windows")
            return windows, list(data.get("concepts", CONCEPT_KEYS))

    analyzer = ClapSemanticAnalyzer(cfg)
    progress(f"Audio AI: loading {path.name} at {cfg.sample_rate} Hz")
    y, sr = librosa.load(path, sr=cfg.sample_rate, mono=True)
    duration = float(len(y) / sr)
    source_windows = _window_audio(y, sr, duration, cfg.window_seconds, cfg.hop_seconds)
    text_features = analyzer.encode_text(CONCEPT_PROMPTS.values())

    results: list[AudioSemanticWindow] = []
    batch_size = max(1, cfg.batch_size)
    for offset in range(0, len(source_windows), batch_size):
        batch = source_windows[offset:offset + batch_size]
        audio_features = analyzer.encode_audio([segment for _, _, segment in batch])
        cosine = audio_features @ text_features.T
        probabilities = _softmax(cosine, cfg.temperature)
        for (start, end, _), probs in zip(batch, probabilities, strict=True):
            entropy, confidence = _entropy_confidence(probs)
            # Keep the complete common concept basis. This is intentionally
            # compact (~50 floats/window) and enables cross-modal scene ranking.
            scores = {key: float(value) for key, value in zip(CONCEPT_KEYS, probs, strict=True)}
            results.append(AudioSemanticWindow(
                start=start,
                end=end,
                scores=scores,
                confidence=confidence,
                entropy=entropy,
            ))
        progress(f"Audio AI: CLAP windows {min(offset + len(batch), len(source_windows))}/{len(source_windows)}")

    payload = {
        "model": cfg.model,
        "concepts": list(CONCEPT_KEYS),
        "windows": [window.model_dump(mode="json") for window in results],
    }
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(cache)
    return results, list(CONCEPT_KEYS)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def attach_audio_semantics(
    track: TrackAnalysis,
    audio: str | Path,
    *,
    config: AudioAIConfig | None = None,
    progress=print,
) -> TrackAnalysis:
    cfg = config or AudioAIConfig()
    windows, concepts = analyze_audio_semantics(audio, config=cfg, progress=progress)
    sections: list[Section] = []
    for section in track.sections:
        weighted = np.zeros(len(CONCEPT_KEYS), dtype=np.float64)
        confidence_weight = 0.0
        entropy_weight = 0.0
        total = 0.0
        for window in windows:
            weight = _overlap(section.start, section.end, window.start, window.end)
            if weight <= 0:
                continue
            weighted += weight * np.asarray([window.scores.get(key, 0.0) for key in CONCEPT_KEYS], dtype=np.float64)
            confidence_weight += weight * window.confidence
            entropy_weight += weight * window.entropy
            total += weight
        if total > 0:
            weighted /= total
            weighted /= max(1e-12, float(weighted.sum()))
            semantics = {key: float(value) for key, value in zip(CONCEPT_KEYS, weighted, strict=True)}
            confidence = float(confidence_weight / total)
            entropy = float(entropy_weight / total)
        else:
            semantics, confidence, entropy = {}, 0.0, 1.0
        sections.append(section.model_copy(update={
            "audio_semantics": semantics,
            "audio_semantic_confidence": confidence,
            "audio_semantic_entropy": entropy,
        }))

    return track.model_copy(update={
        "sections": sections,
        "audio_ai_model": cfg.model,
        "audio_ai_concepts": concepts,
        "audio_ai_windows": windows,
    })


def top_audio_concepts(section: Section, limit: int = 6) -> list[tuple[str, float]]:
    return sorted(section.audio_semantics.items(), key=lambda item: item[1], reverse=True)[:max(0, limit)]


def audio_semantic_vector(section: Section, keys: Iterable[str] = CONCEPT_KEYS) -> np.ndarray:
    values = np.asarray([section.audio_semantics.get(key, 0.0) for key in keys], dtype=np.float32)
    norm = float(np.linalg.norm(values))
    return values / norm if norm > 1e-12 else values


def scene_audio_concept_alignment(
    section: Section,
    *,
    scene_embedding: np.ndarray | None,
    concept_text_embeddings: np.ndarray | None,
    candidate=None,
) -> float:
    """Return 0..1 alignment in a shared concept-score basis.

    CLAP and OpenCLIP do not share an embedding space. We therefore project
    both modalities onto the same curated text concepts and compare those
    probability profiles. This preserves the semantics of each pretrained model
    while avoiding invalid direct embedding cosine similarity.
    """
    if not section.audio_semantics:
        return 0.0
    audio = np.asarray([section.audio_semantics.get(key, 0.0) for key in CONCEPT_KEYS], dtype=np.float64)
    if audio.sum() <= 1e-12:
        return 0.0
    audio /= audio.sum()

    scene_probs: np.ndarray
    if scene_embedding is not None and concept_text_embeddings is not None:
        vector = np.asarray(scene_embedding, dtype=np.float32).reshape(-1)
        texts = np.asarray(concept_text_embeddings, dtype=np.float32)
        if texts.ndim == 2 and texts.shape[1] == vector.size:
            logits = texts @ vector
            scene_probs = _softmax(logits[None, :], .075)[0]
        else:
            scene_probs = np.zeros(len(CONCEPT_KEYS), dtype=np.float64)
    elif candidate is not None:
        # Metadata-only fallback. Import lazily to avoid semantic.py importing us
        # in a cycle.
        from .semantic import metadata_semantic_score
        values = np.asarray([
            metadata_semantic_score(candidate, CONCEPT_PROMPTS[key]) for key in CONCEPT_KEYS
        ], dtype=np.float64)
        scene_probs = _softmax(values[None, :], .35)[0]
    else:
        return 0.0

    if scene_probs.sum() <= 1e-12:
        return 0.0
    scene_probs /= scene_probs.sum()
    # Bhattacharyya affinity is bounded 0..1 and behaves well for sparse
    # probability distributions.
    return float(np.clip(np.sum(np.sqrt(audio * scene_probs)), 0.0, 1.0))


def audio_ai_doctor(model: str = "laion/clap-htsat-fused", device: str = "auto") -> dict[str, object]:
    result: dict[str, object] = {"model": model, "requested_device": device}
    try:
        import torch
        import transformers
        result["torch"] = getattr(torch, "__version__", "unknown")
        result["transformers"] = getattr(transformers, "__version__", "unknown")
        result["cuda_available"] = bool(torch.cuda.is_available())
        result["cuda_devices"] = int(torch.cuda.device_count()) if torch.cuda.is_available() else 0
        resolved, warning = resolve_torch_device(torch, device)
        result["resolved_device"] = resolved
        if warning:
            result["device_warning"] = warning
        if torch.cuda.is_available():
            result["cuda_arch_list"] = list(torch.cuda.get_arch_list())
            try:
                result["cuda_capability"] = list(torch.cuda.get_device_capability(0))
                result["cuda_device_name"] = torch.cuda.get_device_name(0)
            except Exception:
                pass
        result["available"] = True
    except ImportError as exc:
        result["available"] = False
        result["error"] = str(exc)
    return result
