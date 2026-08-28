#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text)


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def sub_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"expected exactly one regex match in {path}: {pattern[:120]!r}; got {count}")
    write(path, updated)


# Release metadata and cache-busting.
replace_once("pyproject.toml", 'version = "0.42.0"', 'version = "0.42.1"')
replace_once("src/tubeviz/__init__.py", '__version__ = "0.42.0"', '__version__ = "0.42.1"')
main_cpp = read("src/tubeviz/native_src/src/main.cpp")
if main_cpp.count("tubeviz-native-render 0.42.0") != 2:
    raise SystemExit("unexpected native version occurrences")
write("src/tubeviz/native_src/src/main.cpp", main_cpp.replace("tubeviz-native-render 0.42.0", "tubeviz-native-render 0.42.1"))
write("src/tubeviz/static/gui.html", read("src/tubeviz/static/gui.html").replace("?v=0.42.0", "?v=0.42.1"))
replace_once(
    "src/tubeviz/static/index.html",
    '<script type="module" src="/static/visualizer.js"></script>',
    '<script type="module" src="/static/visualizer.js?v=0.42.1"></script>',
)

# WebGPU: the final beat-warp mode mutates angle, so WGSL requires `var`.
replace_once(
    "src/tubeviz/static/browser_gpu_core.js",
    "    let angle=a*.24*polarity*(1.0-smoothstep(.05,.88,r));\n    angle+=sin(r*34.0*frequency-localPhase*11.0+variant)*a*.035;",
    "    var angle=a*.24*polarity*(1.0-smoothstep(.05,.88,r));\n    angle+=sin(r*34.0*frequency-localPhase*11.0+variant)*a*.035;",
)

# Version the preview module graph so existing Studio tabs cannot combine stale
# 0.42.0 shader/worker modules with the fixed 0.42.1 entry point.
replace_once(
    "src/tubeviz/static/browser_gpu.js",
    "import {createGpuRendererCore} from '/static/browser_gpu_core.js';",
    "import {createGpuRendererCore} from '/static/browser_gpu_core.js?v=0.42.1';",
)
replace_once(
    "src/tubeviz/static/browser_gpu.js",
    "new Worker('/static/browser_gpu_worker.js',{type:'module'})",
    "new Worker('/static/browser_gpu_worker.js?v=0.42.1',{type:'module'})",
)
replace_once(
    "src/tubeviz/static/browser_gpu_worker.js",
    "import {createGpuRendererCore} from '/static/browser_gpu_core.js';",
    "import {createGpuRendererCore} from '/static/browser_gpu_core.js?v=0.42.1';",
)
visualizer = read("src/tubeviz/static/visualizer.js")
for old, new in (
    ("from '/static/browser_gpu.js';", "from '/static/browser_gpu.js?v=0.42.1';"),
    ("from '/static/browser_source.js';", "from '/static/browser_source.js?v=0.42.1';"),
    ("from '/static/browser_encode.js';", "from '/static/browser_encode.js?v=0.42.1';"),
):
    if old not in visualizer:
        raise SystemExit(f"visualizer import not found: {old}")
    visualizer = visualizer.replace(old, new, 1)
write("src/tubeviz/static/visualizer.js", visualizer)

# Worker WebGPU transfer failures own the VideoFrames if postMessage never
# succeeds. Explicitly close them instead of leaving cleanup to GC.
sub_once(
    "src/tubeviz/static/browser_gpu.js",
    r"  render\(effectSource,sourceColorSource,params=\{\}\)\{.*?\n  resetHistory\(\)\{",
    r'''  render(effectSource,sourceColorSource,params={}){
    if(this.failed)return false;
    // Live preview may drop a GPU submission if the worker is already behind.
    if(this.inflight>=2)return true;
    let effect=null,source=null;
    try{
      const ts=Math.max(0,Math.round(Number(params.time||0)*1e6));
      effect=new VideoFrame(effectSource,{timestamp:ts});source=new VideoFrame(sourceColorSource,{timestamp:ts});
      const id=++this.seq;this.inflight++;
      const promise=new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>{
          if(!this.pending.has(id))return;
          this.pending.delete(id);this.inflight=Math.max(0,this.inflight-1);this._markFailed(`WebGPU worker frame ${id} timed out`);reject(new Error(this.failureReason));
        },WORKER_FRAME_TIMEOUT_MS);
        this.pending.set(id,{resolve,reject,timer});
      });
      promise.catch(()=>{});this.lastPromise=promise;
      this.worker.postMessage({type:'render',id,effect,source,params},[effect,source]);
      effect=null;source=null;return true;
    }catch(error){
      try{effect?.close();}catch(_){}try{source?.close();}catch(_){}
      this._markFailed(error?.message||error);return false;
    }
  }
  resetHistory(){''',
)

