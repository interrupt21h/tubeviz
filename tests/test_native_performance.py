# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.cli import build_parser
from tubeviz.native_render import NativeRenderConfig, _raw_ffmpeg_command


def test_native_defaults_use_fast_encoder_and_cache():
    cfg = NativeRenderConfig()
    assert cfg.preset == "veryfast"
    assert cfg.decoder_cache == 16
    assert cfg.threads == 0


def test_native_render_cli_exposes_performance_controls():
    args = build_parser().parse_args([
        "render", "timeline.json",
        "--backend", "native",
        "--native-preset", "superfast",
        "--native-decoder-cache", "24",
        "--native-threads", "8",
    ])
    assert args.native_preset == "superfast"
    assert args.native_decoder_cache == 24
    assert args.native_threads == 8


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
