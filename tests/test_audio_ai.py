# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import numpy as np

from tubeviz.audio_ai import (
    CONCEPT_KEYS,
    _entropy_confidence,
    scene_audio_concept_alignment,
)
from tubeviz.ai_music_director import attach_semantic_directions, semantic_direction
from tubeviz.library import SceneCandidate
from tubeviz.models import Section, TrackAnalysis


def section(**updates):
    data = dict(
        index=0, start=0.0, end=8.0, energy=.72, label="build",
        brightness=.55, onset_density=.48, local_tempo_bpm=126,
        bass_weight=.5, percussive_ratio=.62, tonal_stability=.48,
        noisiness=.35, spectral_contrast=.5, vibe="driving",
    )
    data.update(updates)
    return Section(**data)


def candidate():
    return SceneCandidate(
        scene_id=1, clip_id=1, scene_index=0,
        start_time=0, end_time=6, duration=6,
        thumbnail_path=None, source_id="x", title="neon underground rave crowd",
        description="kinetic nightclub lasers", channel=None,
        normalized_path="normalized/x.mp4", term="rave neon", term_rank=1,
        visual_features={"motion": .8, "complexity": .7},
    )


def test_entropy_confidence_rewards_peaked_distribution():
    peaked = np.zeros(8); peaked[0] = .92; peaked[1:] = .08/7
    flat = np.ones(8)/8
    ep, cp = _entropy_confidence(peaked)
    ef, cf = _entropy_confidence(flat)
    assert ep < ef
    assert cp > cf


def test_common_concept_alignment_is_high_for_matching_openclip_profile():
    scores = {key: 0.0 for key in CONCEPT_KEYS}
    scores["rave"] = .5
    scores["neon"] = .3
    scores["kinetic"] = .2
    sec = section(audio_semantics=scores, audio_semantic_confidence=.8)
    # Identity text basis means scene embedding dimension maps directly to
    # concepts; construct it toward the same three concepts.
    basis = np.eye(len(CONCEPT_KEYS), dtype=np.float32)
    scene = np.zeros(len(CONCEPT_KEYS), dtype=np.float32)
    for key, value in scores.items():
        scene[CONCEPT_KEYS.index(key)] = value
    scene /= np.linalg.norm(scene)
    aligned = scene_audio_concept_alignment(
        sec, scene_embedding=scene, concept_text_embeddings=basis, candidate=candidate()
    )
    assert aligned > .55


def test_semantic_direction_uses_audio_concepts():
    scores = {key: 0.0 for key in CONCEPT_KEYS}
    scores.update({"kinetic": .28, "rave": .24, "neon": .20, "euphoric": .18, "pulsing": .10})
    sec = section(audio_semantics=scores, audio_semantic_confidence=.75)
    direction = semantic_direction(sec)
    assert direction.desired_motion > .6
    assert direction.edit_density > .5
    assert direction.effect_family in {"hyper", "prismatic"}
    assert direction.visual_world


def test_attach_semantic_directions_updates_track():
    scores = {key: 0.0 for key in CONCEPT_KEYS}
    scores["dreamlike"] = .6
    scores["slow_drift"] = .4
    sec = section(audio_semantics=scores, audio_semantic_confidence=.7)
    track = TrackAnalysis(
        source="song.wav", duration=8, sample_rate=22050, hop_length=512,
        tempo_bpm=120, beats=[0,.5], bars=[0], sections=[sec], events=[]
    )
    updated = attach_semantic_directions(track)
    assert updated.sections[0].ai_direction is not None
    assert updated.sections[0].ai_direction.desired_motion < .55
