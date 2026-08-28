# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_live_preview_clock_is_not_owned_by_a_source_decoder():
    index = Path("src/tubeviz/static/index.html").read_text()
    guard = Path("src/tubeviz/static/preview_clock.js").read_text()
    visualizer = Path("src/tubeviz/static/visualizer.js").read_text()

    clock_script = '/static/preview_clock.js?v=0.44.0-previewfix2'
    visualizer_script = '/static/visualizer.js?v=0.44.0-timeline1'
    assert clock_script in index
    assert index.index(clock_script) < index.index(visualizer_script)

    # The visualizer already has a display-clock fallback. Hidden source videos
    # must not be allowed to hold that loop hostage while seeking or buffering.
    assert "Object.defineProperty(video, 'requestVideoFrameCallback'" in guard
    assert "value: undefined" in guard
    assert "video.dataset.tubevizPreviewClock = 'display'" in guard
    assert "HTMLVideoElement.prototype" not in guard
    assert "requestAnimationFrame(now=>runLiveFrame(now))" in visualizer


def test_preview_clock_guard_is_scoped_to_tubeviz_decoder_elements():
    guard = Path("src/tubeviz/static/preview_clock.js").read_text()
    assert "document.querySelectorAll('video.decoder')" in guard
    assert "globalThis.__tubevizPreviewClock" in guard
