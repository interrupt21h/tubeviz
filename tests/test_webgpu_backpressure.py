# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_main_thread_webgpu_preview_drops_stale_frames_instead_of_queueing():
    gpu = Path("src/tubeviz/static/browser_gpu.js").read_text()
    assert "const REALTIME_MAX_INFLIGHT=1" in gpu
    assert "class RealtimeGpuFinalizer" in gpu
    assert "if(this.inflight>=REALTIME_MAX_INFLIGHT){this.dropped++;return true;}" in gpu
    assert "const completion=this.core.sync().then" in gpu
    assert "this.gpuMs=this.gpuMs?this.gpuMs*.85+elapsed*.15:elapsed" in gpu
    assert "return new RealtimeGpuFinalizer(core)" in gpu


def test_realtime_webgpu_defers_resize_and_history_reset_until_gpu_is_idle():
    gpu = Path("src/tubeviz/static/browser_gpu.js").read_text()
    assert "if(this.inflight){this.pendingResize={width,height};return;}" in gpu
    assert "if(this.inflight){this.pendingHistoryReset=true;return;}" in gpu
    assert "this._applyDeferred();" in gpu
