# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_offline_renderer_does_not_wait_one_second_per_video_frame():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "function waitDecodedFrame" not in js
    assert "requestVideoFrameCallback(finish)" not in js
    assert "setTimeout(finish,1000)" not in js
    assert "video.addEventListener('seeked',finish" in js


def test_offline_renderer_exports_final_canvas_directly():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    render_py = Path("src/tubeviz/render.py").read_text()
    assert "window.tubevizRenderAndExport" in js
    assert "exportCanvas.toBlob" in js
    assert "exportCtx.drawImage(videoFx" in js
    assert "exportCtx.drawImage(canvas" in js
    assert "page.screenshot" not in render_py
    assert 'base64.b64decode(result["data"])' in render_py


def test_progress_reports_stage_timings():
    render_py = Path("src/tubeviz/render.py").read_text()
    assert "canvas-export" in render_py
    assert "ffmpeg-pipe" in render_py