# Worker-side VideoDecoder capability/configuration must be negotiated in the
# worker itself. Main-thread support does not guarantee an available worker
# hardware session, especially after a random-access decoder restart.
worker_path = "src/tubeviz/static/browser_source_worker.js"
worker = read(worker_path)
worker = re.sub(
    r"function createDecoder\(s\) \{.*?\n\}\nfunction restartAt\(s, index\) \{.*?\n\}",
    r'''function decoderError(error, fallback='source decoder failed') { return error instanceof Error ? error : new Error(String(error || fallback)); }
function rejectWaiters(s, error) {
  const err = decoderError(error);
  for (const waiter of s.waiters?.values?.() ?? []) waiter.reject(err);
  s.waiters?.clear?.(); if (s.outputIndices) s.outputIndices.length = 0;
}
function configCandidates(config) {
  const base = {...(config || {})}, codec = String(base.codec || '');
  if (!codec) return [];
  const raw = [
    base,
    {...base, hardwareAcceleration:'no-preference'},
    {...base, hardwareAcceleration:'prefer-software'},
    {codec, optimizeForLatency:true, hardwareAcceleration:'no-preference'},
    {codec, optimizeForLatency:true},
    {codec},
  ];
  const seen = new Set();
  return raw.filter(item => { const key=JSON.stringify(item); if(seen.has(key))return false; seen.add(key); return true; });
}
function newDecoder(s) {
  return new VideoDecoder({
    output: frame => {
      const index=s.outputIndices.shift(), waiter=s.waiters.get(index);
      if(waiter){s.waiters.delete(index);waiter.resolve(frame);}else frame.close();
    },
    error: error => { s.error=decoderError(error); rejectWaiters(s,s.error); },
  });
}
async function createDecoder(s) {
  s.outputIndices=[];s.waiters=new Map();s.error=null;
  let lastError=null;
  for(const candidate of configCandidates(s.config)){
    let selected=candidate;
    try{
      if(typeof VideoDecoder.isConfigSupported==='function'){
        const support=await VideoDecoder.isConfigSupported(candidate);
        if(!support?.supported)continue;selected=support.config??candidate;
      }
      const decoder=newDecoder(s);
      try{decoder.configure(selected);}catch(error){try{decoder.close();}catch(_){}throw error;}
      s.decoder=decoder;s.config=selected;return;
    }catch(error){lastError=decoderError(error);}
  }
  throw new Error(`no supported worker VideoDecoder configuration for ${s.config?.codec||'unknown codec'}: ${lastError?.message||'unsupported'}`);
}
async function restartAt(s,index) {
  rejectWaiters(s,new Error('source decoder restarted'));
  try{if(s.decoder?.state!=='closed')s.decoder.close();}catch(_){}
  await createDecoder(s);s.decodedThrough=index-1;
}''',
    worker,
    count=1,
    flags=re.S,
)
if "async function createDecoder(s)" not in worker:
    raise SystemExit("worker decoder replacement failed")
