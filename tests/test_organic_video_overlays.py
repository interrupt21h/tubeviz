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
