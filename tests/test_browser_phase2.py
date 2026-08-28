# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import struct
from pathlib import Path

from tubeviz.render import RenderConfig
from tubeviz.server import _annexb_nals, _pack_sequence_h264


def nal(kind: int, payload: bytes = b"x") -> bytes:
    return b"\x00\x00\x00\x01" + bytes([kind & 0x1F]) + payload


def test_sequential_transport_packs_key_and_delta_access_units():
    stream = b"".join([
        nal(7, b"sps"), nal(8, b"pps"),
        nal(9, b"aud0"), nal(5, b"frame0"),
        nal(9, b"aud1"), nal(1, b"frame1"),
    ])
    packed, count = _pack_sequence_h264(stream, fps=30.0)
    assert count == 2
    assert packed[:4] == b"TVZ2"
    frames, fps = struct.unpack("<If", packed[4:12])
    assert frames == 2 and fps == 30.0
    offset = 12
    flags = []
    for _ in range(frames):
        key, length = struct.unpack("<BI", packed[offset:offset+5]); offset += 5
        unit = packed[offset:offset+length]; offset += length
        flags.append(key)
        types = []
        for item in _annexb_nals(unit):
            start = 4 if item.startswith(b"\x00\x00\x00\x01") else 3
            types.append(item[start] & 0x1F)
        if key:
            assert 5 in types
            assert 7 in types and 8 in types
        else:
            assert 1 in types
    assert flags == [1, 0]


def test_browser_phase2_source_decoder_and_worker_gpu_assets_exist():
    source = Path("src/tubeviz/static/browser_source.js").read_text()
    visualizer = Path("src/tubeviz/static/visualizer.js").read_text()
    core = Path("src/tubeviz/static/browser_gpu_core.js").read_text()
    facade = Path("src/tubeviz/static/browser_gpu.js").read_text()
    worker = Path("src/tubeviz/static/browser_gpu_worker.js").read_text()
    source_worker = Path("src/tubeviz/static/browser_source_worker.js").read_text()
    encoder_worker = Path("src/tubeviz/static/browser_encode_worker.js").read_text()
    assert "VideoDecoder" in source and "EncodedVideoChunk" in source
    assert "TVZ2" in source and "decodedThrough" in source and "nearestKey" in source_worker
    assert "browser_source_worker.js" in source and "VideoDecoder" in source_worker
    assert "/api/offline-source/" in source
    assert "WebCodecsSceneSource" in visualizer
    assert "sourceDecode" in visualizer
    assert "transferControlToOffscreen" in facade
    assert "new VideoFrame" in facade
    assert "createGpuRendererCore" in worker
    assert "historyTex" in core and "copyTextureToTexture" in core
    assert "source-chroma" in core.lower()
    assert "VideoEncoder" in encoder_worker and "new WebSocket" in encoder_worker



def test_webgpu_shader_and_texture_contract_matches_current_validation_rules():
    core = Path("src/tubeviz/static/browser_gpu_core.js").read_text()
    assert "let target=params.p4.zw" not in core
    assert "let focalTarget=params.p4.zw" in core
    assert "GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT" in core
    assert "format:this.format" in core
    assert "createRenderPipelineAsync" in core
    assert "getCompilationInfo" in core
    assert "uncapturederror" in core
    assert "beatWarpUv" in core
    assert "p13: vec4f" in core
    assert "size:224" in core
    visualizer = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "currentBeatWarpState" in visualizer
    assert "beatMode:beatState.mode" in visualizer


def test_browser_source_decode_config_validation():
    RenderConfig(browser_source_decode="auto").validate()
    RenderConfig(browser_source_decode="webcodecs").validate()
    RenderConfig(browser_source_decode="video").validate()
    try:
        RenderConfig(browser_source_decode="bogus").validate()
    except ValueError as exc:
        assert "browser_source_decode" in str(exc)
    else:
        raise AssertionError("invalid source decoder mode accepted")


def test_webgpu_preview_probes_before_transfer_and_falls_back_safely():
    facade = Path("src/tubeviz/static/browser_gpu.js").read_text()
    worker = Path("src/tubeviz/static/browser_gpu_worker.js").read_text()
    visualizer = Path("src/tubeviz/static/visualizer.js").read_text()
    index = Path("src/tubeviz/static/index.html").read_text()
    assert facade.index("await probeWorkerWebGpu(worker)") < facade.index("canvas.transferControlToOffscreen()")
    assert "preferWorker:offlineMode" in visualizer
    assert "disableBrowserGpu" in visualizer
    assert "Preview renderer:" in visualizer
    assert "probe-result" in worker and "OffscreenCanvas(4,4)" in worker
    assert "render-meta" in index
    assert "WebGPU requested for offline rendering but unavailable" in visualizer



def test_webgpu_wgsl_mutation_and_webcodecs_lifecycle_regressions():
    core = Path("src/tubeviz/static/browser_gpu_core.js").read_text()
    facade = Path("src/tubeviz/static/browser_gpu.js").read_text()
    source = Path("src/tubeviz/static/browser_source.js").read_text()
    source_worker = Path("src/tubeviz/static/browser_source_worker.js").read_text()
    visualizer = Path("src/tubeviz/static/visualizer.js").read_text()

    assert "var angle=a*.24*polarity" in core
    assert "let angle=a*.24*polarity" not in core
    assert "angle+=sin(r*34.0*frequency" in core
    assert "avc1.64002a" in source
    assert "avc1.4d002a" not in source
    assert "avc1.42002a" not in source
    assert "VideoDecoder.isConfigSupported" in source_worker
    assert "hardwareAcceleration:'no-preference'" in source_worker
    assert "hardwareAcceleration:'prefer-software'" in source_worker
    assert "m.frame?.close?.()" in source
    assert "effect?.close()" in facade and "source?.close()" in facade
    assert "rejectWaiters(s,new Error('source decoder closed'))" in source_worker
    assert "bankState[bankIndex]=[]" in visualizer
    assert "st.source.closed" in visualizer
    assert "live WebCodecs source failed; switching this preview to HTMLVideoElement" in visualizer
    assert "liveSourceDecodeMode='video'" in visualizer


def test_preview_module_graph_is_release_cache_busted():
    index = Path("src/tubeviz/static/index.html").read_text()
    visualizer = Path("src/tubeviz/static/visualizer.js").read_text()
    gpu = Path("src/tubeviz/static/browser_gpu.js").read_text()
    source = Path("src/tubeviz/static/browser_source.js").read_text()
    assert "/static/visualizer.js?v=0.42.1" in index
    assert "/static/browser_gpu.js?v=0.42.1" in visualizer
    assert "/static/browser_source.js?v=0.42.1" in visualizer
    assert "/static/browser_gpu_core.js?v=0.42.1" in gpu
    assert "/static/browser_source_worker.js?v=0.42.1" in source
