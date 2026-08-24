# SPDX-License-Identifier: Apache-2.0
from tubeviz.cli import build_parser


def test_ingest_url_parser_accepts_multiple_urls_and_manual_defaults():
    args = build_parser().parse_args([
        "ingest-url",
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/def456",
        "--library", "/tmp/library",
    ])
    assert args.urls == [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/def456",
    ]
    assert args.term == "manual"
    assert args.hard_max_duration == 0.0
    assert args.library == "/tmp/library"
