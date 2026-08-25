# SPDX-License-Identifier: Apache-2.0
from tubeviz.cli import build_parser


def test_analyze_choreography_options_parse():
    args=build_parser().parse_args([
        "analyze","song.mp3","--no-choreography","--trajectory-strength","1.1",
        "--anticipation-seconds","18","--sequence-lookahead","7","--sequence-beam-width","8",
        "--sequence-candidate-pool","24","--trajectory-weight",".9",
        "--anticipation-weight",".8","--effect-compatibility-weight",".7",
        "--no-preference-learning","--preference-weight",".5",
    ])
    assert args.choreography is False
    assert args.trajectory_strength == 1.1
    assert args.sequence_lookahead == 7
    assert args.sequence_beam_width == 8
    assert args.effect_compatibility_weight == .7
    assert args.preference_learning is False
    assert args.preference_weight == .5


def test_serve_sequence_options_parse():
    args=build_parser().parse_args(["serve","timeline.json","--sequence-lookahead","6","--trajectory-weight",".95"])
    assert args.sequence_lookahead == 6
    assert args.trajectory_weight == .95
