# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.ai_edit_consultant import AIEditConsultantConfig, consult_section, preference_bonus
from tubeviz.ai_music_director import _director_prompt
from tubeviz.ai_resources import build_resource_manifest
from tubeviz.library import ClipLibrary, sha256_file
from tubeviz.models import DirectedTimeline, Section, TrackAnalysis
from tubeviz.scene_selector import SceneSelectorConfig, build_scene_plan


def _ready(library: ClipLibrary, source_id: str, term: str, title: str) -> int:
    clip_id = library.upsert_discovery(
        source="youtube", source_id=source_id,
        source_url=f"https://youtube.invalid/{source_id}", term=term, rank=1,
        metadata={"title": title, "duration": 10.0},
    )
    path = library.normalized_dir / f"{source_id}.mp4"
    path.write_bytes(source_id.encode() * 16)
    library.mark_normalized(clip_id, path, sha256_file(path))
    library.replace_scenes(clip_id, [(0.0, 10.0, None)])
    return clip_id


def _track() -> TrackAnalysis:
    return TrackAnalysis(
        source="song.wav", duration=8.0, sample_rate=22050, hop_length=512,
        tempo_bpm=120.0, beats=[], bars=[], events=[],
        sections=[Section(index=0, start=0.0, end=8.0, energy=.72, label="peak", vibe="euphoric")],
    )


def test_resource_manifest_describes_actual_output_pool_and_effect_inventory(tmp_path: Path):
    lib = ClipLibrary(tmp_path / "library")
    lib.initialize()
    _ready(lib, "forest", "surreal nature", "Forest world")
    _ready(lib, "dance", "dance performance", "Dance stage")
    cfg = SceneSelectorConfig(vector_effects=True, creative_effects=True, codec_glitch_mode="musical")
    manifest = build_resource_manifest(lib, cfg)
    assert manifest["library"]["eligible_clips"] == 2
    assert manifest["library"]["eligible_scenes"] == 2
    assert manifest["renderer"]["raster_creative"]
    assert "flow ribbons" in manifest["renderer"]["vector"]
    assert manifest["renderer"]["codec"]["enabled"] is True
    assert "flow melt" in manifest["renderer"]["hero"]


def test_whole_song_prompt_receives_resource_manifest():
    prompt = _director_prompt(_track(), {"library": {"eligible_clips": 17}, "renderer": {"hero": ["flow melt"]}})
    assert "ACTUAL library" in prompt
    assert '"eligible_clips": 17' in prompt
    assert "flow melt" in prompt
    assert "later bounded edit-consultant pass" in prompt


def test_consultant_rejects_invented_ids_and_unknown_effects(monkeypatch, tmp_path: Path):
    lib = ClipLibrary(tmp_path / "library")
    lib.initialize()
    _ready(lib, "a", "nature", "A")
    _ready(lib, "b", "dance", "B")
    candidates = lib.scene_candidates()
    valid = candidates[1].scene_id

    monkeypatch.setattr("tubeviz.ai_edit_consultant._call", lambda prompt, cfg: {
        "shots": [{
            "shot_index": 0,
            "preferred_scene_ids": [999999, valid],
            "effect_family": "hyper",
            "hero_kind": "flow melt",
            "reason": "use motion contrast",
        }]
    })
    advice = consult_section(
        _track().sections[0], windows=[(0.0, 8.0)],
        candidates=[(candidates[0], 1.0), (candidates[1], .9)], previous=None,
        config=AIEditConsultantConfig(
            enabled=True, base_url="http://localhost:8000/v1", model="local",
            cache_dir=str(tmp_path / "cache"), force=True,
        ), progress=lambda _: None,
    )
    assert advice[0]["preferred_scene_ids"] == [valid]
    assert advice[0]["effect_family"] == "hyper"
    assert advice[0]["hero_kind"] == "flow melt"
    assert preference_bonus(valid, advice[0], .85) > 0
    assert preference_bonus(999999, advice[0], .85) == 0


def test_scene_planner_consultant_can_choose_across_terms_without_openclip(monkeypatch, tmp_path: Path):
    lib = ClipLibrary(tmp_path / "library")
    lib.initialize()
    _ready(lib, "a", "nature", "A")
    _ready(lib, "b", "dance", "B")
    candidates = lib.scene_candidates()
    target = next(c for c in candidates if c.source_id == "b")

    def fake_consult(section, *, windows, candidates, previous, config, progress):
        assert {c.source_id for c, _ in candidates} == {"a", "b"}
        return {0: {"preferred_scene_ids": [target.scene_id], "effect_family": "cinematic", "hero_kind": None, "reason": "payoff"}}

    monkeypatch.setattr("tubeviz.scene_selector.consult_section", fake_consult)
    timeline = DirectedTimeline(track=_track(), cues=[])
    plan = build_scene_plan(
        timeline, lib,
        SceneSelectorConfig(
            semantic=False, dynamic_shots=False, sequence_lookahead=1,
            max_video_layers=1, novelty_weight=0.0,
            ai_consultant_enabled=True, ai_consultant_base_url="http://local/v1",
            ai_consultant_model="model", ai_consultant_weight=10.0,
        ), progress=lambda _: None,
    )
    assert len(plan) == 1
    assert plan[0].scene_id == target.scene_id
    assert plan[0].ai_consultant["selected_was_preferred"] is True
