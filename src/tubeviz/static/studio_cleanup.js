// SPDX-License-Identifier: Apache-2.0
// Progressive Studio hierarchy cleanup.  Existing controls are moved, never
// cloned or renamed, so gui.js listeners and CLI parity remain intact.
(() => {
  'use strict';

  function controlNode(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    return el.closest('label') || el;
  }

  function moveControls(parent, ids) {
    for (const id of ids) {
      const node = controlNode(id);
      if (node && !parent.contains(node)) parent.appendChild(node);
    }
  }

  function detailsGroup(title, note, className = '') {
    const details = document.createElement('details');
    details.className = `studio-control-group ${className}`.trim();
    const summary = document.createElement('summary');
    const heading = document.createElement('span');
    heading.textContent = title;
    const copy = document.createElement('small');
    copy.textContent = note;
    summary.append(heading, copy);
    const body = document.createElement('div');
    body.className = 'studio-control-group-body';
    details.append(summary, body);
    return {details, body};
  }

  function cleanupNavigation() {
    const nav = document.querySelector('body > nav');
    if (!nav) return;
    for (const button of nav.querySelectorAll('.tab')) {
      const tab = button.dataset.tab;
      button.classList.add(['project','ingest','library','timeline','render'].includes(tab) ? 'workflow-tab' : 'utility-tab');
      if (tab === 'jobs') button.classList.add('utility-start');
    }
  }

  function cleanupAnalyze() {
    const card = document.querySelector('#timelineAnalysisDetails .analyze-card');
    if (!card || card.dataset.cleanedUp === '1') return;
    card.dataset.cleanedUp = '1';
    const oldGrid = card.querySelector(':scope > .grid.two.tight');
    const preset = card.querySelector('.analysis-preset-panel');
    if (!oldGrid || !preset) return;

    const intro = document.createElement('div');
    intro.className = 'studio-primary-controls';
    intro.innerHTML = '<div class="studio-control-heading"><b>Creative look</b><span>The controls that most change what the edit feels like.</span></div>';
    const essential = document.createElement('div');
    essential.className = 'studio-essential-grid';
    intro.appendChild(essential);
    moveControls(essential, ['sectionBars','maxLayers','transformIntensity','creativeIntensity','compositionIntensity','minShot','maxShot']);
    preset.after(intro);

    const toggles = document.createElement('div');
    toggles.className = 'studio-essential-toggles';
    moveControls(toggles, ['dynamicShots','choreography','rhythmAlignment','creativeEffects','vectorEffects','reshuffle']);
    intro.appendChild(toggles);

    const fine = document.createElement('div');
    fine.className = 'studio-fine-controls';
    intro.after(fine);

    const edit = detailsGroup('Edit intelligence', 'Scene variety, transitions, lookahead, trajectory, and source reuse.');
    moveControls(edit.body, ['compositionDiversity','targetUnique','noveltyWeight','visualMatchWeight','transitionWeight','trajectoryStrength','anticipationSeconds','sequenceLookahead','sequenceBeamWidth','effectCompatibilityWeight','preferenceWeight','maxExcerpt','preferenceLearning']);
    fine.appendChild(edit.details);

    const creative = detailsGroup('Creative detail', 'Density, temporal memory, hero moments, and vector strength.');
    moveControls(creative.body, ['effectDensity','temporalPersistence','heroFrequency','vectorIntensity']);
    fine.appendChild(creative.details);

    const ai = detailsGroup('AI direction & models', 'Semantic/audio models and optional LLM direction.');
    moveControls(ai.body, ['semanticDevice','audioAiDevice','musicAiDevice','musicAiModel','audioVisualWeight','audioAiWindow','audioAiHop','aiDirectorStrength','aiConsultantCandidates','aiConsultantWeight','semantic','audioAi','musicAi','aiDirector','aiEditConsultant']);
    const aiNote = card.querySelector('.ai-inherit-note');
    if (aiNote) ai.body.appendChild(aiNote);
    for (const id of ['audioAiDoctorBtn','musicAiDoctorBtn']) {
      const button = document.getElementById(id);
      if (button) ai.body.appendChild(button);
    }
    fine.appendChild(ai.details);

    const glitch = detailsGroup('Experimental / glitch', 'Codec corruption stays opt-in; use it as punctuation rather than a base look.', 'studio-experimental-group');
    moveControls(glitch.body, ['codecGlitch','codecGlitchIntensity','codecPreviewMaterialize']);
    fine.appendChild(glitch.details);

    if (!oldGrid.children.length) oldGrid.hidden = true;
    const actionRow = card.querySelector(':scope > .actions');
    if (actionRow) actionRow.classList.add('studio-primary-action');
  }

  function cleanupIngest() {
    const card = document.querySelector('.ingest-source-card');
    if (!card || card.dataset.cleanedUp === '1') return;
    card.dataset.cleanedUp = '1';
    const grid = card.querySelector(':scope > .grid.two.tight');
    const brief = document.getElementById('visualBrief')?.closest('label');
    if (!grid || !brief) return;

    const essentials = document.createElement('div');
    essentials.className = 'studio-essential-grid ingest-essential-grid';
    brief.after(essentials);
    moveControls(essentials, ['resultsPerTerm','targetClips','hardMaxDuration','minSourceHeight','maxSourceHeight','mediaPrep','normalizeEncoder','cookiesBrowser']);

    const advanced = detailsGroup('Discovery quality & filtering', 'Candidate-pool size, AI query depth, and quality gates.', 'ingest-quality-group');
    moveControls(advanced.body, ['aiDevice','aiCandidates','aiQueries','acquisitionQueries','minVideoFitness','minDynamicScore','maxTextOverlay','maxPersistentText','minMotionCoverage','minTemporalDiversity','maxFaceDominance','minAestheticScore','longVideoAttempts','longVideoExcerptSeconds']);
    essentials.after(advanced.details);

    const automation = detailsGroup('Ingest automation', 'Preview gating, long-video sampling, and automatic trimming.');
    moveControls(automation.body, ['previewGate','sampleLongVideos','autoTrim']);
    advanced.details.after(automation.details);

    const primaryToggles = document.createElement('div');
    primaryToggles.className = 'studio-essential-toggles ingest-primary-toggles';
    moveControls(primaryToggles, ['aiDiscovery','visualIndexScenes']);
    automation.details.after(primaryToggles);

    if (!grid.children.length) grid.hidden = true;
  }

  function run() {
    cleanupNavigation();
    cleanupAnalyze();
    cleanupIngest();
    document.documentElement.classList.add('studio-cleanup-active');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, {once:true});
  else run();
})();
