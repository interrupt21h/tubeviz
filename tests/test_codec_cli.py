# SPDX-License-Identifier: Apache-2.0
from tubeviz.cli import build_parser


def test_analyze_codec_glitch_options():
    args = build_parser().parse_args([
        "analyze", "song.mp3", "--codec-glitch", "musical",
        "--codec-glitch-intensity", ".75",
    ])
    assert args.codec_glitch == "musical"
    assert args.codec_glitch_intensity == .75


def test_codec_doctor_cli():
    args = build_parser().parse_args(["codec", "doctor", "--ffedit", "/opt/ffedit"])
    assert args.ffedit == "/opt/ffedit"


def test_codec_materialize_cli():
    args = build_parser().parse_args([
        "codec", "materialize", "timeline.json", "--library", "./library",
        "--qscale", "2", "--gop", "24",
    ])
    assert args.timeline == "timeline.json"
    assert args.qscale == 2
    assert args.gop == 24


def test_render_codec_materialize_option():
    args = build_parser().parse_args([
        "render", "timeline.json", "--codec-materialize", "--codec-qscale", "2"
    ])
    assert args.codec_materialize is True
    assert args.codec_qscale == 2
