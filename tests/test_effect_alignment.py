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



def test_resident_native_gpu_uses_post_composite_radial_spatial_grammar():
    source = Path("src/tubeviz/native_src/src/resident_gpu.cpp").read_text()
    assert "float ring=sin(rr*34.0-phase*4.6)" in source
    assert "float va=vortex*.24*(1.0-smoothstep(.04,.95,vr))" in source
    assert 'set_param(impl_->layer_hook, "ripple", 0.0f)' in source
    assert 'set_param(impl_->layer_hook, "vortex", 0.0f)' in source
    assert 'set_param(impl_->final_hook, "beat_variant"' in source
    assert 'set_param(impl_->final_hook, "beat_phase"' in source
    assert 'set_param(impl_->final_hook, "beat_polarity"' in source
    assert "float wave=flow*.010+ripple*.008" not in source


def test_canvas_fallback_uses_radial_source_over_geometry():
    source = Path("src/tubeviz/static/visualizer.js").read_text()
    ripple = source.split("function applyRipple(amount){", 1)[1].split("function applyTiles", 1)[0]
    vortex = source.split("function applyVortex(amount){", 1)[1].split("function applyMotionTrails", 1)[0]
    assert "fx.clip('evenodd')" in ripple
    assert "globalCompositeOperation='source-over'" in ripple
    assert "n*34-time*4.6" in ripple
    assert "fx.clip('evenodd')" in vortex
    assert "globalCompositeOperation='source-over'" in vortex
    assert "amount*.24*falloff" in vortex


def test_persistent_heavy_effect_defaults_are_sparse():
    source = Path("src/tubeviz/transforms.py").read_text()
    assert 'ripple = accent("ripple", ripple, .24, .09)' in source
    assert 'slit_scan = accent("slit scan", slit_scan, .18, .09)' in source
    assert 'datamosh = accent("datamosh-like block displacement", datamosh, .16, .10' in source
    assert '_density_gate(vortex_gate, .12, event_density' in source
