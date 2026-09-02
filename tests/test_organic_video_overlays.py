# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.scene_selector import _composition_mode


def test_default_compositor_avoids_boxed_modes():
    modes = {
        _composition_mode("ambient", .2, 0, 2, "ambient"),
        _composition_mode("drive", .5, 1, 2, "driving"),
        _composition_mode("build", .7, 2, 3, "groove"),
        _composition_mode("peak", .9, 4, 4, "heavy"),
    }
    assert not modes.intersection({"pip", "split", "mosaic"})
    assert modes <= {"single", "flow", "luma", "strips"}


def test_renderer_has_no_rectangular_onset_video_patch():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "Onset fragments are now fluid refraction droplets" in js
    assert "ctx.bezierCurveTo" in js
    assert "function organicMask" in js
    # Old implementation copied a source rectangle directly to another rectangle.
    assert "ctx.drawImage(videoFx,sx,sy,w,h,sx+f.vx*80" not in js


def test_legacy_tiles_are_organic_lenses():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    start = js.index("function applyTiles")
    end = js.index("function applyKaleidoscope", start)
    body = js[start:end]
    assert "fx.ellipse" in body
    assert "for(let y=0;y<grid" not in body


def test_beat_warp_is_frequency_aware():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "function applyBeatWarp(state)" in js
    assert "currentBeatWarpState" in js
    assert "beatWarpEvent" in js
    assert "video_edit_beat_warp" in js
    assert "tempoWarpFx" in js


def test_gpu_flow_compositor_uses_semantic_organic_mask():
    gpu = Path("src/tubeviz/static/browser_gpu_core.js").read_text()
    assert "fn organicFlowMask" in gpu
    assert "subjectRadius" in gpu
    assert "subjectPreserve" in gpu
    assert "boundary=.90+.14*sin" in gpu
    # Regression: the direct WebGPU path must not fall back to the old soft ellipse.
    assert "let dx=(uv.x-cx)/(.26+.035*fi)" not in gpu

    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "semanticTarget=creativeTarget()" in js
    assert "subjectPreserve:Number(semanticCreative.subject_preserve" in js
    assert "fx.clip('evenodd')" in js


def test_native_flow_compositors_use_semantic_target_and_subject_protection():
    resident = Path("src/tubeviz/native_src/src/resident_gpu.cpp").read_text()
    cpu = Path("src/tubeviz/native_src/src/effects.cpp").read_text()
    assert '//!PARAM subject_radius' in resident
    assert '//!PARAM subject_preserve' in resident
    assert 'target+vec2(sin(phase*.40' in resident
    assert 'subject*preserve*.80' in resident
    assert "Semantic organic mask" in cpu
    assert "creative->target_x" in cpu
    assert "creative->subject_preserve" in cpu


def test_directed_color_is_not_reclamped_to_tiny_postfix_range():
    browser = Path("src/tubeviz/static/visualizer.js").read_text()
    cpu = Path("src/tubeviz/native_src/src/effects.cpp").read_text()
    gpu = Path("src/tubeviz/native_src/src/gpu.cpp").read_text()
    assert "Math.max(-95,Math.min(95" in browser
    assert "std::clamp(c.color_hue_shift, -95.0, 95.0)" in cpu
    assert "std::clamp(c.color_hue_shift, -95.0, 95.0)" in gpu
    assert "directedColorIntent" in browser
    assert "directed_color_ramp" in cpu
