# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import math
import re
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .torch_device import resolve_torch_device
from .library import ClipLibrary, SceneCandidate

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SemanticConfig:
    model: str = "ViT-B-32"
    pretrained: str = "laion2b_s34b_b79k"
    device: str = "auto"
    batch_size: int = 32


@dataclass(frozen=True)
class EmbeddingIndexSummary:
    total_scenes: int
    indexed: int
    skipped_existing: int
    missing_thumbnails: int


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_TOKEN_RE.findall(text.lower()))


def metadata_semantic_score(candidate: SceneCandidate, query: str) -> float:
    """Cheap semantic fallback using provenance and source metadata.

    Search-term provenance is weighted highest because it is intentional corpus
    labeling supplied by the user. Title and description add weaker evidence.
    """
    q = _tokens(query)
    if not q:
        return 0.0

    def overlap(text: str | None) -> float:
        tokens = _tokens(text)
        if not tokens:
            return 0.0
        return len(q & tokens) / math.sqrt(len(q) * len(tokens))

    return (
        2.5 * overlap(candidate.term)
        + 1.5 * overlap(candidate.title)
        + 0.6 * overlap(candidate.description)
        + 0.2 * overlap(candidate.channel)
    )


class OpenClipEmbedder:
    """Thin optional wrapper around OpenCLIP's documented inference API."""

    def __init__(self, config: SemanticConfig | None = None):
        self.config = config or SemanticConfig()
        try:
            import open_clip
            import torch
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "OpenCLIP semantic features are not installed. Install with: "
                "pip install -e '.[semantic]'"
            ) from exc

        self.open_clip = open_clip
        self.torch = torch
        self.Image = Image
        self.device, self.device_warning = resolve_torch_device(torch, self.config.device)

        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            self.config.model,
            pretrained=self.config.pretrained,
        )
        self.model = self.model.to(self.device)
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(self.config.model)

    def _autocast(self):
        if str(self.device).startswith("cuda"):
            return self.torch.autocast("cuda")
        return nullcontext()

    def encode_images(self, paths: Iterable[Path]) -> np.ndarray:
        images = [
            self.preprocess(self.Image.open(path).convert("RGB"))
            for path in paths
        ]
        if not images:
            return np.empty((0, 0), dtype=np.float32)
        batch = self.torch.stack(images).to(self.device)
        with self.torch.no_grad(), self._autocast():
            features = self.model.encode_image(batch)
            features = features / features.norm(dim=-1, keepdim=True).clamp_min(1e-12)
        return features.float().cpu().numpy().astype(np.float32, copy=False)

    def encode_text(self, texts: Iterable[str]) -> np.ndarray:
        texts = list(texts)
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        tokens = self.tokenizer(texts).to(self.device)
        with self.torch.no_grad(), self._autocast():
            features = self.model.encode_text(tokens)
            features = features / features.norm(dim=-1, keepdim=True).clamp_min(1e-12)
        return features.float().cpu().numpy().astype(np.float32, copy=False)


def index_scene_embeddings(
    library: ClipLibrary,
    *,
    config: SemanticConfig | None = None,
    force: bool = False,
    progress=print,
) -> EmbeddingIndexSummary:
    cfg = config or SemanticConfig()
    library.initialize()
    embedder = OpenClipEmbedder(cfg)
    candidates = library.scene_candidates()
    existing = library.scene_embedding_ids(model=cfg.model, pretrained=cfg.pretrained)

    pending: list[tuple[SceneCandidate, Path]] = []
    skipped = 0
    missing = 0
    for candidate in candidates:
        if candidate.scene_id in existing and not force:
            skipped += 1
            continue
        if not candidate.thumbnail_path:
            missing += 1
            continue
        path = library.root / candidate.thumbnail_path
        if not path.exists():
            missing += 1
            continue
        pending.append((candidate, path))

    indexed = 0
    batch_size = max(1, cfg.batch_size)
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        vectors = embedder.encode_images(path for _, path in batch)
        for (candidate, _), vector in zip(batch, vectors, strict=True):
            library.store_scene_embedding(
                candidate.scene_id,
                model=cfg.model,
                pretrained=cfg.pretrained,
                vector=vector,
            )
            indexed += 1
        progress(f"embedded {indexed}/{len(pending)} scenes")

    return EmbeddingIndexSummary(
        total_scenes=len(candidates),
        indexed=indexed,
        skipped_existing=skipped,
        missing_thumbnails=missing,
    )


