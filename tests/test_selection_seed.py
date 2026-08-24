# SPDX-License-Identifier: Apache-2.0
from tubeviz.cli import build_parser
from tubeviz.scene_selector import _scene_rank
from tubeviz.library import SceneCandidate


def candidate(scene_id: int) -> SceneCandidate:
    return SceneCandidate(
        scene_id=scene_id,
        clip_id=scene_id,
        source_id=f"id{scene_id}",
        title=f"clip {scene_id}",
        normalized_path=f"normalized/id{scene_id}.mp4",
        scene_index=0,
        start_time=0.0,
        end_time=8.0,
        duration=8.0,
        thumbnail_path=None,
        description=None,
        channel=None,
        term="test",
        term_rank=scene_id,
    )


def test_seed_zero_preserves_semantic_order():
    a, b = candidate(1), candidate(2)
    assert _scene_rank(a, 8, "x", 1.0, selection_seed=0, selection_variation=10) < \
           _scene_rank(b, 8, "x", 0.9, selection_seed=0, selection_variation=10)


def test_same_seed_is_reproducible():
    c = candidate(7)
    a = _scene_rank(c, 8, "section", 0.5, selection_seed=1234, selection_variation=.3)
    b = _scene_rank(c, 8, "section", 0.5, selection_seed=1234, selection_variation=.3)
    assert a == b


def test_different_seeds_change_seeded_rank():
    c = candidate(7)
    assert _scene_rank(c, 8, "section", 0.5, selection_seed=1234, selection_variation=.3) != \
           _scene_rank(c, 8, "section", 0.5, selection_seed=5678, selection_variation=.3)


def test_analyze_and_serve_parse_selection_options():
    parser = build_parser()
    a = parser.parse_args(["analyze", "song.mp3", "--selection-seed", "42", "--selection-variation", ".5"])
    assert a.selection_seed == 42
    assert a.selection_variation == .5

    s = parser.parse_args(["serve", "timeline.json", "--replan-scenes", "--reshuffle"])
    assert s.replan_scenes is True
    assert s.reshuffle is True
