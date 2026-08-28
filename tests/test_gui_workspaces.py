# SPDX-License-Identifier: Apache-2.0
import re
from pathlib import Path


def _static(name: str) -> str:
    return (Path(__file__).parents[1] / "src" / "tubeviz" / "static" / name).read_text(encoding="utf-8")


def test_studio_top_level_workflow_is_focused_and_unified():
    html = _static("gui.html")
    expected = ["project", "ingest", "library", "timeline", "render", "jobs", "settings", "advanced"]
    positions = [html.index(f'data-tab="{tab}"') for tab in expected]
    assert positions == sorted(positions)
    assert 'data-tab="create"' not in html
    assert 'data-tab="command"' not in html
    assert 'data-tab="ai"' not in html
    assert 'id="projectContextBar"' in html
    assert 'id="ingestWorkspace"' in html
    assert 'data-ingest-mode="ai"' in html
    assert 'data-ingest-mode="search"' in html
    assert 'data-ingest-mode="urls"' in html


def test_command_center_is_a_separate_advanced_workspace():
    html = _static("gui.html")
    settings = html.split('<section id="settings" class="panel">', 1)[1].split('<section id="advanced" class="panel">', 1)[0]
    advanced = html.split('<section id="advanced" class="panel">', 1)[1].split('</main>', 1)[0]
    assert 'settingsAdvancedTools' not in html
    assert 'command-card' not in settings
    assert 'command-card' in advanced
    assert '<h2>Advanced</h2>' in advanced
    assert 'runCliCommand' in advanced


def test_legacy_numeric_card_kicker_prefixes_are_removed():
    html = _static("gui.html")
    kickers = re.findall(r'<div class="card-kicker">(.*?)</div>', html, flags=re.S)
    assert kickers
    assert not [value for value in kickers if re.match(r'\s*\d{1,2}[A-Z]?\s*(?:[·:—–-]|$)', value)]


def test_project_no_longer_contains_ingest_render_or_terminal_output():
    html = _static("gui.html")
    project = html.split('<section id="project" class="panel active">', 1)[1].split('<section id="ingest"', 1)[0]
    assert 'id="libraryPath"' in project
    assert 'id="audioPath"' in project
    assert 'id="timelinePath"' in project
    assert 'id="outputPath"' in project
    assert 'id="ingestBtn"' not in project
    assert 'id="manualIngestBtn"' not in project
    assert 'id="renderBtn"' not in project
    assert 'id="jobLog"' not in project
    assert 'id="jobProgress"' not in project


def test_global_activity_and_jobs_are_the_only_visible_job_output_surfaces():
    html = _static("gui.html")
    js = _static("gui.js")
    css = _static("gui.css")
    assert 'id="globalActivity"' in html
    assert 'id="activityBar"' in html
    assert 'id="activityJobs"' in html
    assert 'id="jobDetail"' in html
    assert 'class="job-detail-log"' in js
    assert 'function renderGlobalActivity(job' in js
    assert 'function loadJobDetail(id' in js
    assert '.global-activity{' in css
    assert '.jobs-workspace{' in css


def test_zoom_help_icon_has_explicit_square_geometry():
    css = _static("gui.css")
    assert 'flex:0 0 16px!important' in css
    assert 'aspect-ratio:1!important' in css
    assert '.timeline-zoom-label{display:flex!important' in css


def test_screenshot_script_supports_advanced_tab_and_compatibility_aliases():
    script = (Path(__file__).parents[1] / "scripts" / "screenshot_studio.py").read_text(encoding="utf-8")
    for tab in ("project", "ingest", "library", "timeline", "render", "jobs", "settings", "advanced"):
        assert f'"{tab}"' in script
    assert 'TAB_ALIASES' in script
    assert '"create": "project"' in script
    assert '"ai": "settings"' in script
    assert '"command": "advanced"' in script
    assert '#advanced .command-card' in script
    assert '--ingest-mode' in script


def test_running_job_log_preserves_manual_scroll_position():
    js = _static("gui.js")
    css = _static("gui.css")
    assert 'const previousLog=detail.querySelector(".job-detail-log")' in js
    assert 'const previousLogWasAtBottom=' in js
    assert 'if(previousLogWasAtBottom)nextLog.scrollTop=nextLog.scrollHeight' in js
    assert 'else nextLog.scrollTop=Math.min(previousLogScrollTop' in js
    assert 'overscroll-behavior:contain' in css
    assert 'scrollbar-gutter:stable' in css
