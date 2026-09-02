# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

import pytest

from tubeviz.aesthetic_density import classic_032_density_violations, measure_aesthetic_density
from tubeviz.analysis_presets import ANALYSIS_PRESETS, apply_analysis_preset


ROOT = Path(__file__).resolve().parents[1]


def test_classic_032_restores_pre_creative_renderer_grammar() -> None:
    p = ANALYSIS_PRESETS["classic-032"]["parameters"]

    # Historical v0.32.1 Studio/editor values that materially affect the cut.
    assert p["section_bars"] == 8
    assert p["max_video_layers"] == 3
    assert p["transform_intensity"] == pytest.approx(1.20)
    assert p["composition_intensity"] == pytest.approx(1.20)
    assert p["novelty_weight"] == pytest.approx(0.65)
    assert p["visual_match_weight"] == pytest.approx(1.25)
    assert p["transition_weight"] == pytest.approx(0.70)
    assert p["trajectory_strength"] == pytest.approx(0.85)
    assert p["sequence_lookahead"] == 5
    assert p["sequence_beam_width"] == 6
    assert p["vector_effects"] is True
    assert p["vector_intensity"] == pytest.approx(1.0)
    assert p["min_shot_seconds"] == pytest.approx(0.65)
    assert p["max_shot_seconds"] == pytest.approx(6.0)
    assert p["source_excerpt_max_seconds"] == pytest.approx(5.0)
    assert p["audio_visual_match_weight"] == pytest.approx(1.10)

    # Post-v0.32 semantic/temporal creative rendering is not part of Classic.
    assert p["creative_effects"] is False
    assert p["creative_intensity"] == 0
    assert p["effect_density"] == 0
    assert p["temporal_persistence"] == 0
    assert p["hero_frequency"] == 0
    assert p["codec_glitch"] == "off"
    assert p["composition_diversity"] <= 1.10


def test_source_first_keeps_modern_renderer_but_restores_visual_dynamic_range() -> None:
    p = ANALYSIS_PRESETS["source-first"]["parameters"]
    assert p["creative_effects"] is True
    assert 0 < p["creative_intensity"] <= 0.40
    assert p["effect_density"] <= 0.20
    assert p["temporal_persistence"] <= 0.15
    assert p["hero_frequency"] <= 0.15
    assert 1.15 <= p["composition_intensity"] <= 1.35
    assert p["composition_diversity"] <= 0.35
    assert p["vector_intensity"] <= 0.70
    assert p["choreography"] is True
    assert p["dynamic_shots"] is True
    assert p["rhythm_alignment"] is True


def test_presets_remain_user_editable_after_application() -> None:
    resolved = apply_analysis_preset({
        "analysis_preset": "classic-032",
        "transition_weight": 1.05,
        "vector_intensity": 0.4,
    })
    assert resolved["creative_effects"] is False
    assert resolved["transition_weight"] == pytest.approx(1.05)
    assert resolved["vector_intensity"] == pytest.approx(0.4)


def test_aesthetic_density_reports_effect_stacking_and_clean_runs() -> None:
    timeline = {
        "scene_plan": [
            {
                "composition_mode": "single",
                "layers": [],
                "transform": {},
                "direction": {"creative": {}, "vector_effects": [], "codec_effects": []},
                "codec_materialization": {},
            },
            {
                "composition_mode": "single",
                "layers": [],
                "transform": {},
                "direction": {
                    "creative": {},
                    "vector_effects": [{"kind": "contours", "amount": 0.5, "opacity": 0.2, "visible": True}],
                    "codec_effects": [],
                },
                "codec_materialization": {},
            },
            {
                "composition_mode": "flow",
                "layers": [{"opacity": 0.5}],
                "transform": {"glitch": 0.25},
                "direction": {
                    "creative": {
                        "flow_warp": 0.4,
                        "temporal_echo": 0.3,
                        "hero_kind": "flow_melt",
                        "hero_amount": 0.7,
                    },
                    "vector_effects": [],
                    "codec_effects": [{"kind": "mv", "amount": 0.4}],
                },
                "codec_materialization": {},
            },
        ]
    }

    report = measure_aesthetic_density(timeline)
    assert report["shots"] == 3
    assert report["creative_fx_fraction"] == pytest.approx(1 / 3)
    assert report["hero_fraction"] == pytest.approx(1 / 3)
    assert report["creative_temporal_fraction"] == pytest.approx(1 / 3)
    assert report["vector_fraction"] == pytest.approx(1 / 3)
    assert report["codec_fraction"] == pytest.approx(1 / 3)
    assert report["layered_fraction"] == pytest.approx(1 / 3)
    assert report["legacy_fx_fraction"] == pytest.approx(1 / 3)
    assert report["clean_shot_fraction"] == pytest.approx(1 / 3)
    assert report["max_treatment_families"] >= 5
    assert report["max_visible_vector_families"] == 1
    assert report["max_clean_run"] == 1

    violations = classic_032_density_violations(report)
    assert any("creative_fx_fraction" in item for item in violations)
    assert any("hero_fraction" in item for item in violations)
    assert any("creative_temporal_fraction" in item for item in violations)


def test_clean_classic_density_has_no_modern_creative_violations() -> None:
    timeline = {
        "scene_plan": [
            {
                "composition_mode": "flow",
                "layers": [{"opacity": 0.5}],
                "transform": {"ripple": 0.25},
                "direction": {
                    "creative": {},
                    "vector_effects": [
                        {"kind": "contours", "amount": 0.4, "opacity": 0.2, "visible": True},
                        {"kind": "flow_ribbons", "amount": 0.3, "opacity": 0.15, "visible": True},
                    ],
                    "codec_effects": [],
                },
                "codec_materialization": {},
            }
        ]
    }
    report = measure_aesthetic_density(timeline)
    assert classic_032_density_violations(report) == []


def test_preview_filter_controller_loads_before_visualizer_and_exposes_effect_families() -> None:
    html = (ROOT / "src/tubeviz/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "src/tubeviz/static/preview_effect_filters.js").read_text(encoding="utf-8")

    assert html.index("preview_effect_filters.js") < html.index("visualizer.js")
    assert "/api/timeline" in js
    assert "timeline unchanged" in js
    assert "TubevizPreviewEffects" in js
    assert "BroadcastChannel" in js
    assert "classic" in js and "source" in js
    for label in ("Transform", "Color", "Vector", "Creative", "Temporal", "Warp", "Layers", "Codec", "Legacy FX"):
        assert label in js

    # Preview filters must remain a view over the timeline, not a timeline rewrite.
    assert "window.fetch = async function tubevizPreviewFilteredFetch" in js
    assert "new Proxy" in js
    assert "originalTimeline" in js

    # Keep the actual Response object standards-compatible; proxy only decoded
    # timeline data. This avoids browser internal-slot failures during startup.
    assert "response.clone().json()" in js
    assert "Object.defineProperty(response, 'json'" in js
    assert "new Proxy(response" not in js

    # Timeline transport commands may arrive as soon as the preview server is
    # reachable, before the module renderer has finished initializing. They must
    # survive that startup window so the Studio Play button cannot lose a click.
    assert "queuedTransportCommand" in js
    assert "replayTransportCommand" in js
    assert "tubeviz-preview-command" in js
    assert "window.addEventListener('load'" in js