worker = worker.replace(
    "  createDecoder(state); sources.set(m.sourceId, state);",
    "  await createDecoder(state); sources.set(m.sourceId, state);",
    1,
)
worker = worker.replace(
    "  if (index <= s.decodedThrough) restartAt(s, nearestKey(s, index));",
    "  if (s.closed) throw new Error('source decoder closed');\n  if (index <= s.decodedThrough) await restartAt(s, nearestKey(s, index));",
    1,
)
worker = worker.replace(
    "  postMessage({type: 'frame', requestId: m.requestId, sourceId: m.sourceId, index, frame}, [frame]);",
    "  try { postMessage({type: 'frame', requestId: m.requestId, sourceId: m.sourceId, index, frame}, [frame]); }\n  catch (error) { try { frame.close(); } catch (_) {} throw error; }",
    1,
)
worker = worker.replace(
    "  const state = {fps: packed.fps, units: packed.units, version: packed.version, config: m.config, decodedThrough: -1, chain: Promise.resolve()};",
    "  const state = {fps: packed.fps, units: packed.units, version: packed.version, config: m.config, decodedThrough: -1, chain: Promise.resolve(), closed: false};",
    1,
)
old_close = "function closeSource(id) {\n  const s = sources.get(id); if (!s) return;\n  try { if (s.decoder.state !== 'closed') s.decoder.close(); } catch (_) {}\n  sources.delete(id);\n}"
new_close = "function closeSource(id) {\n  const s = sources.get(id); if (!s) return;\n  s.closed=true;rejectWaiters(s,new Error('source decoder closed'));\n  try { if (s.decoder?.state !== 'closed') s.decoder.close(); } catch (_) {}\n  sources.delete(id);\n}"
if old_close not in worker:
    raise SystemExit("worker closeSource block not found")
worker = worker.replace(old_close, new_close, 1)
write(worker_path, worker)

# Main-thread source facade: the server always emits High Profile Level 4.2.
# Probe only that codec and vary acceleration preference, then close orphan
# transferred frames and reject pending requests when a source is detached.
source_path = "src/tubeviz/static/browser_source.js"
source = read(source_path)
source = source.replace(
    "new Worker('/static/browser_source_worker.js', {type: 'module'})",
    "new Worker('/static/browser_source_worker.js?v=0.42.1', {type: 'module'})",
    1,
)
marker = "let decoderProbePromise = null;\n"
helper = r'''function decoderConfigCandidates(config = {}) {
  const base={...config,codec:config.codec||DEFAULT_CODEC};
  const raw=[
    base,
    {...base,hardwareAcceleration:'prefer-hardware',optimizeForLatency:true},
    {...base,hardwareAcceleration:'no-preference',optimizeForLatency:true},
    {...base,hardwareAcceleration:'prefer-software',optimizeForLatency:true},
    {codec:base.codec,optimizeForLatency:true,hardwareAcceleration:'no-preference'},
    {codec:base.codec,optimizeForLatency:true},
    {codec:base.codec},
  ];
  const seen=new Set();
  return raw.filter(item=>{const key=JSON.stringify(item);if(seen.has(key))return false;seen.add(key);return true;});
}

'''
if marker not in source:
    raise SystemExit("browser source probe marker missing")
