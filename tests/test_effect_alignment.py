# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_webgpu_ripple_is_radial_and_source_preserving():
    source = Path("src/tubeviz/static/browser_gpu_core.js").read_text()
    assert "fn radialRippleUv" in source
    assert "let radialDir=p/max(r,.0001)" in source
    assert "let ring=sin(r*34.0-time*4.6)" in source
    assert "let falloff=1.0-smoothstep(.03,1.05,r)" in source
    assert "uv=radialRippleUv(uv" in source
    assert "sin(uv.y*24.0-time*3.1)" not in source


def test_native_gpu_ripple_uses_the_same_radial_grammar():
    source = Path("src/tubeviz/native_src/src/gpu.cpp").read_text()
    assert "float ring = sin(rr*34.0 - phase*4.6);" in source
    assert "float falloff = 1.0 - smoothstep(.03, 1.05, rr);" in source
    assert "vec2 radial = rp / max(rr, .0001);" in source
    assert "ripple*.006" not in source


def test_native_vortex_has_radial_falloff_instead_of_flat_rotation():
    source = Path("src/tubeviz/native_src/src/gpu.cpp").read_text()
    assert "float va = vortex * .24 * (1.0 - smoothstep(.04, .95, vr));" in source
    assert "float va = vortex * .018;" not in source


def test_effect_scheduler_has_cooldowns_for_heavy_punctuation():
    source = Path("src/tubeviz/editing.py").read_text()
    assert "def add_effect(" in source
    for action in (
        "video_edit_ripple",
        "video_edit_vortex",
        "video_edit_kaleidoscope",
        "video_edit_datamosh",
        "video_edit_slice_recursion",
    ):
        assert action in source
    assert "cooldown=" in source
