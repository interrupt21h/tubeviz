// SPDX-License-Identifier: Apache-2.0
// Sequential H.264 source decoder for deterministic browser renders.
//
// The server supplies a small tubeviz transport rather than asking WebCodecs to
// demux MP4/WebM. TVZ2 uses a normal GOP with explicit key/delta access units;
// the decoder advances sequentially and only restarts from the closest prior IDR
// when timeline access moves backwards. TVZ1 all-keyframe caches remain readable
// for compatibility with v0.37.x libraries.

const DEFAULT_CODEC = 'avc1.64002a';
const LIVE_SOURCE_PREFIX = '/api/browser-source/';
const LEGACY_OFFLINE_SOURCE_PREFIX = '/api/offline-source/';

export function parsePackedH264(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength < 12) throw new Error('invalid tubeviz WebCodecs source payload');
  const magic = String.fromCharCode(...bytes.subarray(0, 4));
  if (magic !== 'TVZ1' && magic !== 'TVZ2') throw new Error(`unsupported tubeviz source transport ${magic}`);
  const view = new DataView(buffer);
  const count = view.getUint32(4, true);
  const fps = view.getFloat32(8, true);
  if (!Number.isFinite(fps) || fps <= 0 || count < 1) throw new Error('invalid tubeviz source header');
  const units = [];
  let offset = 12;
  for (let i = 0; i < count; i++) {
    let key = true;
    if (magic === 'TVZ2') {
      if (offset + 5 > bytes.byteLength) throw new Error('truncated tubeviz source index');
      key = view.getUint8(offset) !== 0; offset += 1;
    } else if (offset + 4 > bytes.byteLength) {
      throw new Error('truncated tubeviz source index');
    }
    const length = view.getUint32(offset, true); offset += 4;
    if (!length || offset + length > bytes.byteLength) throw new Error('truncated tubeviz H.264 access unit');
    units.push({key, data: bytes.subarray(offset, offset + length)});
    offset += length;
  }
  if (!units[0]?.key) throw new Error('tubeviz source transport does not begin with a key frame');
  return {version: magic === 'TVZ2' ? 2 : 1, fps, units};
}

