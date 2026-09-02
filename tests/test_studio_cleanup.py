# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_studio_cleanup_assets_load_after_primary_gui_assets():
    html = Path("src/tubeviz/static/gui.html").read_text()
    assert "/static/studio_cleanup.css" in html
    assert "/static/studio_cleanup.js" in html
    assert html.index("/static/gui.js") < html.index("/static/studio_cleanup.js")


def test_studio_cleanup_preserves_controls_while_grouping_expert_tuning():
    js = Path("src/tubeviz/static/studio_cleanup.js").read_text()
    for heading in (
        "Creative look",
        "Edit intelligence",
        "Creative detail",
        "AI direction & models",
        "Experimental / glitch",
        "Discovery quality & filtering",
        "Ingest automation",
    ):
        assert heading in js
    for control_id in (
        "analysisPreset",
        "compositionIntensity",
        "creativeIntensity",
        "codecGlitch",
        "aiDirectorStrength",
        "minVideoFitness",
        "targetClips",
    ):
        # analysisPreset remains in existing markup; all moved controls retain IDs.
        assert control_id in (js + Path("src/tubeviz/static/gui.html").read_text())
    assert "cloneNode" not in js
    assert "controlNode(id)" in js


def test_studio_cleanup_has_responsive_compact_hierarchy():
    css = Path("src/tubeviz/static/studio_cleanup.css").read_text()
    assert ".studio-essential-grid" in css
    assert ".studio-control-group" in css
    assert ".utility-start" in css
    assert "@media (max-width: 700px)" in css
