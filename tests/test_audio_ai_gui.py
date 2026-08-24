# SPDX-License-Identifier: Apache-2.0
from tubeviz.gui import JobRequest, _job_command


def test_gui_analyze_job_includes_audio_ai_and_llm_director():
    command = _job_command(JobRequest(
        kind="analyze",
        library="./library",
        audio="song.mp3",
        output="song.json",
        options={
            "semantic": True,
            "audio_ai": True,
            "audio_ai_device": "cuda",
            "audio_ai_window": 6,
            "audio_ai_hop": 3,
            "audio_visual_match_weight": 1.3,
            "ai_director": True,
            "ai_director_base_url": "http://localhost:8000/v1",
            "ai_director_model": "local-model",
            "ai_director_api_key": "secret",
            "ai_director_strength": .7,
        },
    ))
    joined = " ".join(command)
    assert "--audio-ai" in command
    assert "--audio-ai-device cuda" in joined
    assert "--audio-ai-window 6" in joined
    assert "--audio-ai-hop 3" in joined
    assert "--audio-visual-match-weight 1.3" in joined
    assert "--ai-director" in command
    assert "--ai-director-base-url http://localhost:8000/v1" in joined
    assert "--ai-director-model local-model" in joined
    assert "--ai-director-api-key secret" in joined


def test_gui_audio_ai_doctor_job():
    command = _job_command(JobRequest(
        kind="audio-ai-doctor",
        options={"device": "cpu", "model": "laion/clap-htsat-fused"},
    ))
    joined = " ".join(command)
    assert "audio-ai doctor" in joined
    assert "--device cpu" in joined
