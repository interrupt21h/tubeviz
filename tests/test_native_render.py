# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.cli import build_parser
from tubeviz.models import (
    CompositeLayer,
    DirectedTimeline,
    SceneSelection,
    TrackAnalysis,
    VideoTransform,
    VisualCue,
)
from tubeviz.native_render import (
    NativeRenderConfig,
    _raw_ffmpeg_command,
    native_doctor,
    native_source_dir,
    write_native_manifest,
)


def _timeline(tmp_path: Path) -> DirectedTimeline:
    library = tmp_path / "library"
    media = library / "normalized"
    media.mkdir(parents=True)
    (media / "a.mp4").write_bytes(b"a")
    (media / "b.mp4").write_bytes(b"b")
    track = TrackAnalysis(
        source=str(tmp_path / "song.wav"),
        duration=8.0,
        sample_rate=22050,
        hop_length=512,
        tempo_bpm=120.0,
        beats=[0.0, 0.5, 1.0],
        bars=[0.0, 2.0],
        sections=[],
        events=[],
    )
    scene = SceneSelection(
        section_index=0,
        time=0.0,
        term="archive",
        clip_id=1,
        scene_id=1,
        scene_index=0,
        source_id="a",
        media_file="normalized/a.mp4",
        media_url="/media/normalized/a.mp4",
        start=2.0,
        end=4.0,
        duration=2.0,
        crossfade_seconds=.4,
        opacity=.9,
        transform=VideoTransform(mirror=True, brightness=1.1, ripple=.2),
        layers=[
            CompositeLayer(
                clip_id=2,
                scene_id=2,
                scene_index=0,
                source_id="b",
                media_file="normalized/b.mp4",
                media_url="/media/normalized/b.mp4",
                start=5.0,
                end=7.0,
                duration=2.0,
                opacity=.5,
                blend_mode="screen",
            )
        ],
    )
    cues = [
        VisualCue(
            time=.5,
            action="beat_warp",
            parameters={"amount": .8, "low": .9, "mid": .2, "high": .1, "warp_mode_id": 6, "warp_variant": 3, "center_x": .62, "center_y": .41, "direction": 1.2, "frequency": 1.7, "polarity": -1, "duration": .2, "attack": .05, "overshoot": .25},
        ),
        VisualCue(time=1.0, action="video_edit_ripple", parameters={"amount": .5}),
        VisualCue(time=1.5, action="unsupported_browser_only", parameters={"amount": 1}),
    ]
    return DirectedTimeline(track=track, cues=cues, scene_plan=[scene])


def test_native_manifest_contains_shot_layers_and_supported_music_cues(tmp_path: Path):
    timeline = _timeline(tmp_path)
    manifest = write_native_manifest(
        timeline,
        tmp_path / "library",
        tmp_path / "render.tsv",
    )
    text = manifest.read_text()
    assert "META\t8.000000000" in text
    assert "SHOT\t0.000000000\t8.000000000" in text
    assert "normalized/a.mp4" in text
    assert "LAYER" in text and "screen" in text
    assert "CUE\t0.500000000\tbeat_warp" in text
    beat_line = next(line for line in text.splitlines() if line.startswith("CUE\t0.500000000\tbeat_warp"))
    fields = beat_line.split("\t")
    assert fields[7:9] == ["6", "3"]
    assert fields[9:11] == ["0.620000000", "0.410000000"]
    assert fields[13] == "-1.000000000"
    assert "CUE\t1.000000000\tvideo_edit_ripple" in text
    assert "unsupported_browser_only" not in text


def test_native_ffmpeg_path_is_raw_rgb_not_image_pipe(tmp_path: Path):
    command = _raw_ffmpeg_command(
        output=tmp_path / "out.mp4",
        audio=tmp_path / "song.wav",
        duration=8.0,
        config=NativeRenderConfig(width=1280, height=720, fps=30),
    )
    joined = " ".join(command)
    assert "-f rawvideo" in joined
    assert "-pixel_format rgb24" in joined
    assert "-video_size 1280x720" in joined
    assert "image2pipe" not in joined


def test_native_source_tree_is_packaged_and_has_phase2_shader():
    source = native_source_dir()
    assert (source / "CMakeLists.txt").is_file()
    assert (source / "src/decoder.cpp").is_file()
    assert (source / "src/renderer.cpp").is_file()
    assert (source / "shaders/beat_warp.glsl").is_file()


def test_render_cli_supports_backend_and_native_controls():
    args = build_parser().parse_args([
        "render", "timeline.json", "--backend", "native",
        "--native-binary", "/tmp/tubeviz-native-render",
        "--native-keep-manifest",
    ])
    assert args.backend == "native"
    assert args.native_binary == "/tmp/tubeviz-native-render"
    assert args.native_keep_manifest is True


def test_native_cli_build_and_doctor_parse():
    parser = build_parser()
    build = parser.parse_args(["native", "build", "--clean", "--jobs", "8"])
    assert build.clean is True and build.jobs == 8
    doctor = parser.parse_args(["native", "doctor"])
    assert doctor.native_command == "doctor"


def test_native_doctor_reports_toolchain_keys():
    info = native_doctor()
    assert "renderer" in info
    assert "cmake" in info
    assert "libraries" in info
    assert "libavcodec" in info["libraries"]


def test_render_cli_supports_browser_acceleration_controls():
    args = build_parser().parse_args([
        "render", "timeline.json", "--backend", "browser",
        "--browser-transport", "webcodecs",
        "--browser-gpu", "webgpu",
        "--browser-source-decode", "webcodecs",
        "--webcodecs-bitrate", "12000000",
    ])
    assert args.browser_transport == "webcodecs"
    assert args.browser_gpu == "webgpu"
    assert args.browser_source_decode == "webcodecs"
    assert args.webcodecs_bitrate == 12_000_000
