# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from tubeviz.youtube import DownloadFailure, SearchResult, YouTubeSource
from tubeviz.ingest import IngestConfig, _acceptable


def result(metadata):
    return SearchResult(
        source="youtube",
        source_id="abc",
        url="https://www.youtube.com/watch?v=abc",
        rank=1,
        metadata=metadata,
    )


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"is_live": True, "live_status": "is_live"}, "active live stream"),
        ({"live_status": "is_upcoming"}, "upcoming live stream"),
        ({"live_status": "post_live"}, "post-live"),
    ],
)
def test_live_sources_are_rejected_before_download(metadata, expected):
    ok, reason = _acceptable(result(metadata), IngestConfig())
    assert not ok
    assert expected in reason


def test_archived_live_vod_is_allowed_when_finite_http_format_exists():
    item = result({
        "was_live": True,
        "live_status": "was_live",
        "duration": 300,
        "formats": [
            {"protocol": "https", "format_id": "18"},
            {"protocol": "m3u8_native", "format_id": "96"},
        ],
    })
    ok, reason = _acceptable(item, IngestConfig())
    assert ok, reason


def test_archived_live_without_finite_vod_is_rejected():
    item = result({
        "was_live": True,
        "live_status": "was_live",
        "duration": 300,
        "formats": [{"protocol": "m3u8_native", "format_id": "96"}],
    })
    ok, reason = _acceptable(item, IngestConfig())
    assert not ok
    assert "finite" in reason


def test_download_has_independent_live_guard(tmp_path: Path):
    source = YouTubeSource()
    with pytest.raises(DownloadFailure) as exc:
        source.download(
            result({"is_live": True, "live_status": "is_live"}),
            tmp_path,
        )
    assert exc.value.status == "live_stream"


def test_default_formats_prefer_direct_http_and_exclude_dash_first():
    attempts = YouTubeSource.DEFAULT_FORMAT_ATTEMPTS
    assert "protocol^=http" in attempts[0]
    assert "protocol!*=dash" in attempts[0]


def test_base_options_bound_network_and_parallelize_fragments():
    source = YouTubeSource(
        socket_timeout=17,
        concurrent_fragments=6,
        retries=1,
        fragment_retries=2,
    )
    opts = source._base_options()
    assert opts["socket_timeout"] == 17
    assert opts["concurrent_fragment_downloads"] == 6
    assert opts["retries"] == 1
    assert opts["fragment_retries"] == 2
