# SPDX-License-Identifier: Apache-2.0
import json

import pytest

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


class _FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _completion(content, *, finish_reason="stop", completion_tokens=256, reasoning_tokens=0):
    return {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }],
        "usage": {
            "completion_tokens": completion_tokens,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


def test_ai_director_retries_length_completion_with_larger_budget(monkeypatch):
    import tubeviz.ai_music_director as director

    responses = iter([
        _completion('{"sections":[{"index":0}', finish_reason="length", completion_tokens=8192),
        _completion('{"sections":[{"index":0,"strategy":"establish"}]}', completion_tokens=320),
    ])
    requests = []

    def fake_urlopen(request, timeout=None):
        requests.append(json.loads(request.data.decode("utf-8")))
        return _FakeHTTPResponse(next(responses))

    monkeypatch.setattr(director.urllib.request, "urlopen", fake_urlopen)
    progress = []
    result = director._call_llm(
        _track(),
        AIDirectorConfig(
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-5.6-terra",
            max_completion_tokens=8192,
        ),
        progress=progress.append,
    )

    assert result == {"sections": [{"index": 0, "strategy": "establish"}]}
    assert [item["max_completion_tokens"] for item in requests] == [8192, 16384]
    assert requests[1]["reasoning_effort"] == "none"
    assert "COMPLETE JSON object" in requests[1]["messages"][0]["content"]
    assert any("retrying with 16384 tokens" in message for message in progress)


def test_ai_director_retries_malformed_json_even_when_finish_reason_is_stop(monkeypatch):
    import tubeviz.ai_music_director as director

    responses = iter([
        _completion('{"sections":[{"index":0,}]}', completion_tokens=700),
        _completion('{"sections":[]}', completion_tokens=32),
    ])
    requests = []

    def fake_urlopen(request, timeout=None):
        requests.append(json.loads(request.data.decode("utf-8")))
        return _FakeHTTPResponse(next(responses))

    monkeypatch.setattr(director.urllib.request, "urlopen", fake_urlopen)
    progress = []
    result = director._call_llm(
        _track(),
        AIDirectorConfig(
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-5.6-terra",
            max_completion_tokens=8192,
        ),
        progress=progress.append,
    )

    assert result == {"sections": []}
    assert [item["max_completion_tokens"] for item in requests] == [8192, 16384]
    assert any("malformed JSON" in message for message in progress)


def test_ai_director_reports_length_after_bounded_retries(monkeypatch):
    import tubeviz.ai_music_director as director

    responses = iter([
        _completion("{", finish_reason="length", completion_tokens=8192),
        _completion("{", finish_reason="length", completion_tokens=16384),
        _completion("{", finish_reason="length", completion_tokens=32768),
    ])
    requests = []

    def fake_urlopen(request, timeout=None):
        requests.append(json.loads(request.data.decode("utf-8")))
        return _FakeHTTPResponse(next(responses))

    monkeypatch.setattr(director.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="exceeded its completion budget") as excinfo:
        director._call_llm(
            _track(),
            AIDirectorConfig(
                enabled=True,
                base_url="https://api.openai.com/v1",
                model="gpt-5.6-terra",
                max_completion_tokens=8192,
            ),
            progress=lambda _message: None,
        )

    assert [item["max_completion_tokens"] for item in requests] == [8192, 16384, 32768]
    assert "request_budget=32768" in str(excinfo.value)
    assert "completion_tokens=32768" in str(excinfo.value)


def test_ai_director_reports_json_location_after_bounded_retries(monkeypatch):
    import tubeviz.ai_music_director as director

    responses = iter([
        _completion('{"sections":[{"index":0,}]}'),
        _completion('{"sections":[{"index":0,}]}'),
        _completion('{"sections":[{"index":0,}]}'),
    ])

    def fake_urlopen(request, timeout=None):
        return _FakeHTTPResponse(next(responses))

    monkeypatch.setattr(director.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="malformed JSON after retries") as excinfo:
        director._call_llm(
            _track(),
            AIDirectorConfig(
                enabled=True,
                base_url="https://api.openai.com/v1",
                model="gpt-5.6-terra",
            ),
            progress=lambda _message: None,
        )

    assert "line 1" in str(excinfo.value)
    assert "column" in str(excinfo.value)
    assert "char" in str(excinfo.value)


def test_ai_director_prompt_requests_sparse_section_patches():
    from tubeviz.ai_music_director import _director_prompt

    prompt = _director_prompt(_track())
    assert "PATCH over its supplied baseline" in prompt
    assert "omit fields you do not intentionally change" in prompt