source = source.replace(marker, helper + marker, 1)
source, count = re.subn(
    r"    const configs = \[.*?    return \{supported: false, reason: 'no supported Annex-B H\.264 VideoDecoder configuration'\};",
    r'''    // TVZ2 is encoded as High Profile Level 4.2 (`avc1.64002a`). Do not
    // advertise support by probing a different AVC profile than the transport.
    for (const config of decoderConfigCandidates({codec:DEFAULT_CODEC,hardwareAcceleration:'prefer-hardware',optimizeForLatency:true})) {
      try {
        const support=await VideoDecoder.isConfigSupported(config);
        if(support?.supported)return {supported:true,config:support.config??config,codec:DEFAULT_CODEC};
      } catch (_) {}
    }
    return {supported:false,reason:'no supported High Profile Level 4.2 Annex-B H.264 VideoDecoder configuration'};''',
    source,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit("browser source probe replacement failed")
source = source.replace("let sourceWorkerManager = null;\n", "let sourceWorkerManager = null;\nlet sourceWorkerWarningShown = false;\n", 1)
source, count = re.subn(
    r"class SourceWorkerManager \{.*?\n\}\n\nclass WorkerWebCodecsSceneSource",
    r'''class SourceWorkerManager {
  constructor() {
    this.worker=new Worker('/static/browser_source_worker.js?v=0.42.1',{type:'module'});
    this.seq=0;this.sourceSeq=0;this.pending=new Map();this.failed=false;this.workerDecodeUnavailableReason='';
    this.worker.onmessage=e=>{
      const m=e.data||{},p=this.pending.get(m.requestId);
      if(!p){try{m.frame?.close?.();}catch(_){}return;}
      this.pending.delete(m.requestId);m.type==='error'?p.reject(new Error(m.error)):p.resolve(m);
    };
    this.worker.onerror=e=>{
      this.failed=true;const err=new Error(e.message||'source decoder worker failed');
      for(const p of this.pending.values())p.reject(err);this.pending.clear();
    };
  }
  request(message) {
    if(this.failed)return Promise.reject(new Error('source decoder worker unavailable'));
    const requestId=++this.seq;
    return new Promise((resolve,reject)=>{
      this.pending.set(requestId,{resolve,reject,sourceId:message.sourceId??null});
      try{this.worker.postMessage({...message,requestId});}catch(error){this.pending.delete(requestId);reject(error);}
    });
  }
  async open(url,config) {
    if(this.workerDecodeUnavailableReason)throw new Error(this.workerDecodeUnavailableReason);
    const sourceId=++this.sourceSeq;
    try{
      const m=await this.request({type:'open',sourceId,url,config});
      return new WorkerWebCodecsSceneSource(this,sourceId,m.fps,m.count,m.version);
    }catch(error){
      const reason=String(error?.message||error);
      if(/no supported worker VideoDecoder configuration|Unsupported configuration/i.test(reason))this.workerDecodeUnavailableReason=reason;
      throw error;
    }
  }
  close(sourceId) {
    const error=new Error('source decoder closed');
    for(const [requestId,p] of this.pending){if(p.sourceId!==sourceId)continue;this.pending.delete(requestId);p.reject(error);}
    if(!this.failed){try{this.worker.postMessage({type:'close',sourceId});}catch(_){}}
  }
}

class WorkerWebCodecsSceneSource''',
    source,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit("SourceWorkerManager replacement failed")
source, count = re.subn(
    r"async function openWorkerSource\(url, config\) \{.*?\n\}",
    r'''async function openWorkerSource(url,config) {
  if(typeof Worker==='undefined'||typeof VideoFrame==='undefined')return null;
  try{
    if(!sourceWorkerManager||sourceWorkerManager.failed)sourceWorkerManager=new SourceWorkerManager();
    if(sourceWorkerManager.workerDecodeUnavailableReason)return null;
    return await sourceWorkerManager.open(url,config);
  }catch(error){
    if(!sourceWorkerWarningShown){sourceWorkerWarningShown=true;console.warn('tubeviz source worker unavailable; using main-thread VideoDecoder',error);}
    return null;
  }
}''',
    source,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit("openWorkerSource replacement failed")
source, count = re.subn(
    r"  _createDecoder\(\) \{.*?\n  \}\n  _nearestKey",
    r'''  _createDecoder() {
    const callbacks={
      output:frame=>{const index=this.outputIndices.shift(),waiter=this.waiters.get(index);if(waiter){this.waiters.delete(index);waiter.resolve(frame);}else frame.close();},
      error:error=>{this.decoderError=error instanceof Error?error:new Error(String(error));for(const waiter of this.waiters.values())waiter.reject(this.decoderError);this.waiters.clear();this.outputIndices.length=0;},
    };
    let lastError=null;
    for(const config of decoderConfigCandidates(this.config)){
      const decoder=new VideoDecoder(callbacks);
      try{decoder.configure(config);this.decoder=decoder;this.config=config;return;}
      catch(error){lastError=error;try{decoder.close();}catch(_){}}
    }
    throw lastError??new Error(`no supported VideoDecoder configuration for ${this.config?.codec||DEFAULT_CODEC}`);
  }
  _nearestKey''',
    source,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit("main-thread decoder replacement failed")
write(source_path, source)

# Detach a bank immediately after closing its sources so the frame loop cannot
# keep calling frameAt() on a source that is intentionally closed while the next
# scene is being loaded.
replace_once(
    "src/tubeviz/static/visualizer.js",
    "function closeBankSources(bankIndex){\n  for(const st of bankState[bankIndex]??[])try{st.source?.close();}catch(_){}\n}",
    "function closeBankSources(bankIndex){\n  const states=bankState[bankIndex]??[];bankState[bankIndex]=[];\n  for(const st of states)try{st.source?.close();}catch(_){}\n}",
)
sub_once(
    "src/tubeviz/static/visualizer.js",
    r"function updateLiveSourceFrames\(\)\{.*?\n\}\n\nfunction previewLayerBudget",
    r'''function updateLiveSourceFrames(){
  if(offlineMode||liveSourceDecodeMode!=='webcodecs'||audio.paused)return;
  const now=clockSeconds();
  for(let bankIndex=0;bankIndex<bankState.length;bankIndex++){
    const states=bankState[bankIndex]??[];
    for(let layerIndex=0;layerIndex<states.length;layerIndex++){
      const st=states[layerIndex];if(!st.source||st.source.closed||st.framePending)continue;
      const rate=st.transform?.materialized?1:Number(st.transform?.playback_rate??1);
      let offset=((now-Number(st.sceneTime??0))*rate+(st.liveBias??0))%st.span;if(offset<0)offset+=st.span;
      if(st.transform?.reverse)offset=Math.max(0,st.span-offset-.001);
      const fallbackOffset=offset;
      st.framePending=st.source.frameAt(offset).then(frame=>{st.frame=frame;}).catch(async error=>{
        if(st.webCodecsFailed||bankState[bankIndex]?.[layerIndex]!==st)return;
        st.webCodecsFailed=true;console.warn('live WebCodecs source failed; switching this preview to HTMLVideoElement',error);
        try{st.source?.close();}catch(_){}st.source=null;st.frame=null;
        liveSourceDecodeMode='video';liveSourceDecodeReason=`WebCodecs fallback: ${String(error?.message||error)}`;updateRendererStatus(liveSourceDecodeReason);
        const scene=timeline.scene_plan[st.sceneIndex],layer=scene?allLayers(scene)[st.layerIndex]:null,video=banks[bankIndex]?.[st.layerIndex];
        if(!scene||!layer||!video||bankState[bankIndex]?.[layerIndex]!==st)return;
        try{
          const replacement=await loadHtmlLayer(video,layer,scene,st.layerIndex,st.sceneIndex);
          if(bankState[bankIndex]?.[layerIndex]!==st)return;
          replacement.video.currentTime=Math.max(replacement.start,Math.min(replacement.end-.02,replacement.start+fallbackOffset));
          Object.assign(st,replacement,{webCodecsFailed:true});
        }catch(fallbackError){console.warn('HTML video fallback also failed',fallbackError);}
      }).finally(()=>{st.framePending=null;});
    }
  }
}

function previewLayerBudget''',
)

# Regression tests for the exact console failures and lifecycle fallout.
tests_path = "tests/test_browser_phase2.py"
tests = read(tests_path)
if "test_webgpu_wgsl_mutation_and_webcodecs_lifecycle_regressions" in tests:
    raise SystemExit("browser regression tests already present")
tests += r'''


def test_webgpu_wgsl_mutation_and_webcodecs_lifecycle_regressions():
    core = Path("src/tubeviz/static/browser_gpu_core.js").read_text()
    facade = Path("src/tubeviz/static/browser_gpu.js").read_text()
    source = Path("src/tubeviz/static/browser_source.js").read_text()
    source_worker = Path("src/tubeviz/static/browser_source_worker.js").read_text()
    visualizer = Path("src/tubeviz/static/visualizer.js").read_text()

    assert "var angle=a*.24*polarity" in core
    assert "let angle=a*.24*polarity" not in core
    assert "angle+=sin(r*34.0*frequency" in core
    assert "avc1.64002a" in source
    assert "avc1.4d002a" not in source
    assert "avc1.42002a" not in source
    assert "VideoDecoder.isConfigSupported" in source_worker
    assert "hardwareAcceleration:'no-preference'" in source_worker
    assert "hardwareAcceleration:'prefer-software'" in source_worker
    assert "m.frame?.close?.()" in source
    assert "effect?.close()" in facade and "source?.close()" in facade
    assert "rejectWaiters(s,new Error('source decoder closed'))" in source_worker
    assert "bankState[bankIndex]=[]" in visualizer
    assert "st.source.closed" in visualizer
    assert "live WebCodecs source failed; switching this preview to HTMLVideoElement" in visualizer
    assert "liveSourceDecodeMode='video'" in visualizer


def test_preview_module_graph_is_release_cache_busted():
    index = Path("src/tubeviz/static/index.html").read_text()
    visualizer = Path("src/tubeviz/static/visualizer.js").read_text()
    gpu = Path("src/tubeviz/static/browser_gpu.js").read_text()
    source = Path("src/tubeviz/static/browser_source.js").read_text()
    assert "/static/visualizer.js?v=0.42.1" in index
    assert "/static/browser_gpu.js?v=0.42.1" in visualizer
    assert "/static/browser_source.js?v=0.42.1" in visualizer
    assert "/static/browser_gpu_core.js?v=0.42.1" in gpu
    assert "/static/browser_source_worker.js?v=0.42.1" in source
'''
write(tests_path, tests)

# Package CI should syntax-check the whole browser module graph.
ci_path = ".github/workflows/ci.yml"
ci = read(ci_path)
old_ci = """      - name: Validate Python and browser sources
        run: |
          python -m compileall -q src/tubeviz
          node --check src/tubeviz/static/gui.js
"""
new_ci = """      - name: Validate Python and browser sources
        run: |
          python -m compileall -q src/tubeviz
          for file in \\
            src/tubeviz/static/gui.js \\
            src/tubeviz/static/visualizer.js \\
            src/tubeviz/static/browser_gpu.js \\
            src/tubeviz/static/browser_gpu_core.js \\
            src/tubeviz/static/browser_gpu_worker.js \\
            src/tubeviz/static/browser_source.js \\
            src/tubeviz/static/browser_source_worker.js \\
            src/tubeviz/static/browser_encode.js \\
            src/tubeviz/static/browser_encode_worker.js; do
            node --check "$file"
          done
"""
if old_ci not in ci:
    raise SystemExit("CI browser validation block not found")
write(ci_path, ci.replace(old_ci, new_ci, 1))

# Keep release history in CHANGELOG, not README.
changelog = read("CHANGELOG.md")
if not changelog.startswith("# 0.42.0"):
    raise SystemExit("unexpected CHANGELOG head")
entry = """# 0.42.1 — WebGPU and WebCodecs preview reliability

- Fix the WebGPU compositor WGSL regression that declared the final beat-warp `angle` as immutable and then mutated it, causing shader-module compilation to fail and forcing affected previews back to Canvas2D.
- Keep the TVZ2 WebCodecs codec contract truthful: capability probing now tests the High Profile Level 4.2 AVC configuration actually emitted by the server and varies hardware/software preference without substituting an incompatible profile string.
- Negotiate WebCodecs support inside the dedicated decoder worker as well as on the main thread. Decoder creation and random-access restarts fall back from hardware preference to no-preference/software decoding when a hardware session cannot be configured.
- Close orphaned or failed-transfer `VideoFrame` objects explicitly, reject pending requests when a source closes, and detach closed banks immediately so late worker frames cannot leak or trigger repeated `source decoder closed` requests.
- If a live worker decoder still fails at runtime, downgrade the active preview to `HTMLVideoElement` once and preserve the current source position instead of logging the same failure every animation frame.
- Cache-bust the browser preview module graph for 0.42.1 and expand CI JavaScript syntax validation across the WebGPU, WebCodecs, encoder and visualizer modules.

"""
write("CHANGELOG.md", entry + changelog)

print("WebGPU/WebCodecs v0.42.1 fixes applied")
