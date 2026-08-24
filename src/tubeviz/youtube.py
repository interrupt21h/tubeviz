# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any


def _yt_dlp():
    return import_module("yt_dlp")


@dataclass(frozen=True)
class SearchResult:
    source: str
    source_id: str
    url: str
    rank: int
    metadata: dict[str, Any]


class DownloadFailure(RuntimeError):
    """A download failure classified for persistent library status."""

    def __init__(self, message: str, *, status: str = "download_error"):
        super().__init__(message)
        self.status = status


class QuietLogger:
    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


def classify_download_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if "403" in text and "forbidden" in text:
        return "blocked_403"
    if any(token in text for token in ("private video", "video is private")):
        return "private"
    if any(token in text for token in ("video unavailable", "this video is unavailable", "not available")):
        return "unavailable"
    if any(token in text for token in ("sign in to confirm your age", "age-restricted", "age restricted")):
        return "auth_required"
    return "download_error"


class YouTubeSource:
    source_name = "youtube"

    # A format URL can fail while another selected format remains usable. These
    # are intentionally ordinary yt-dlp format selectors, not site-specific URL
    # manipulation. If YouTube requires a PO token, all attempts may still 403;
    # tubeviz records that explicitly and continues filling the term quota.
    # Prefer finite direct HTTP/HTTPS media. This mirrors yt-dlp's documented
    # recommendation for preferring direct links over HLS/DASH manifests.
    # Live HLS is rejected separately before any download starts.
    DEFAULT_FORMAT_ATTEMPTS = (
        "(bv*+ba/b)[protocol^=http][protocol!*=dash]",
        "(bv*+ba/b)[protocol^=http]",
        "b[ext=mp4][protocol^=http][protocol!*=dash]",
    )

    LIVE_STATUSES = {"is_live", "is_upcoming", "post_live"}
    FINITE_PROTOCOLS = {"http", "https", "http_dash_segments"}

    def __init__(
        self,
        *,
        quiet: bool = True,
        cookies_from_browser: str | None = None,
        format_attempts: tuple[str, ...] | None = None,
        socket_timeout: float = 20.0,
        concurrent_fragments: int = 4,
        retries: int = 2,
        fragment_retries: int = 2,
    ):
        self.quiet = quiet
        self.cookies_from_browser = cookies_from_browser
        self.format_attempts = format_attempts or self.DEFAULT_FORMAT_ATTEMPTS
        self.socket_timeout = max(1.0, float(socket_timeout))
        self.concurrent_fragments = max(1, int(concurrent_fragments))
        self.retries = max(0, int(retries))
        self.fragment_retries = max(0, int(fragment_retries))

    def _base_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noplaylist": True,
            "retries": self.retries,
            "fragment_retries": self.fragment_retries,
            "extractor_retries": self.retries,
            "file_access_retries": 2,
            "socket_timeout": self.socket_timeout,
            "concurrent_fragment_downloads": self.concurrent_fragments,
            # Never opt into downloading a live stream from its beginning.
            "live_from_start": False,
        }
        if self.quiet:
            options["logger"] = QuietLogger()
        if self.cookies_from_browser:
            options["cookiesfrombrowser"] = (self.cookies_from_browser,)
        return options

    @classmethod
    def live_rejection_reason(cls, metadata: dict[str, Any]) -> str | None:
        """Return a reason when metadata represents an active/non-final live source.

        `was_live` is intentionally allowed: once YouTube has produced a normal
        VOD, archived live footage can be useful. `post_live` is rejected because
        yt-dlp documents it as a live source whose VOD is not yet processed.
        """
        live_status = str(metadata.get("live_status") or "").strip().lower()
        if metadata.get("is_live") is True or live_status == "is_live":
            return "active live stream"
        if live_status == "is_upcoming":
            return "upcoming live stream"
        if live_status == "post_live":
            return "post-live video is not yet processed as VOD"
        return None

    @classmethod
    def has_finite_vod_format(cls, metadata: dict[str, Any]) -> bool:
        """Whether yt-dlp metadata exposes a finite HTTP-ish media representation."""
        formats = metadata.get("formats") or []
        if not formats:
            # Flat search metadata often lacks formats. Defer the decision until
            # hydrated metadata is available.
            return True
        for fmt in formats:
            if not isinstance(fmt, dict):
                continue
            protocol = str(fmt.get("protocol") or "").lower()
            if protocol in cls.FINITE_PROTOCOLS:
                # Reject formats explicitly marked incomplete by extractors.
                if fmt.get("is_from_start") is False and metadata.get("live_status") == "was_live":
                    continue
                return True
        return False

    def search(self, term: str, limit: int) -> list[SearchResult]:
        options = self._base_options() | {
            "extract_flat": True,
            "skip_download": True,
        }
        with _yt_dlp().YoutubeDL(options) as ydl:
            raw = ydl.extract_info(f"ytsearch{limit}:{term}", download=False)
            data = ydl.sanitize_info(raw)

        entries = data.get("entries") or []
        results: list[SearchResult] = []
        for rank, entry in enumerate(entries, start=1):
            if not entry:
                continue
            source_id = str(entry.get("id") or "").strip()
            if not source_id:
                continue
            url = entry.get("webpage_url") or entry.get("url")
            if not url or not str(url).startswith(("http://", "https://")):
                url = f"https://www.youtube.com/watch?v={source_id}"
            results.append(
                SearchResult(
                    source=self.source_name,
                    source_id=source_id,
                    url=str(url),
                    rank=rank,
                    metadata=dict(entry),
                )
            )
        return results

    def resolve_url(self, url: str, *, rank: int = 1) -> SearchResult:
        """Resolve a manually supplied YouTube URL into a normal SearchResult.

        Uses yt-dlp extraction rather than parsing YouTube URL shapes ourselves, so
        youtu.be, watch, shorts, and other extractor-supported single-video URLs
        follow the same metadata/download path as discovered candidates.
        """
        value = str(url).strip()
        if not value.startswith(("http://", "https://")):
            raise DownloadFailure(f"expected an http(s) video URL, got: {url!r}", status="metadata_error")
        options = self._base_options() | {"skip_download": True, "noplaylist": True}
        try:
            with _yt_dlp().YoutubeDL(options) as ydl:
                raw = ydl.extract_info(value, download=False)
                metadata = ydl.sanitize_info(raw)
        except Exception as exc:
            raise DownloadFailure(str(exc), status="metadata_error") from exc
        if not isinstance(metadata, dict):
            raise DownloadFailure("yt-dlp did not return video metadata", status="metadata_error")
        source_id = str(metadata.get("id") or "").strip()
        if not source_id:
            raise DownloadFailure("yt-dlp metadata has no video id", status="metadata_error")
        webpage_url = str(metadata.get("webpage_url") or value)
        return SearchResult(
            source=self.source_name,
            source_id=source_id,
            url=webpage_url,
            rank=max(1, int(rank)),
            metadata=dict(metadata),
        )

    def hydrate(self, result: SearchResult) -> SearchResult:
        options = self._base_options() | {"skip_download": True}
        try:
            with _yt_dlp().YoutubeDL(options) as ydl:
                raw = ydl.extract_info(result.url, download=False)
                metadata = ydl.sanitize_info(raw)
        except Exception as exc:
            raise DownloadFailure(str(exc), status="metadata_error") from exc
        hydrated_metadata = dict(metadata)
        # Preserve pre-download AI discovery/ranking provenance across hydration.
        for key, value in result.metadata.items():
            if str(key).startswith("_tubeviz_"):
                hydrated_metadata[key] = value
        return SearchResult(
            source=result.source,
            source_id=result.source_id,
            url=str(metadata.get("webpage_url") or result.url),
            rank=result.rank,
            metadata=hydrated_metadata,
        )

    def download(self, result: SearchResult, originals_dir: Path) -> tuple[Path, Path | None, dict[str, Any]]:
        reason = self.live_rejection_reason(result.metadata)
        if reason:
            raise DownloadFailure(reason, status="live_stream")
        if not self.has_finite_vod_format(result.metadata):
            raise DownloadFailure(
                "no finite HTTP/HTTPS VOD format is available; refusing HLS/live-manifest download",
                status="no_finite_format",
            )

        originals_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(originals_dir / "%(id)s.%(ext)s")
        errors: list[str] = []
        last_status = "download_error"

        # A partially successful previous attempt may already have produced a
        # complete media file. Reuse it before issuing another request.
        existing = self._find_downloaded_media(originals_dir, result.source_id, required=False)
        if existing is not None:
            info_json = originals_dir / f"{result.source_id}.info.json"
            return existing, info_json if info_json.exists() else None, result.metadata

        for attempt_no, format_selector in enumerate(self.format_attempts, start=1):
            options = self._base_options() | {
                "format": format_selector,
                "merge_output_format": "mp4",
                "outtmpl": {"default": output_template},
                "writeinfojson": True,
                "writethumbnail": False,
                "restrictfilenames": True,
                "overwrites": False,
                "continuedl": True,
            }
            try:
                with _yt_dlp().YoutubeDL(options) as ydl:
                    raw = ydl.extract_info(result.url, download=True)
                    metadata = ydl.sanitize_info(raw)
                media = self._find_downloaded_media(originals_dir, result.source_id)
                info_json = originals_dir / f"{result.source_id}.info.json"
                return media, info_json if info_json.exists() else None, dict(metadata)
            except Exception as exc:
                last_status = classify_download_error(exc)
                errors.append(f"attempt {attempt_no} format={format_selector!r}: {exc}")
                self._cleanup_partial_files(originals_dir, result.source_id)
                # A failed merge/metadata write can occur after media completion.
                media = self._find_downloaded_media(originals_dir, result.source_id, required=False)
                if media is not None and media.stat().st_size > 0:
                    info_json = originals_dir / f"{result.source_id}.info.json"
                    return media, info_json if info_json.exists() else None, result.metadata

        self._cleanup_partial_files(originals_dir, result.source_id)
        raise DownloadFailure("; ".join(errors), status=last_status)

    @staticmethod
    def _cleanup_partial_files(directory: Path, source_id: str) -> None:
        for path in directory.glob(f"{source_id}*.part*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        for path in directory.glob(f"{source_id}*.ytdl"):
            if path.is_file():
                path.unlink(missing_ok=True)

    @staticmethod
    def _find_downloaded_media(directory: Path, source_id: str, *, required: bool = True) -> Path | None:
        rejected_suffixes = {
            ".json", ".part", ".ytdl", ".description", ".vtt", ".srt", ".jpg", ".jpeg", ".png", ".webp"
        }
        matches = [
            path for path in directory.glob(f"{source_id}.*")
            if path.is_file()
            and not path.name.endswith(".info.json")
            and path.suffix.lower() not in rejected_suffixes
        ]
        if not matches:
            if required:
                raise FileNotFoundError(f"yt-dlp completed but no media file was found for {source_id}")
            return None
        return max(matches, key=lambda path: path.stat().st_size)
