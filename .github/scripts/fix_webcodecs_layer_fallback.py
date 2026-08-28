#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[2]
visualizer_path = root / "src/tubeviz/static/visualizer.js"
tests_path = root / "tests/test_browser_phase2.py"

visualizer = visualizer_path.read_text()
old = "        liveSourceDecodeMode='video';liveSourceDecodeReason=`WebCodecs fallback: ${String(error?.message||error)}`;updateRendererStatus(liveSourceDecodeReason);"
new = "        // Keep WebCodecs active for healthy layers; only this failed layer falls back to HTML video.\n        liveSourceDecodeReason=`WebCodecs layer fallback: ${String(error?.message||error)}`;updateRendererStatus(liveSourceDecodeReason);"
if old not in visualizer:
    raise SystemExit("expected global WebCodecs fallback line not found")
visualizer_path.write_text(visualizer.replace(old, new, 1))

tests = tests_path.read_text()
old_test = '    assert "liveSourceDecodeMode=\'video\'" in visualizer\n'
new_test = (
    '    assert "WebCodecs layer fallback:" in visualizer\n'
    '    assert "liveSourceDecodeMode=\'video\';liveSourceDecodeReason=`WebCodecs fallback:" not in visualizer\n'
    '    assert "if(offlineMode||liveSourceDecodeMode!==\'webcodecs\'||audio.paused)return;" in visualizer\n'
)
if old_test not in tests:
    raise SystemExit("expected old fallback assertion not found")
tests_path.write_text(tests.replace(old_test, new_test, 1))

print("per-layer WebCodecs fallback applied")
