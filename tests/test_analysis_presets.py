# SPDX-License-Identifier: Apache-2.0
from fastapi.testclient import TestClient
import pytest

from tubeviz.analysis_presets import ANALYSIS_PRESETS, analysis_presets_payload, apply_analysis_preset
from tubeviz.gui import JobRequest, _job_command, create_gui_app


EXPECTED = {
    "classic-032",
    "source-first",
    "balanced",
    "high-energy",
    "edm",
    "relaxed",
    "vibrant",
    "cinematic",
    "dreamy",
    "experimental",
}


def test_analysis_preset_catalog_is_complete_and_json_ready():
    assert set(ANALYSIS_PRESETS) == EXPECTED
    payload = analysis_presets_payload()
    assert [item["id"] for item in payload] == list(ANALYSIS_PRESETS)
    assert all(item["label"] and item["description"] and item["parameters"] for item in payload)
    assert ANALYSIS_PRESETS["edm"]["parameters"]["trajectory_strength"] > ANALYSIS_PRESETS["balanced"]["parameters"]["trajectory_strength"]
    assert ANALYSIS_PRESETS["relaxed"]["parameters"]["min_shot_seconds"] > ANALYSIS_PRESETS["high-energy"]["parameters"]["min_shot_seconds"]
    assert ANALYSIS_PRESETS["experimental"]["parameters"]["codec_glitch"] == "musical"
    assert ANALYSIS_PRESETS["classic-032"]["parameters"]["creative_effects"] is False
    assert ANALYSIS_PRESETS["source-first"]["parameters"]["effect_density"] < ANALYSIS_PRESETS["balanced"]["parameters"]["effect_density"]


def test_analysis_preset_merge_keeps_explicit_manual_overrides():
    resolved = apply_analysis_preset({
        "analysis_preset": "edm",
        "transform_intensity": 0.25,
        "max_video_layers": 1,
    })
    assert resolved["transform_intensity"] == 0.25
    assert resolved["max_video_layers"] == 1
    assert resolved["trajectory_strength"] == ANALYSIS_PRESETS["edm"]["parameters"]["trajectory_strength"]


def test_analysis_preset_is_opt_in_for_non_studio_api_clients():
    options = {"semantic": True}
    assert apply_analysis_preset(options) == options
    assert apply_analysis_preset({"analysis_preset": "custom", **options}) == {"analysis_preset": "custom", **options}


def test_unknown_analysis_preset_is_rejected():
    with pytest.raises(ValueError, match="unknown analysis preset"):
        apply_analysis_preset({"analysis_preset": "gabber-space-opera"})


def test_gui_analyze_command_can_use_preset_defaults_with_manual_override():
    command = _job_command(JobRequest(
        kind="analyze",
        library="./library",
        audio="audio/song.mp3",
        output="timelines/song.json",
        options={"analysis_preset": "high-energy", "max_shot_seconds": 3.25},
    ))
    joined = " ".join(command)
    assert "--section-bars 4" in joined
    assert "--transform-intensity 1.5" in joined
    assert "--trajectory-strength 1.2" in joined
    assert "--min-shot-seconds 0.35" in joined
    assert "--max-shot-seconds 3.25" in joined


def test_classic_gui_command_disables_post_032_creative_renderer():
    command = _job_command(JobRequest(
        kind="analyze",
        library="./library",
        audio="audio/song.mp3",
        output="timelines/song.json",
        options={"analysis_preset": "classic-032"},
    ))
    joined = " ".join(command)
    assert "--section-bars 8" in joined
    assert "--transform-intensity 1.2" in joined
    assert "--composition-intensity 1.2" in joined
    assert "--effect-density 0.0" in joined
    assert "--hero-frequency 0.0" in joined
    assert "--no-creative-effects" in command


def test_gui_config_exposes_analysis_presets(tmp_path):
    client = TestClient(create_gui_app(default_library=tmp_path / "library", project_root=tmp_path))
    response = client.get("/api/gui/config")
    assert response.status_code == 200
    presets = response.json()["analysis_presets"]
    assert {item["id"] for item in presets} == EXPECTED
