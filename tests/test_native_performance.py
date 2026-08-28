# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import tubeviz.native_render as native_render
from tubeviz.cli import build_parser
from tubeviz.native_render import NativeRenderConfig, _raw_ffmpeg_command, _resolve_native_video_codec


def test_native_defaults_use_fast_encoder_and_cache():
    cfg = NativeRenderConfig()
    assert cfg.preset == "veryfast"
    assert cfg.video_codec == "auto"
    assert cfg.decoder_cache == 16
    assert cfg.threads == 0
    assert cfg.gpu == "auto"
    assert cfg.hwdecode == "auto"


def test_native_render_cli_exposes_performance_controls():
    args = build_parser().parse_args([
        "render", "timeline.json",
        "--backend", "native",
        "--native-preset", "superfast",
        "--native-decoder-cache", "24",
        "--native-threads", "8",
        "--native-gpu", "vulkan",
        "--native-hwdecode", "cuda",
    ])
    assert args.video_codec is None
    assert args.native_preset == "superfast"
    assert args.native_decoder_cache == 24
    assert args.native_threads == 8
    assert args.native_gpu == "vulkan"
    assert args.native_hwdecode == "cuda"


def test_native_source_has_lazy_avframe_fast_path_and_lru():
    root = Path("src/tubeviz/native_src")
    decoder = (root / "src/decoder.cpp").read_text()
    renderer = (root / "src/renderer.cpp").read_text()
    cmake = (root / "CMakeLists.txt").read_text()
    effects = (root / "src/effects.cpp").read_text()

    assert "const AVFrame* Decoder::avframe_at" in decoder
    assert "return held_frame_;" in decoder
    assert "if (!rgb_valid_) convert_held_frame();" in decoder
    assert "SWS_FAST_BILINEAR" in decoder
    assert "decoder_cache_limit_" in renderer
    assert "warm_shot" in renderer
    assert "OpenMP" in cmake
    assert "#pragma omp parallel for" in effects


def test_native_ffmpeg_default_command_has_safe_unresolved_auto_fallback():
    command = _raw_ffmpeg_command(
        output=Path("/tmp/out.mp4"),
        audio=None,
        duration=1.0,
        config=NativeRenderConfig(),
    )
    joined = " ".join(command)
    assert "-c:v libx264" in joined
    assert "-preset veryfast" in joined


def test_native_auto_encoder_prefers_usable_nvenc(monkeypatch):
    monkeypatch.setattr(native_render, "_ffmpeg_encoder_usable", lambda encoder: encoder == "h264_nvenc")
    assert _resolve_native_video_codec("auto") == "h264_nvenc"
    assert _resolve_native_video_codec(None) == "h264_nvenc"
    assert _resolve_native_video_codec("libx264") == "libx264"


def test_native_auto_encoder_falls_back_to_x264(monkeypatch):
    monkeypatch.setattr(native_render, "_ffmpeg_encoder_usable", lambda encoder: False)
    assert _resolve_native_video_codec("auto") == "libx264"


def test_native_nvenc_uses_cq_instead_of_crf():
    command = _raw_ffmpeg_command(
        output=Path("/tmp/out.mp4"),
        audio=None,
        duration=1.0,
        config=NativeRenderConfig(video_codec="h264_nvenc", crf=20),
    )
    joined = " ".join(command)
    assert "-c:v h264_nvenc" in joined
    assert "-cq 20" in joined
    assert "-b:v 0" in joined
    assert "-crf" not in command


def test_native_source_contains_resident_vulkan_cuda_and_perf_paths():
    root = Path("src/tubeviz/native_src")
    decoder = (root / "src/decoder.cpp").read_text()
    renderer = (root / "src/renderer.cpp").read_text()
    gpu = (root / "src/gpu.cpp").read_text()
    resident = (root / "src/resident_gpu.cpp").read_text()
    cmake = (root / "CMakeLists.txt").read_text()
    native_py = Path("src/tubeviz/native_render.py").read_text()

    assert "avcodec_get_hw_config" in decoder
    assert "AV_HWDEVICE_TYPE_CUDA" in decoder
    assert "av_hwdevice_ctx_create" in decoder
    assert '"primary_ctx", "1"' in decoder
    assert "SharedCudaDevice" in decoder
    assert "av_buffer_ref(shared)" in decoder
    assert "AV_PIX_FMT_FLAG_HWACCEL" in decoder
    assert "av_hwframe_transfer_data" in decoder

    assert "ResidentGpuPipeline" in renderer
    assert "render_shot_resident" in renderer
    assert "resident_->last_hardware_map_failed()" in renderer
    assert "software decode + GPU YUV upload" in renderer
    assert 'PERF\\tframes=' in renderer

    assert "pl_map_avframe_ex" in resident
    assert "pl_unmap_avframe" in resident
    assert "pl_tex_download" in resident
    assert "history_mix" in resident
    assert "pl_tex_blit" in resident

    assert "GpuPostProcessor" in renderer
    assert "apply_creative_temporal_effects" in renderer
    assert "previous_output_.swap(output)" in renderer
    assert "pl_vulkan_create" in gpu
    assert "pl_vulkan_create(impl_->log, nullptr)" in gpu
    assert "pl_mpv_user_shader_parse" in gpu
    assert "pl_render_image" in gpu
    assert "params.dynamic_constants = false" in gpu
    assert "src/gpu.cpp" in cmake
    assert "src/resident_gpu.cpp" in cmake
    assert "src/libav_bridge.c" in cmake
    assert 'line.startswith("PERF\\t")' in native_py


def test_studio_render_forwards_native_acceleration_controls():
    js = Path("src/tubeviz/static/gui.js").read_text()
    html = Path("src/tubeviz/static/gui.html").read_text()
    gui = Path("src/tubeviz/gui.py").read_text()
    assert 'native_gpu:value("nativeGpu")' in js
    assert 'native_hwdecode:value("nativeHwdecode")' in js
    assert 'id="nativeGpu"' in html
    assert 'id="nativeHwdecode"' in html
    assert '"--native-gpu"' in gui
    assert '"--native-hwdecode"' in gui


def test_studio_render_forwards_browser_acceleration_controls():
    js = Path("src/tubeviz/static/gui.js").read_text()
    html = Path("src/tubeviz/static/gui.html").read_text()
    gui = Path("src/tubeviz/gui.py").read_text()
    assert 'browser_transport:value("browserTransport")' in js
    assert 'browser_gpu:value("browserGpu")' in js
    assert 'browser_source_decode:value("browserSourceDecode")' in js
    assert 'webcodecs_bitrate:number("webcodecsBitrate")' in js
    assert 'id="browserTransport"' in html
    assert 'id="browserGpu"' in html
    assert 'id="browserSourceDecode"' in html
    assert 'id="webcodecsBitrate"' in html
    assert '"--browser-transport"' in gui
    assert '"--browser-gpu"' in gui
    assert '"--browser-source-decode"' in gui
    assert '"--webcodecs-bitrate"' in gui
