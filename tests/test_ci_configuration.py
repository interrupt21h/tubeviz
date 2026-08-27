from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_uses_canonical_clone_url() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "git clone https://github.com/interrupt21h/tubeviz.git tubeviz" in readme
    assert "git clone <repo-url>" not in readme


def test_project_metadata_uses_canonical_repository_urls() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'Repository = "https://github.com/interrupt21h/tubeviz.git"' in pyproject
    assert 'Issues = "https://github.com/interrupt21h/tubeviz/issues"' in pyproject


def test_github_ci_covers_supported_python_and_native_build() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for version in ("3.11", "3.12", "3.13", "3.14"):
        assert f'- "{version}"' in workflow
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert "python -m pytest" in workflow
    assert "python -m build" in workflow
    assert "python -m twine check dist/*" in workflow
    assert "node --check src/tubeviz/static/gui.js" in workflow
    assert "cmake --build build/native" in workflow
    assert "tubeviz-native-render --version" in workflow
