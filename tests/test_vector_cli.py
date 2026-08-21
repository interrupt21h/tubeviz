from tubeviz.cli import build_parser


def test_analyze_vector_controls_parse():
    args = build_parser().parse_args([
        "analyze", "song.mp3",
        "--no-vector-effects",
        "--vector-intensity", "1.6",
    ])
    assert args.vector_effects is False
    assert args.vector_intensity == 1.6


def test_serve_vector_controls_parse():
    args = build_parser().parse_args([
        "serve", "timeline.json",
        "--replan-scenes",
        "--vector-intensity", ".5",
    ])
    assert args.vector_effects is True
    assert args.vector_intensity == .5
