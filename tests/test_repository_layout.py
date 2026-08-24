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
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text
    assert Path("NOTICE").is_file()


def test_readme_screenshot_stays_first():
    assert Path("README.md").read_text().startswith("![tubeviz screenshot](screenshot.png)\n")
