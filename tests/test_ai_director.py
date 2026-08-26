# SPDX-License-Identifier: Apache-2.0
from tubeviz.ai_music_director import AIDirectorConfig, _blend, semantic_direction
from tubeviz.audio_ai import CONCEPT_KEYS
from tubeviz.cli import build_parser
from tubeviz.models import Section, SectionAIDirection


def section():
    scores = {key: 0.0 for key in CONCEPT_KEYS}
    scores.update({"industrial": .35, "dark": .25, "mechanical": .2, "pulsing": .2})
    return Section(
        index=0,start=0,end=8,energy=.7,label="drive",brightness=.4,
        onset_density=.5,local_tempo_bpm=124,bass_weight=.55,
        percussive_ratio=.65,tonal_stability=.5,noisiness=.3,
        spectral_contrast=.5,vibe="driving",audio_semantics=scores,
        audio_semantic_confidence=.75,
    )


def test_llm_direction_blend_keeps_values_bounded_and_textual_plan():
    base = semantic_direction(section())
    proposed = SectionAIDirection(
        visual_world="industrial cathedral", motion_style="forward mechanical",
        palette="steel blue", effect_family="analog", desired_motion=.9,
        desired_complexity=.8, edit_density=.75, continuity=.35,
        target_hue=205, vector_intensity=1.1, codec_intensity=.6,
    )
    merged = _blend(base, proposed, .5)
    assert merged.visual_world == "industrial cathedral"
    assert base.desired_motion <= merged.desired_motion <= .9 or .9 <= merged.desired_motion <= base.desired_motion
    assert merged.effect_family == "analog"


def test_audio_ai_cli_options_parse():
    args = build_parser().parse_args([
        "analyze", "song.mp3", "--audio-ai", "--audio-ai-device", "cuda",
        "--audio-ai-window", "6", "--audio-ai-hop", "3",
        "--audio-visual-match-weight", "1.4", "--ai-director",
        "--ai-director-base-url", "http://localhost:8000/v1",
        "--ai-director-model", "local-model",
    ])
    assert args.audio_ai is True
    assert args.audio_ai_device == "cuda"
    assert args.audio_ai_window == 6
    assert args.audio_ai_hop == 3
    assert args.audio_visual_match_weight == 1.4
    assert args.ai_director is True


def test_audio_ai_subcommands_parse():
    parser = build_parser()
    doctor = parser.parse_args(["audio-ai", "doctor", "--device", "cpu"])
    assert doctor.device == "cpu"
    inspect = parser.parse_args(["audio-ai", "inspect", "timeline.json", "--top", "3"])
    assert inspect.timeline == "timeline.json"
    assert inspect.top == 3


def _track():
    from tubeviz.models import TrackAnalysis

    return TrackAnalysis(
        source="song.wav",
        duration=8,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=124,
        beats=[],
        bars=[],
        sections=[section()],
        events=[],
    )


def test_native_openai_payload_uses_gpt56_reasoning_profile():
    from tubeviz.ai_music_director import _request_payload

    payload = _request_payload(
        _track(),
        AIDirectorConfig(
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-5.6-terra",
        ),
    )
    assert payload["model"] == "gpt-5.6-terra"
    assert payload["reasoning_effort"] == "none"
    assert payload["max_completion_tokens"] == 8192
    assert payload["response_format"] == {"type": "json_object"}
    assert "temperature" not in payload
    assert "max_tokens" not in payload


def test_generic_openai_compatible_payload_preserves_legacy_shape():
    from tubeviz.ai_music_director import _request_payload

    payload = _request_payload(
        _track(),
        AIDirectorConfig(
            enabled=True,
            base_url="http://localhost:8000/v1",
            model="local-model",
        ),
    )
    assert payload["temperature"] == 0.35
    assert "reasoning_effort" not in payload
    assert "max_completion_tokens" not in payload
    assert "response_format" not in payload


def test_native_openai_completion_budget_has_safe_floor():
    from tubeviz.ai_music_director import _request_payload

    payload = _request_payload(
        _track(),
        AIDirectorConfig(
            enabled=True,
            base_url="https://api.openai.com/v1/chat/completions",
            model="gpt-5.6-terra",
            max_completion_tokens=1,
        ),
    )
    assert payload["max_completion_tokens"] == 512


def test_ai_director_cli_openai_defaults_parse():
    args = build_parser().parse_args([
        "analyze", "song.mp3", "--audio-ai", "--ai-director",
        "--ai-director-base-url", "https://api.openai.com/v1",
        "--ai-director-model", "gpt-5.6-terra",
    ])
    assert args.ai_director_reasoning_effort == "none"
    assert args.ai_director_max_completion_tokens == 8192
    assert args.ai_edit_consultant is True
    assert args.ai_consultant_candidates == 12
    assert args.ai_consultant_weight == 0.85
    assert args.ai_consultant_max_completion_tokens == 4096
