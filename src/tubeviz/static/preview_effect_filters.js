// SPDX-License-Identifier: Apache-2.0
(() => {
  'use strict';

  const query = new URLSearchParams(location.search);
  const studioPreview = query.get('studio') === '1';
  const storageKey = 'tubeviz.preview.effect-filters.v1';
  const channelName = 'tubeviz-preview-effect-filters-v1';
  const nativeFetch = window.fetch.bind(window);

  const defaults = Object.freeze({
    transforms: true,
    color: true,
    vector: true,
    creative: true,
    temporal: true,
    warp: true,
    composition: true,
    codec: true,
    legacy: true,
  });

  const presets = Object.freeze({
    all: {...defaults},
    classic: {
      transforms: true,
      color: true,
      vector: true,
      creative: false,
      temporal: true,
      warp: true,
      composition: true,
      codec: false,
      legacy: true,
    },
    source: {
      transforms: false,
      color: false,
      vector: false,
      creative: false,
      temporal: false,
      warp: false,
      composition: false,
      codec: false,
      legacy: false,
    },
  });

  const labels = Object.freeze({
    transforms: 'Transform',
    color: 'Color',
    vector: 'Vector',
    creative: 'Creative',
    temporal: 'Temporal',
    warp: 'Warp',
    composition: 'Layers',
    codec: 'Codec',
    legacy: 'Legacy FX',
  });

  function normalize(candidate) {
    const out = {...defaults};
    if (candidate && typeof candidate === 'object') {
      for (const key of Object.keys(defaults)) {
        if (typeof candidate[key] === 'boolean') out[key] = candidate[key];
      }
    }
    return out;
  }

  function loadState() {
    try {
      return normalize(JSON.parse(sessionStorage.getItem(storageKey) || 'null'));
    } catch (_) {
      return {...defaults};
    }
  }

  let state = loadState();
  let originalTimeline = null;
  const proxyCache = new WeakMap();
  const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel(channelName) : null;

  function saveState() {
    try { sessionStorage.setItem(storageKey, JSON.stringify(state)); } catch (_) {}
  }

  function broadcastState() {
    try { channel?.postMessage({type: 'filters', state}); } catch (_) {}
  }

  function setState(next, {broadcast = true} = {}) {
    state = normalize(next);
    saveState();
    renderControls();
    syncLegacySliders();
    if (broadcast) broadcastState();
    window.dispatchEvent(new CustomEvent('tubeviz-preview-effect-filters', {detail: {...state}}));
  }

  function setPreset(name) {
    const preset = presets[name];
    if (preset) setState(preset);
  }

  channel?.addEventListener('message', event => {
    if (event.data?.type === 'filters') setState(event.data.state, {broadcast: false});
  });

  function isTimelineRequest(input) {
    try {
      const value = input instanceof Request ? input.url : String(input);
      return new URL(value, location.href).pathname === '/api/timeline';
    } catch (_) {
      return false;
    }
  }

  const geometricTransformFields = new Set([
    'reverse', 'mirror', 'zoom', 'pan_x', 'pan_y', 'rotation_degrees',
  ]);
  const colorTransformFields = new Set([
    'brightness', 'contrast', 'saturation', 'hue_degrees', 'grayscale', 'blur_px',
  ]);
  const temporalTransformFields = new Set([
    'feedback', 'shutter', 'slit_scan', 'frame_echo', 'mirror_corridor',
    'chroma_delay', 'motion_trails', 'slice_recursion',
  ]);
  const warpTransformFields = new Set([
    'ripple', 'vortex', 'block_displace', 'tunnel',
  ]);
  const legacyTransformFields = new Set([
    'glitch', 'noise', 'pixelate', 'rgb_split', 'scanlines', 'vignette',
    'kaleidoscope', 'tiles', 'posterize', 'edge', 'strobe', 'mask_wipe',
    'solarize', 'datamosh', 'vhs_tracking',
  ]);
  const unitTransformFields = new Set(['zoom', 'brightness', 'contrast', 'saturation']);
  const falseTransformFields = new Set(['reverse', 'mirror']);

  const creativeAllZero = new Set([
    'flow_warp', 'flow_trails', 'flow_rgb', 'temporal_echo', 'temporal_rgb',
    'temporal_smear', 'camera_energy', 'camera_drift_x', 'camera_drift_y',
    'depth_parallax', 'depth_fog', 'subject_preserve', 'background_warp',
    'feedback', 'local_symmetry', 'texture_bloom', 'texture_streaks',
    'palette_strength', 'abstraction', 'hero_amount', 'history_inherit',
  ]);
  const creativeTemporal = new Set([
    'flow_trails', 'temporal_echo', 'temporal_rgb', 'temporal_smear',
    'feedback', 'history_inherit',
  ]);
  const creativeWarp = new Set(['flow_warp', 'background_warp']);

  function neutralTransformValue(target, prop) {
    if (falseTransformFields.has(prop)) return false;
    if (unitTransformFields.has(prop)) return 1.0;
    if (prop === 'blend_mode') return 'normal';
    return 0.0;
  }

  function filteredTransformValue(target, prop) {
    if (!state.transforms && geometricTransformFields.has(prop)) return neutralTransformValue(target, prop);
    if (!state.color && colorTransformFields.has(prop)) return neutralTransformValue(target, prop);
    if (!state.temporal && temporalTransformFields.has(prop)) return 0.0;
    if (!state.warp && warpTransformFields.has(prop)) return 0.0;
    if (!state.legacy && legacyTransformFields.has(prop)) return 0.0;
    return undefined;
  }

  function filteredColorValue(prop) {
    if (state.color) return undefined;
    if (prop === 'source_hue' || prop === 'target_hue' || prop === 'hue_shift_degrees' || prop === 'chromatic_aberration') return 0.0;
    if (prop === 'saturation_scale' || prop === 'contrast_scale' || prop === 'brightness_scale') return 1.0;
    if (prop === 'warmth') return 0.5;
    if (prop === 'palette') return [];
    return undefined;
  }

  function filteredCreativeValue(prop) {
    if (!state.creative) {
      if (creativeAllZero.has(prop)) return 0.0;
      if (prop === 'source_fidelity') return 1.0;
      if (prop === 'hero_kind') return null;
      if (prop === 'automation') return {};
    }
    if (!state.temporal && creativeTemporal.has(prop)) return 0.0;
    if (!state.warp && creativeWarp.has(prop)) return 0.0;
    return undefined;
  }

  function pathKind(path) {
    const last = path[path.length - 1];
    const parent = path[path.length - 2];
    if (last === 'transform') return 'transform';
    if (last === 'color') return 'color';
    if (last === 'creative') return 'creative';
    if (parent === 'scene_plan' && /^\d+$/.test(String(last))) return 'scene';
    if (parent === 'layers' && /^\d+$/.test(String(last))) return 'layer';
    if (last === 'direction') return 'direction';
    return '';
  }

  function proxyFor(value, path) {
    if (!value || typeof value !== 'object') return value;
    let byPath = proxyCache.get(value);
    const key = path.join('.');
    if (!byPath) {
      byPath = new Map();
      proxyCache.set(value, byPath);
    }
    if (byPath.has(key)) return byPath.get(key);

    const proxy = new Proxy(value, {
      get(target, property, receiver) {
        if (typeof property === 'symbol') return Reflect.get(target, property, receiver);
        const prop = String(property);
        const kind = pathKind(path);

        if (kind === 'transform') {
          const filtered = filteredTransformValue(target, prop);
          if (filtered !== undefined) return filtered;
        }

        if (kind === 'color') {
          const filtered = filteredColorValue(prop);
          if (filtered !== undefined) return filtered;
        }

        if (kind === 'creative') {
          const filtered = filteredCreativeValue(prop);
          if (filtered !== undefined) return filtered;
        }

        if (kind === 'direction') {
          if (prop === 'vector_effects' && !state.vector) return [];
          if (prop === 'codec_effects' && !state.codec) return [];
        }

        if (kind === 'scene') {
          if (prop === 'composition_mode' && !state.composition) return 'single';
          if (!state.codec && target.codec_materialization?.materialized) {
            const materialization = target.codec_materialization;
            if (prop === 'media_file' && materialization.original_media_file) return materialization.original_media_file;
            if (prop === 'media_url' && materialization.original_media_url) return materialization.original_media_url;
            if (prop === 'start' && Number.isFinite(Number(materialization.original_start))) return Number(materialization.original_start);
            if (prop === 'end' && Number.isFinite(Number(materialization.original_end))) return Number(materialization.original_end);
          }
        }

        if (kind === 'layer' && !state.composition) {
          if (prop === 'opacity') return 0.0;
          if (prop === 'blend_mode') return 'normal';
        }

        const result = Reflect.get(target, property, receiver);
        return proxyFor(result, [...path, prop]);
      },
    });
    byPath.set(key, proxy);
    return proxy;
  }

  window.fetch = async function tubevizPreviewFilteredFetch(input, init) {
    const response = await nativeFetch(input, init);
    if (!isTimelineRequest(input)) return response;

    return new Proxy(response, {
      get(target, property, receiver) {
        if (property === 'json') {
          return async () => {
            const payload = await Response.prototype.json.call(target);
            originalTimeline = payload;
            return proxyFor(payload, ['timeline']);
          };
        }
        const value = Reflect.get(target, property, receiver);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
  };

  function syncLegacySliders() {
    const values = {
      'fx-master': Object.values(state).some(Boolean) ? 1 : 0,
      'fx-motion': state.warp ? 1 : 0,
      'fx-trails': state.temporal ? 1 : 0,
      'fx-glitch': (state.legacy || state.codec) ? 1 : 0,
      'fx-strobe': state.legacy ? 1 : 0,
    };
    for (const [id, value] of Object.entries(values)) {
      const input = document.getElementById(id);
      if (!input) continue;
      input.value = String(value);
      input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
    }
  }

  function matchingPreset() {
    for (const [name, preset] of Object.entries(presets)) {
      if (Object.keys(defaults).every(key => state[key] === preset[key])) return name;
    }
    return 'custom';
  }

  function addStyle() {
    if (document.getElementById('tubeviz-preview-filter-style')) return;
    const style = document.createElement('style');
    style.id = 'tubeviz-preview-filter-style';
    style.textContent = `
      #tubeviz-preview-filters{position:fixed;z-index:30;right:10px;top:10px;max-width:min(620px,calc(100vw - 20px));padding:8px 9px;border:1px solid rgba(255,255,255,.16);border-radius:10px;background:rgba(8,12,19,.78);color:#eef5ff;box-shadow:0 8px 28px rgba(0,0,0,.30);backdrop-filter:blur(14px);font:11px/1.2 system-ui,sans-serif;user-select:none}
      #tubeviz-preview-filters .pvfx-head{display:flex;align-items:center;gap:7px;margin-bottom:6px}
      #tubeviz-preview-filters .pvfx-head b{font-size:11px;letter-spacing:.08em;text-transform:uppercase}
      #tubeviz-preview-filters .pvfx-head small{opacity:.55;margin-right:auto}
      #tubeviz-preview-filters .pvfx-presets,#tubeviz-preview-filters .pvfx-toggles{display:flex;flex-wrap:wrap;gap:4px}
      #tubeviz-preview-filters .pvfx-presets{margin-bottom:5px;padding-bottom:5px;border-bottom:1px solid rgba(255,255,255,.10)}
      #tubeviz-preview-filters button{appearance:none;border:1px solid rgba(255,255,255,.16);border-radius:999px;padding:4px 7px;background:rgba(255,255,255,.07);color:inherit;font:inherit;cursor:pointer}
      #tubeviz-preview-filters button:hover{background:rgba(255,255,255,.13)}
      #tubeviz-preview-filters button[aria-pressed="true"]{border-color:rgba(137,203,255,.55);background:rgba(73,148,212,.30)}
      #tubeviz-preview-filters .pvfx-preset.active{border-color:rgba(170,225,255,.75);background:rgba(89,168,230,.36)}
      #tubeviz-preview-filters .pvfx-note{margin-top:5px;opacity:.52}
      body.studio-popout #tubeviz-preview-filters{top:14px;right:14px}
      @media(max-width:720px){#tubeviz-preview-filters{left:8px;right:8px;max-width:none}}
    `;
    document.head.appendChild(style);
  }

  function renderControls() {
    const root = document.getElementById('tubeviz-preview-filters');
    if (!root) return;
    for (const button of root.querySelectorAll('[data-filter]')) {
      const key = button.dataset.filter;
      button.setAttribute('aria-pressed', state[key] ? 'true' : 'false');
    }
    const active = matchingPreset();
    for (const button of root.querySelectorAll('[data-preset]')) {
      button.classList.toggle('active', button.dataset.preset === active);
    }
  }

  function installControls() {
    if (!studioPreview || document.getElementById('tubeviz-preview-filters')) return;
    addStyle();
    const root = document.createElement('div');
    root.id = 'tubeviz-preview-filters';
    root.setAttribute('role', 'group');
    root.setAttribute('aria-label', 'Timeline preview effect filters');
    root.innerHTML = `
      <div class="pvfx-head"><b>Preview FX</b><small>preview only · timeline unchanged</small></div>
      <div class="pvfx-presets">
        <button class="pvfx-preset" data-preset="all" type="button">All</button>
        <button class="pvfx-preset" data-preset="classic" type="button" title="Approximate the v0.32 treatment vocabulary while keeping modern preview/render fixes">0.32</button>
        <button class="pvfx-preset" data-preset="source" type="button" title="Show the source edit with treatment families suppressed">Source</button>
      </div>
      <div class="pvfx-toggles">
        ${Object.entries(labels).map(([key, label]) => `<button data-filter="${key}" type="button" aria-pressed="true">${label}</button>`).join('')}
      </div>
      <div class="pvfx-note">Layers and materialized codec media update completely on the next shot/load; all other families are filtered live.</div>
    `;
    document.body.appendChild(root);

    root.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.dataset.preset) {
        setPreset(button.dataset.preset);
        return;
      }
      if (button.dataset.filter) {
        const key = button.dataset.filter;
        setState({...state, [key]: !state[key]});
      }
    });
    renderControls();
  }

  window.TubevizPreviewEffects = Object.freeze({
    getState: () => ({...state}),
    setState: next => setState(next),
    setPreset,
    getOriginalTimeline: () => originalTimeline,
    presets: () => Object.fromEntries(Object.entries(presets).map(([key, value]) => [key, {...value}])),
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      installControls();
      syncLegacySliders();
    }, {once: true});
  } else {
    installControls();
    syncLegacySliders();
  }
})();
