# SPDX-License-Identifier: Apache-2.0
from tubeviz.ai_music_director import AIDirectorConfig, _blend, _director_prompt, _sanitize_director_data
from tubeviz.models import AIDirectorBeat, Section, SectionAIDirection, TrackAnalysis
from tubeviz.scene_selector import _director_beat_assignments


def _section(direction=None):
    return Section(
        index=0, start=0, end=8, energy=.72, label="build", local_tempo_bpm=124,
        percussive_ratio=.6, bass_weight=.55, vibe="driving",
        audio_semantic_confidence=.2, ai_direction=direction,
    )


def _track(direction=None):
    return TrackAnalysis(
        source="song.wav", duration=8, sample_rate=22050, hop_length=512,
        tempo_bpm=124, beats=[0, .5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5],
        bars=[], sections=[_section(direction)], events=[],
    )


def test_director_beat_model_is_bounded_and_explicit():
    beat=AIDirectorBeat(at=.75, purpose="payoff", source_query="faces emerge from smoke", composition="single", effect_bias=1.1, hero_kind="time prism")
    assert beat.at == .75
    assert beat.source_query.startswith("faces")
    assert beat.composition == "single"


def test_blend_preserves_explicit_director_moment_even_at_low_numeric_strength():
    base=SectionAIDirection(desired_motion=.2, strategy="establish")
    proposed=SectionAIDirection(desired_motion=.9, strategy="payoff", provenance="llm", director_beats=[AIDirectorBeat(at=.8, purpose="time prism payoff", hero_kind="time prism")])
    merged=_blend(base, proposed, .2)
    assert .2 < merged.desired_motion < .9
    assert merged.strategy == "payoff"
    assert merged.director_beats[0].hero_kind == "time prism"


def test_director_response_sanitizer_rejects_invented_capabilities():
    value=_sanitize_director_data({
        "preferred_composition":"mosaic",
        "preferred_effects":["motion trails", "invented laser"],
        "director_beats":[{
            "at":1.8, "composition":"invented layout", "preferred_effects":["ripple", "invented"],
            "hero_kind":"time_prism", "history_mode":"nonsense", "effect_bias":99,
        }],
    })
    assert value["preferred_composition"] == "mosaic"
    assert value["preferred_effects"] == ["motion trails"]
    beat=value["director_beats"][0]
    assert beat["at"] == 1.0
    assert beat["composition"] is None
    assert beat["preferred_effects"] == ["ripple"]
    assert beat["hero_kind"] == "time prism"
    assert beat["history_mode"] == "auto"
    assert beat["effect_bias"] == 1.75


def test_director_prompt_demands_visible_shot_level_creative_decisions():
    prompt=_director_prompt(_track())
    assert "director_beats" in prompt
    assert "recognizable in the finished edit" in prompt
    assert "not a section-long default" in prompt


def test_director_beats_map_to_nearest_distinct_valid_shots():
    direction=SectionAIDirection(director_beats=[
        AIDirectorBeat(at=.12, purpose="open"),
        AIDirectorBeat(at=.88, purpose="payoff"),
    ])
    windows=[(0,2),(2,4),(4,6),(6,8)]
    assigned=_director_beat_assignments(_section(direction), windows)
    assert assigned[0].purpose == "open"
    assert assigned[3].purpose == "payoff"


def test_director_config_defaults_to_full_numeric_authority_budget():
    assert AIDirectorConfig().semantic_strength == 1.0


def test_preview_exposes_director_provenance():
    index=(__import__('pathlib').Path(__file__).parents[1]/"src/tubeviz/static/index.html").read_text()
    js=(__import__('pathlib').Path(__file__).parents[1]/"src/tubeviz/static/visualizer.js").read_text()
    assert 'id="director-meta"' in index
    assert "AI director active" in js
    assert "beat_applied" in js


def test_effect_name_normalization_accepts_canonical_hyphenated_names():
    from tubeviz.ai_resources import normalize_effect_name
    assert normalize_effect_name("optical-flow warp") == "optical-flow warp"
    assert normalize_effect_name("optical flow warp") == "optical-flow warp"
    assert normalize_effect_name("source-preserving color grade") == "source-preserving color grade"
