from tubeviz.cli import build_parser


def test_visual_index_cli_parses():
    args = build_parser().parse_args([
        "library", "visual-index",
        "--library", "./library",
        "--fps", "8",
        "--max-frames", "120",
        "--force",
    ])
    assert args.library == "./library"
    assert args.fps == 8
    assert args.max_frames == 120
    assert args.force is True


def test_analyze_visual_director_options_parse():
    args = build_parser().parse_args([
        "analyze", "song.mp3",
        "--visual-match-weight", "1.5",
        "--transition-weight", ".8",
        "--no-rhythm-alignment",
    ])
    assert args.visual_match_weight == 1.5
    assert args.transition_weight == .8
    assert args.rhythm_alignment is False
