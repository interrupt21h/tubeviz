#!/usr/bin/env python3

from argparse import ArgumentParser
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument(
        "url",
        nargs="?",
        default="http://127.0.0.1:8090/",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path; defaults to screenshots/screenshot-<tab>.png",
    )
    parser.add_argument(
        "--tab",
        choices=("create", "library", "command", "jobs", "ai"),
        default="create",
    )
    parser.add_argument("--width", type=int, default=1920)
    args = parser.parse_args()

    output = Path(args.output or f"screenshots/screenshot-{args.tab}.png").expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": args.width, "height": 1080},
            device_scale_factor=1,
        )

        page.goto(args.url, wait_until="networkidle")

        page.locator(f'.tab[data-tab="{args.tab}"]').click()
        page.locator(f"#{args.tab}.panel.active").wait_for()

        # Disable animation, sticky positioning, and focused help bubbles.
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
            """
        )

        # Trigger lazy-loaded images before capturing the Library.
        if args.tab == "library":
            page.locator("#loadClips").click()
            page.locator("#clipGrid .clip").first.wait_for(timeout=30_000)

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

        page.screenshot(
            path=str(output),
            full_page=True,
            animations="disabled",
        )

        browser.close()

    print(output)


if __name__ == "__main__":
    main()
