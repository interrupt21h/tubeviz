# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.cli import build_parser
from tubeviz.native_render import NativeRenderConfig, _raw_ffmpeg_command


def test_native_defaults_use_fast_encoder_and_cache():
    cfg = NativeRenderConfig()
    assert cfg.preset == "veryfast"
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
    assert args.native_preset == "superfast"
    assert args.native_decoder_cache == 24
    assert args.native_threads == 8
    assert args.native_gpu == "vulkan"
    assert args.native_hwdecode == "cuda"


def test_native_source_has_cached_frame_fast_path_and_lru():
    root = Path("src/tubeviz/native_src")
    decoder = (root / "src/decoder.cpp").read_text()
    renderer = (root / "src/renderer.cpp").read_text()
    cmake = (root / "CMakeLists.txt").read_text()
    effects = (root / "src/effects.cpp").read_text()

    assert "already-decoded frame covers this requested time" in decoder
    assert "return rgb_;" in decoder
    assert "SWS_FAST_BILINEAR" in decoder
    assert "decoder_cache_limit_" in renderer
    assert "warm_shot" in renderer
    assert "OpenMP" in cmake
    assert "#pragma omp parallel for" in effects


def test_native_ffmpeg_default_uses_veryfast():
    command = _raw_ffmpeg_command(
        output=Path("/tmp/out.mp4"),
        audio=None,
        duration=1.0,
        config=NativeRenderConfig(),
    )
    joined = " ".join(command)
    assert "-preset veryfast" in joined


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


def test_native_source_contains_vulkan_and_cuda_acceleration_paths():
    root = Path("src/tubeviz/native_src")
    decoder = (root / "src/decoder.cpp").read_text()
    renderer = (root / "src/renderer.cpp").read_text()
    gpu = (root / "src/gpu.cpp").read_text()
    cmake = (root / "CMakeLists.txt").read_text()

    assert "avcodec_get_hw_config" in decoder
    assert "AV_HWDEVICE_TYPE_CUDA" in decoder
    assert "av_hwdevice_ctx_create" in decoder
    assert '"primary_ctx", "1"' in decoder
    assert "SharedCudaDevice" in decoder
    assert "av_buffer_ref(shared)" in decoder
    assert "AV_PIX_FMT_FLAG_HWACCEL" in decoder
    assert "av_hwframe_transfer_data" in decoder
    assert "GpuPostProcessor" in renderer
    assert "apply_creative_temporal_effects" in renderer
    assert "previous_output_.swap(output)" in renderer
    assert "pl_vulkan_create" in gpu
    assert "pl_vulkan_create(impl_->log, nullptr)" in gpu
    assert "pl_log_params(" not in gpu
    assert "pl_vulkan_params(" not in gpu
    assert "pl_mpv_user_shader_parse" in gpu
    assert "pl_render_image" in gpu
    assert "params.dynamic_constants = false" in gpu
    assert "pl_find_fmt(impl_->gpu, PL_FMT_UNORM, 3" in gpu
    assert "rgb.swap(impl_->rgb_out)" in gpu
    assert "src/gpu.cpp" in cmake


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