function decoderConfigCandidates(config = {}) {
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

let decoderProbePromise = null;
export async function probeWebCodecsSourceDecoder() {
  if (decoderProbePromise) return decoderProbePromise;
  decoderProbePromise = (async () => {
    if (typeof VideoDecoder === 'undefined' || typeof EncodedVideoChunk === 'undefined') {
      return {supported: false, reason: 'VideoDecoder or EncodedVideoChunk unavailable'};
    }
    // TVZ2 is encoded as High Profile Level 4.2 (`avc1.64002a`). Do not
    // advertise support by probing a different AVC profile than the transport.
    for (const config of decoderConfigCandidates({codec:DEFAULT_CODEC,hardwareAcceleration:'prefer-hardware',optimizeForLatency:true})) {
      try {
        const support=await VideoDecoder.isConfigSupported(config);
        if(support?.supported)return {supported:true,config:support.config??config,codec:DEFAULT_CODEC};
      } catch (_) {}
    }
    return {supported:false,reason:'no supported High Profile Level 4.2 Annex-B H.264 VideoDecoder configuration'};
  })();
  return decoderProbePromise;
}

let prewarmChain = Promise.resolve();
export function prewarmWebCodecsScene(sceneIndex, layerCount, {fps = 60} = {}) {
  if (!Number.isInteger(sceneIndex) || sceneIndex < 0 || layerCount < 1) return Promise.resolve();
  prewarmChain = prewarmChain.catch(() => {}).then(async () => {
    for (let i = 0; i < layerCount; i++) {
      try {
        const response = await fetch(`${LIVE_SOURCE_PREFIX}${sceneIndex}/${i}?fps=${encodeURIComponent(fps)}`, {cache: 'force-cache'});
        if (response.ok) { try { await response.body?.cancel(); } catch (_) {} }
      } catch (_) {}
    }
  });
  return prewarmChain;
}

let sourceWorkerManager = null;
let sourceWorkerWarningShown = false;
class SourceWorkerManager {
  constructor() {
    this.worker=new Worker('/static/browser_source_worker.js?v=0.44.0',{type:'module'});
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

class WorkerWebCodecsSceneSource {
  constructor(manager, sourceId, fps, count, version = 2) {
    this.manager = manager; this.sourceId = sourceId; this.fps = fps;
    this.frameCount = count; this.transportVersion = version;
    this.currentIndex = -1; this.currentFrame = null; this.closed = false;
  }
  async frameAt(relativeSeconds) {
    if (this.closed) throw new Error('source decoder closed');
    const index = Math.max(0, Math.min(this.frameCount - 1, Math.round(Math.max(0, relativeSeconds) * this.fps)));
    if (index === this.currentIndex && this.currentFrame) return this.currentFrame;
    const m = await this.manager.request({type: 'frame', sourceId: this.sourceId, index});
    this.currentFrame?.close();
    this.currentFrame = m.frame; this.currentIndex = m.index;
    return this.currentFrame;
  }
  async flush() {}
  close() {
    if (this.closed) return;
    this.closed = true; this.currentFrame?.close(); this.currentFrame = null;
    this.manager.close(this.sourceId);
  }
}

async function openWorkerSource(url,config) {
  if(typeof Worker==='undefined'||typeof VideoFrame==='undefined')return null;
  try{
    if(!sourceWorkerManager||sourceWorkerManager.failed)sourceWorkerManager=new SourceWorkerManager();
    if(sourceWorkerManager.workerDecodeUnavailableReason)return null;
    return await sourceWorkerManager.open(url,config);
  }catch(error){
    if(!sourceWorkerWarningShown){sourceWorkerWarningShown=true;console.warn('tubeviz source worker unavailable; using main-thread VideoDecoder',error);}
    return null;
  }
}

export class WebCodecsSceneSource {
  constructor({config, fps, units, version = 2, label = ''}) {
    this.config = config; this.fps = fps; this.units = units; this.transportVersion = version; this.label = label;
    this.currentIndex = -1; this.currentFrame = null; this.decodedThrough = -1;
    this.closed = false; this.decoderError = null; this.outputIndices = []; this.waiters = new Map();
    this._createDecoder();
  }
  _createDecoder() {
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
  _nearestKey(index) {
    for (let i = index; i >= 0; i--) if (this.units[i]?.key) return i;
    return 0;
  }
  _restartAt(index) {
    try { if (this.decoder?.state !== 'closed') this.decoder.close(); } catch (_) {}
    this.outputIndices.length = 0; this.waiters.clear(); this.decoderError = null;
    this._createDecoder(); this.decodedThrough = index - 1;
  }
  static async open(sceneIndex, layerIndex, {fps = 60, strict = false} = {}) {
    const probe = await probeWebCodecsSourceDecoder();
    if (!probe.supported) { if (strict) throw new Error(probe.reason); return null; }
    const url = `${LIVE_SOURCE_PREFIX}${sceneIndex}/${layerIndex}?fps=${encodeURIComponent(fps)}`;
    // LEGACY_OFFLINE_SOURCE_PREFIX remains documented/served for old offline clients.
    void LEGACY_OFFLINE_SOURCE_PREFIX;
    const workerSource = await openWorkerSource(url, probe.config);
    if (workerSource) return workerSource;
    const response = await fetch(url, {cache: 'force-cache'});
    if (!response.ok) throw new Error(`offline source ${sceneIndex}/${layerIndex}: HTTP ${response.status} ${await response.text()}`);
    const packed = parsePackedH264(await response.arrayBuffer());
    return new WebCodecsSceneSource({config: probe.config, fps: packed.fps, units: packed.units, version: packed.version, label: `${sceneIndex}/${layerIndex}`});
  }
  get frameCount() { return this.units.length; }
  async frameAt(relativeSeconds) {
    if (this.closed) throw new Error(`source decoder ${this.label} is closed`);
    if (this.decoderError) throw this.decoderError;
    const index = Math.max(0, Math.min(this.units.length - 1, Math.round(Math.max(0, relativeSeconds) * this.fps)));
    if (index === this.currentIndex && this.currentFrame) return this.currentFrame;
    if (index <= this.decodedThrough) this._restartAt(this._nearestKey(index));
    const framePromise = new Promise((resolve, reject) => this.waiters.set(index, {resolve, reject}));
    const duration = Math.round(1_000_000 / this.fps);
    for (let i = this.decodedThrough + 1; i <= index; i++) {
      const unit = this.units[i]; this.outputIndices.push(i);
      this.decoder.decode(new EncodedVideoChunk({
        type: unit.key ? 'key' : 'delta', timestamp: Math.round(i * 1_000_000 / this.fps), duration, data: unit.data,
      }));
      this.decodedThrough = i;
      if (this.decoder.decodeQueueSize > 10 && i < index) await this.decoder.flush();
    }
    const frame = await framePromise;
    this.currentFrame?.close(); this.currentFrame = frame; this.currentIndex = index;
    return frame;
  }
  async flush() { if (!this.closed && this.decoder.state !== 'closed') await this.decoder.flush(); }
  close() {
    if (this.closed) return;
    this.closed = true; this.currentFrame?.close(); this.currentFrame = null;
    for (const waiter of this.waiters.values()) waiter.reject(new Error('source decoder closed'));
    this.waiters.clear(); this.outputIndices.length = 0;
    try { if (this.decoder.state !== 'closed') this.decoder.close(); } catch (_) {}
  }
}
