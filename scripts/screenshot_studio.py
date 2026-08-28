#!/usr/bin/env python3

from argparse import ArgumentParser, Namespace
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


CANONICAL_TABS = ("project", "ingest", "library", "library-details", "timeline", "render", "jobs", "settings", "advanced")
TAB_ALIASES = {"create": "project", "ai": "settings", "command": "advanced"}
TABS = CANONICAL_TABS + tuple(TAB_ALIASES)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Capture deterministic tubeviz Studio screenshots with Playwright."
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="http://127.0.0.1:8090/",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path; defaults to screenshots/screenshot-<tab>.png (library-details -> screenshot-library-detail.png)",
    )
    parser.add_argument(
        "--tab",
        choices=TABS,
        default="project",
        help=(
            "Studio view to capture. 'library-details' opens a playable Library "
            "clip and captures its detail/trim modal."
        ),
    )
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument(
        "--ingest-mode",
        choices=("ai", "search", "urls"),
        default="ai",
        help="For --tab ingest, select which acquisition mode is visible.",
    )
    parser.add_argument(
        "--timeline-path",
        default=None,
        help="For --tab timeline, set the Studio Timeline path before capture.",
    )
    parser.add_argument(
        "--start-preview",
        action="store_true",
        help="For --tab timeline, start the embedded browser preview and wait for it before capture.",
    )
    parser.add_argument(
        "--clip-match",
        default=None,
        help=(
            "For --tab library-details, prefer the first playable clip whose title "
            "contains this text (case-insensitive)."
        ),
    )
    parser.add_argument(
        "--clip-index",
        type=int,
        default=0,
        help=(
            "For --tab library-details, zero-based index among matching playable "
            "clips (default: 0)."
        ),
    )
    parser.add_argument(
        "--clip-time",
        type=float,
        default=None,
        help=(
            "For --tab library-details, seek to this time in seconds before the "
            "capture. By default a representative early frame is chosen."
        ),
    )
    parser.add_argument(
        "--full-details",
        action="store_true",
        help=(
            "Deprecated compatibility flag. Library-detail screenshots now capture "
            "the full inspector by default."
        ),
    )
    parser.add_argument(
        "--viewport-details",
        action="store_true",
        help=(
            "For --tab library-details, capture the normal scrollable viewport "
            "instead of expanding the inspector to its complete height."
        ),
    )
    return parser


def install_screenshot_styles(page: Page) -> None:
    page.add_style_tag(
        content="""
            *,
            *::before,
            *::after {
                animation: none !important;
                transition: none !important;
                caret-color: transparent !important;
            }

            header {
                position: static !important;
            }

            .studio-tooltip {
                display: none !important;
            }

            .global-activity {
                display: none !important;
            }
        """
    )


def load_library(page: Page) -> None:
    page.locator("#loadClips").click()
    page.wait_for_function(
        """
        () => {
            const grid = document.querySelector('#clipGrid');
            if (!grid) return false;
            if (grid.querySelector('.clip')) return true;
            return !['', 'Loading…'].includes((grid.textContent || '').trim());
        }
        """,
        timeout=30_000,
    )
    if page.locator("#clipGrid .clip").count() == 0:
        message = page.locator("#clipGrid").inner_text().strip() or "No clips matched."
        raise SystemExit(f"Library has no clips to capture: {message}")


def warm_library_images(page: Page) -> None:
    page.evaluate(
        """
        async () => {
            const step = 700;
            for (
                let y = 0;
                y < document.documentElement.scrollHeight;
                y += step
            ) {
                window.scrollTo(0, y);
                await new Promise(resolve => setTimeout(resolve, 80));
            }
            window.scrollTo(0, 0);
        }
        """
    )
    page.wait_for_timeout(500)


