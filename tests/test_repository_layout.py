# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_native_source_has_single_canonical_tree():
    assert Path("src/tubeviz/native_src/CMakeLists.txt").is_file()
    assert not Path("native").exists()


def test_repository_has_apache_license_metadata():
    pyproject = Path("pyproject.toml").read_text()
    license_text = Path("LICENSE").read_text()
    assert 'license = "Apache-2.0"' in pyproject
    assert 'license-files = ["LICENSE", "NOTICE"]' in pyproject
    assert '"nnaudio==0.3.4"' in pyproject
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text
    assert Path("NOTICE").is_file()


def test_readme_uses_render_output_as_hero():
    text = Path("README.md").read_text()
    assert text.startswith("# tubeviz\n")
    assert "![tubeviz demo — Dream](dream.webp)" in text.split("## Sample videos", 1)[0]
    assert "![tubeviz Studio — Project](screenshots/screenshot-project.png)" in text


def test_readme_tab_screenshots_live_in_screenshots_directory():
    readme = Path("README.md").read_text()
    names = [
        "screenshot-project.png",
        "screenshot-ingest.png",
        "screenshot-library-cropped.png",
        "screenshot-library-detail.png",
        "screenshot-timeline-example.png",
        "screenshot-render.png",
        "screenshot-jobs.png",
        "screenshot-settings.png",
        "screenshot-advanced.png",
    ]
    for name in names:
        path = Path("screenshots") / name
        assert path.is_file()
        assert f"screenshots/{name}" in readme
    assert "![tubeviz screenshot](screenshot.png)" not in readme


def test_screenshot_helper_supports_library_item_details():
    script = Path("scripts/screenshot_studio.py").read_text()
    readme = Path("README.md").read_text()
    assert '"library-details"' in script
    assert '"--clip-match"' in script
    assert '"--clip-index"' in script
    assert '"--clip-time"' in script
    assert '"--full-details"' in script
    assert '"--viewport-details"' in script
    assert 'if not args.viewport_details:' in script
    assert 'body > main' in script
    assert 'max-height: none !important' in script
    assert 'dimensions["clientHeight"] + 2 < dimensions["scrollHeight"]' in script
    assert "screenshots/screenshot-library-detail.png" in readme