def cosine_similarity(vector: np.ndarray, query: np.ndarray) -> float:
    a = np.asarray(vector, dtype=np.float32).reshape(-1)
    b = np.asarray(query, dtype=np.float32).reshape(-1)
    if a.size != b.size or not a.size:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


SCENE_CLASS_PROMPTS: dict[str, str] = {
    "crowd": "a crowd of people",
    "dancing": "people dancing energetically",
    "nightlife": "nightlife in a club or city at night",
    "city": "an urban city scene",
    "tunnel": "a tunnel or corridor with forward perspective",
    "transport": "a train subway bus or moving vehicle",
    "industrial": "industrial machinery factory or mechanical equipment",
    "architecture": "interesting architecture or geometric built environment",
    "nature": "natural landscape plants water mountains or sky",
    "water": "water liquid waves rain or reflections",
    "abstract": "abstract visual art shapes colors or textures",
    "lights": "colorful lights neon lasers or glowing illumination",
    "human_closeup": "a close-up view of a person or face",
    "performance": "a musical performance concert or stage",
    "vehicle_pov": "a moving point of view traveling through an environment",
    "macro": "a macro close-up of texture material or small details",
    "space": "space stars planets or cosmic imagery",
    "fire": "fire sparks flames or pyrotechnics",
    "smoke": "smoke fog haze or atmospheric particles",
    "text_heavy": "a title card subtitles captions or large text overlay",
    "talking_head": "a person speaking directly to a camera",
    "static_presentation": "a static presentation slide logo or informational screen",
}

def classify_scene_thumbnails(
    library: ClipLibrary,
    *,
    clip_id: int,
    embedder: OpenClipEmbedder,
    top_k: int = 5,
    min_score: float = 0.12,
    progress=print,
) -> int:
    """Zero-shot classify scene thumbnails and persist labels with visual features."""
    candidates = [c for c in library.scene_candidates(clip_id=clip_id, respect_trim=False) if c.thumbnail_path]
    pending = []
    for c in candidates:
        path = library.root / c.thumbnail_path
        if path.is_file():
            pending.append((c, path))
    if not pending:
        return 0
    labels = list(SCENE_CLASS_PROMPTS)
    text_vectors = embedder.encode_text(SCENE_CLASS_PROMPTS.values())
    existing = library.load_scene_visual_features([c.scene_id for c, _ in pending])
    count = 0
    batch_size = max(1, embedder.config.batch_size)
    for off in range(0, len(pending), batch_size):
        batch = pending[off:off + batch_size]
        image_vectors = embedder.encode_images(path for _, path in batch)
        scores = image_vectors @ text_vectors.T
        for (candidate, _), row in zip(batch, scores, strict=True):
            order = np.argsort(row)[::-1]
            ranked = [
                {"label": labels[int(i)], "score": round(float(row[int(i)]), 4)}
                for i in order[:max(1, top_k)] if float(row[int(i)]) >= min_score
            ]
            features = dict(existing.get(candidate.scene_id) or {"version": 1})
            features["semantic_labels"] = ranked
            features["semantic_primary"] = ranked[0]["label"] if ranked else None
            features["semantic_model"] = {"model": embedder.config.model, "pretrained": embedder.config.pretrained}
            library.store_scene_visual_features(candidate.scene_id, features)
            count += 1
    if count:
        progress(f"  semantic classification: {count} scenes labeled")
    return count