def find_playable_clip(page: Page, *, match: str | None, index: int):
    if index < 0:
        raise SystemExit("--clip-index must be zero or greater")

    clips = page.locator("#clipGrid .clip")
    candidates = []
    requested = match.casefold() if match else None

    for position in range(clips.count()):
        clip = clips.nth(position)
        play = clip.get_by_role("button", name="Play / Trim", exact=True)
        if play.count() == 0 or not play.is_enabled():
            continue

        title = clip.locator(".clip-title").inner_text().strip()
        if requested and requested not in title.casefold():
            continue
        candidates.append((clip, play, title))

    if not candidates:
        if match:
            raise SystemExit(
                f"No playable Library clip title contains {match!r}. "
                "Try a different --clip-match or omit it."
            )
        raise SystemExit("No playable Library clips are available for a detail screenshot.")

    if index >= len(candidates):
        qualifier = f" matching {match!r}" if match else ""
        raise SystemExit(
            f"--clip-index {index} is out of range: found {len(candidates)} "
            f"playable clip(s){qualifier}."
        )

    return candidates[index]


def open_library_details(page: Page, args: Namespace) -> str:
    _, play_button, title = find_playable_clip(
        page,
        match=args.clip_match,
        index=args.clip_index,
    )
    play_button.click()

    modal = page.locator("#videoModal")
    modal.wait_for(state="visible", timeout=30_000)
    page.locator("#videoModal .trim-editor").wait_for(state="visible", timeout=30_000)

    # Wait for the detail API + video metadata to initialize the trim editor. If a
    # browser codec cannot expose metadata quickly, the modal is still useful, so
    # fall through after the timeout rather than making screenshot generation brittle.
    try:
        page.wait_for_function(
            """
            () => {
                const status = document.querySelector('#trimStatus');
                if (!status) return false;
                const text = status.textContent || '';
                return text && text !== 'Loading clip…';
            }
            """,
            timeout=15_000,
        )
    except Exception:
        pass

    # Freeze playback on a useful frame. The editor itself initially seeks to the
    # In point, which is often a title card; an early interior frame is generally a
    # better documentation screenshot. --clip-time remains available for exactness.
    page.evaluate(
        """
        async requestedTime => {
            const video = document.querySelector('#modalVideo');
            if (!video) return;
            video.pause();

            if (!Number.isFinite(video.duration) || video.duration <= 0) return;
            let target;
            if (Number.isFinite(requestedTime)) {
                target = requestedTime;
            } else {
                target = Math.min(30, Math.max(0.5, video.duration * 0.15));
            }
            target = Math.max(0, Math.min(video.duration - 0.05, target));
            if (Math.abs(video.currentTime - target) < 0.03) return;

            await new Promise(resolve => {
                const done = () => {
                    video.removeEventListener('seeked', done);
                    resolve();
                };
                video.addEventListener('seeked', done, {once: true});
                video.currentTime = target;
                setTimeout(done, 2000);
            });
        }
        """,
        args.clip_time,
    )
    page.wait_for_timeout(250)

    if not args.viewport_details:
        expand_library_details(page)

    return title


def expand_library_details(page: Page) -> None:
    """Turn the scrollable inspector into normal-flow content for a full capture.

    A Playwright ``full_page`` screenshot only follows document scroll height. The
    Studio modal is normally ``position: fixed`` and its ``.trim-modal`` child owns
    an internal scrollbar, so simply asking Playwright for a full-page image still
    clips the lower AI metadata. For documentation capture we temporarily hide the
    underlying Studio chrome, put the overlay back into document flow, and remove
    the inspector's max-height/overflow constraints. The modal then contributes its
    complete height to the document and a full-page screenshot contains every detail.
    """
    page.add_style_tag(
        content="""
            html,
            body {
                height: auto !important;
                min-height: 0 !important;
                overflow: visible !important;
            }

            body > header,
            body > nav,
            body > main {
                display: none !important;
            }

            #videoModal {
                position: relative !important;
                inset: auto !important;
                width: 100% !important;
                min-height: 0 !important;
                height: auto !important;
                display: grid !important;
                place-items: start center !important;
                overflow: visible !important;
                padding: 20px !important;
                background: #000 !important;
            }

            #videoModal .trim-modal {
                max-height: none !important;
                height: auto !important;
                overflow: visible !important;
                margin: 0 !important;
            }

            #videoModal .trim-modal video {
                max-height: 620px !important;
                object-fit: contain !important;
            }

            #videoModal .clip-ai-panel,
            #videoModal .clip-ai-grid,
            #videoModal .ai-scenes {
                max-height: none !important;
                overflow: visible !important;
            }
        """
    )
    page.wait_for_timeout(150)

    # Force layout once before capture. This also catches future modal CSS changes
    # that accidentally reintroduce an internal scrolling box.
    dimensions = page.locator("#videoModal .trim-modal").evaluate(
        """
        element => ({
            clientHeight: element.clientHeight,
            scrollHeight: element.scrollHeight,
            documentHeight: document.documentElement.scrollHeight
        })
        """
    )
    if dimensions["clientHeight"] + 2 < dimensions["scrollHeight"]:
        raise RuntimeError(
            "Library detail inspector is still internally clipped after expansion: "
            f"clientHeight={dimensions['clientHeight']}, "
            f"scrollHeight={dimensions['scrollHeight']}"
        )


