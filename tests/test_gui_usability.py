# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from tubeviz import __version__


def _static(name: str) -> str:
    return (Path(__file__).parents[1] / "src" / "tubeviz" / "static" / name).read_text()


def test_hf_token_reveal_is_bound_before_async_init_and_env_secret_stays_hidden():
    js = _static("gui.js")
    html = _static("gui.html")
    assert 'bindCredentialToggle();' in js
    assert js.index('bindCredentialToggle();') < js.index('init().catch')
    assert 'input.type===\"text\"' in js
    assert 'Show typed token' in html
    assert 'server-side <code>HF_TOKEN</code> value is never sent to the browser' in html
    assert 'hf_token_configured' in js
    assert 'saved secrets are never returned' not in js  # status uses booleans, never values


def test_manual_url_ingest_has_full_editor_and_collapsible_advanced_controls():
    html = _static("gui.html")
    css = _static("gui.css")
    assert 'class="url-editor"' in html
    assert 'id="manualUrlCount"' in html
    assert 'id="clearManualUrls"' in html
    assert '<summary>Advanced ingest settings</summary>' in html
    assert '.manual-card{grid-column:1/-1!important' in css
    assert '.url-editor textarea{min-height:168px!important' in css


def test_every_static_form_control_gets_contextual_help_and_cli_help_is_inherited():
    js = _static("gui.js")
    css = _static("gui.css")
    assert 'function installHelp(root=document)' in js
    assert 'root.querySelectorAll("input,select,textarea,button")' in js
    assert 'const help=cliHelp(arg)||' in js
    assert 'addHelpToControl(el,wrap?.dataset.help||null)' in js
    assert '.studio-tooltip{position:fixed' in css

def test_studio_assets_are_versioned_and_version_visible():
    html = _static("gui.html")
    assert f"gui.css?v={__version__}" in html
    assert f"gui.js?v={__version__}" in html
    assert 'id="studioVersion"' in html


def test_help_tooltip_uses_body_portal():
    js = (Path(__file__).parents[1] / "src/tubeviz/static/gui.js").read_text()
    css = (Path(__file__).parents[1] / "src/tubeviz/static/gui.css").read_text()
    assert 'document.body.appendChild(tip)' in js
    assert 'position:fixed' in css
    assert '.studio-tooltip' in css
    assert 'z-index:2147483000' in css
    assert 'positionStudioTooltip' in js
    assert 'window.innerWidth' in js
    assert 'window.innerHeight' in js


def test_live_job_logs_only_auto_follow_when_user_is_at_bottom():
    js = _static("gui.js")
    assert 'function updateLiveLog(element, lines, {forceFollow=false}={})' in js
    assert 'const distanceFromBottom=element.scrollHeight-element.clientHeight-element.scrollTop;' in js
    assert 'if(wasFollowing)element.scrollTop=element.scrollHeight;' in js
    assert 'else element.scrollTop=previousScrollTop;' in js
    assert '?tail=4000' in js
    assert '$("jobLog").scrollTop=$("jobLog").scrollHeight' not in js
    assert '$("commandJobLog").scrollTop=$("commandJobLog").scrollHeight' not in js


def test_clip_trim_editor_is_directly_below_video_before_ai_metadata():
    html = _static("gui.html")
    video = html.index('<video id="modalVideo"')
    trim = html.index('<div class="trim-editor">')
    ai = html.index('<section id="clipAiMetadata"')
    assert video < trim < ai



def test_library_card_actions_do_not_embed_clip_text_in_inline_handlers():
    js = _static("gui.js")
    assert 'data-clip-action="play"' in js
    assert 'data-clip-action="reject"' in js
    assert 'data-clip-action="edit-tags"' in js
    assert 'data-clip-action="delete"' in js
    assert 'button[data-clip-action]' in js
    assert 'playClip(clip.source_id,clip.source,clip.title||clip.source_id)' in js
    assert 'onclick="playClip(' not in js
    assert 'onclick="rejectClip(' not in js
    assert 'onclick="restoreClip(' not in js
    assert 'onclick="editClipTags(' not in js
    assert 'onclick="deleteClip(' not in js
