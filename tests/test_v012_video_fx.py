from pathlib import Path

from tubeviz.models import VideoTransform


def test_video_transform_contains_temporal_synthesis_fields():
    transform = VideoTransform(
        slit_scan=.1,
        frame_echo=.2,
        mirror_corridor=.3,
        mask_wipe=.2,
        solarize=.2,
        datamosh=.4,
        block_displace=.3,
        chroma_delay=.2,
        vhs_tracking=.2,
        vortex=.3,
        motion_trails=.4,
        slice_recursion=.3,
        effect_style="fracture",
    )
    data = transform.model_dump()
    for field in (
        "slit_scan", "frame_echo", "mirror_corridor", "mask_wipe", "solarize",
        "datamosh", "block_displace", "chroma_delay", "vhs_tracking", "vortex",
        "motion_trails", "slice_recursion", "effect_style",
    ):
        assert field in data


def test_renderer_has_video_first_temporal_fx_and_live_controls():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    html = Path("src/tubeviz/static/index.html").read_text()
    for function in (
        "applySlitScan", "applyFrameEcho", "applyMirrorCorridor", "applyMaskWipe",
        "applySolarize", "applyDatamosh", "applyBlockDisplace", "applyChromaDelay",
        "applyVhsTracking", "applyVortex", "applyMotionTrails", "applySliceRecursion",
    ):
        assert f"function {function}" in js
    for control in ("fx-master", "fx-motion", "fx-trails", "fx-glitch", "fx-strobe"):
        assert control in html


def test_no_persistent_rectangular_motif_thumbnail():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    bad = "ctx.drawImage(videoFx,0,0,width,height,x-size/2,y-size/2,size,size)"
    assert bad not in js
    assert "ctx.clip()" in js