def prepare_timeline(page: Page, args: Namespace) -> None:
    """Prepare the Timeline tab without making screenshots depend on a preview by default."""
    if args.timeline_path:
        page.locator("#timelinePath").fill(args.timeline_path)

    timeline_path = page.locator("#timelinePath").input_value().strip()
    if timeline_path:
        page.locator("#refreshTimeline").click()
        try:
            page.wait_for_function(
                """
                () => {
                    const status = document.querySelector('#timelineStatus');
                    if (!status) return false;
                    const text = (status.textContent || '').trim();
                    return text && !text.startsWith('Loading ');
                }
                """,
                timeout=20_000,
            )
        except Exception:
            pass

    if args.start_preview:
        if not timeline_path:
            raise SystemExit("--start-preview requires --timeline-path or a populated Studio Timeline field")
        page.locator("#previewBtn").click()
        page.locator("#timelinePreviewShell.ready").wait_for(state="visible", timeout=30_000)
        frame = page.locator("#timelinePreviewFrame")
        try:
            frame.wait_for(state="visible", timeout=10_000)
            page.wait_for_timeout(1200)
        except Exception:
            pass


def main() -> None:
    args = build_parser().parse_args()
    default_tab_name = "library-detail" if args.tab == "library-details" else args.tab
    output = Path(
        args.output or f"screenshots/screenshot-{default_tab_name}.png"
    ).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=1,
        )

        page.goto(args.url, wait_until="networkidle")

        requested_tab = args.tab
        ui_tab = "library" if requested_tab == "library-details" else TAB_ALIASES.get(requested_tab, requested_tab)
        page.locator(f'.tab[data-tab="{ui_tab}"]').click()
        page.locator(f"#{ui_tab}.panel.active").wait_for()

        if ui_tab == "advanced":
            page.locator("#advanced .command-card").wait_for(state="visible")
            try:
                page.wait_for_function(
                    "() => (document.querySelector('#cliArguments')?.children.length || 0) > 0",
                    timeout=10_000,
                )
            except Exception:
                pass
        elif ui_tab == "ingest":
            page.locator(f'.ingest-mode-button[data-ingest-mode="{args.ingest_mode}"]').click()
            page.wait_for_timeout(100)

        install_screenshot_styles(page)

        if args.tab in {"library", "library-details"}:
            load_library(page)
        elif args.tab == "timeline":
            prepare_timeline(page, args)

        if args.tab == "library":
            warm_library_images(page)
        elif args.tab == "library-details":
            title = open_library_details(page, args)
            print(f"library detail clip: {title}")

        page.screenshot(
            path=str(output),
            full_page=(args.tab != "library-details" or not args.viewport_details),
            animations="disabled",
        )

        if args.tab == "timeline" and args.start_preview:
            # This helper owns the preview serve job it launched. Shut it down
            # after capture so screenshot automation never leaves a server behind.
            try:
                page.evaluate(
                    "async () => { if (typeof stopTimelinePreviewJob === 'function') await stopTimelinePreviewJob(); }"
                )
                page.wait_for_timeout(150)
            except Exception:
                pass

        browser.close()

    print(output)


if __name__ == "__main__":
    main()
