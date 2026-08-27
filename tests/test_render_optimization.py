# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_offline_renderer_does_not_wait_one_second_per_video_frame():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "function waitDecodedFrame" not in js
    assert "requestVideoFrameCallback(finish)" not in js
    assert "setTimeout(finish,1000)" not in js
    assert "video.addEventListener('seeked',finish" in js


def test_offline_renderer_streams_binary_without_playwright_or_image_compression():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    render_py = Path("src/tubeviz/render.py").read_text()
    server_py = Path("src/tubeviz/server.py").read_text()
    encoder_worker = Path("src/tubeviz/static/browser_encode_worker.js").read_text()
    assert "window.tubevizRenderOfflineSequence" in js
    assert "/ws/offline-render" in js
    assert "VideoEncoder" in js
    assert "VideoFrame" in js
    assert "exportRawRgba" in js and "ws.send(rgba.buffer)" in js
    assert "toBlob(" not in js and "btoa(" not in js
    assert "image2pipe" not in render_py
    assert "-f\", \"rawvideo" in render_py
    assert "base64.b64decode" not in render_py
    assert "offline_render_endpoint" in server_py
    assert "VideoEncoder" in encoder_worker and "ws.send(bytes)" in encoder_worker


def test_browser_webgpu_and_adaptive_preview_are_present():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    gpu = Path("src/tubeviz/static/browser_gpu.js").read_text() + Path("src/tubeviz/static/browser_gpu_core.js").read_text()
    assert "requestVideoFrameCallback" in js
    assert "adaptivePreviewHeight=720" in js
    assert "updateAdaptivePreview" in js
    assert "createBrowserGpuFinalizer" in js
    assert "navigator.gpu.requestAdapter" in gpu
    assert "copyExternalImageToTexture" in gpu
    # Common formerly-CPU raster passes are fused in WGSL.
    for token in ("posterize", "solarize", "blockDisplace", "slitScan", "datamosh"):
        assert token in gpu


def test_progress_is_reported_from_in_page_sequence_not_each_frame_rpc():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    render_py = Path("src/tubeviz/render.py").read_text()
    assert "tubevizReportOfflineProgress" in js
    assert "page.expose_function" in render_py
    assert "fps-total" in render_py
