// SPDX-License-Identifier: Apache-2.0
// Sequential H.264 source decoder for deterministic browser renders.
//
// The server supplies a small tubeviz transport rather than asking WebCodecs to
// demux MP4/WebM. TVZ2 uses a normal GOP with explicit key/delta access units;
// the decoder advances sequentially and only restarts from the closest prior IDR
// when timeline access moves backwards. TVZ1 all-keyframe caches remain readable
// for compatibility with v0.37.x libraries.

const DEFAULT_CODEC = 'avc1.64002a';

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

let decoderProbePromise = null;
export async function probeWebCodecsSourceDecoder() {
  if (decoderProbePromise) return decoderProbePromise;
  decoderProbePromise = (async () => {
    if (typeof VideoDecoder === 'undefined' || typeof EncodedVideoChunk === 'undefined') {
      return {supported: false, reason: 'VideoDecoder or EncodedVideoChunk unavailable'};
    }
    const configs = [
      {codec: DEFAULT_CODEC, hardwareAcceleration: 'prefer-hardware', optimizeForLatency: true},
      {codec: 'avc1.4d002a', hardwareAcceleration: 'prefer-hardware', optimizeForLatency: true},
      {codec: 'avc1.42002a', hardwareAcceleration: 'prefer-hardware', optimizeForLatency: true},
    ];
    for (const config of configs) {
      try {
        const support = await VideoDecoder.isConfigSupported(config);
        if (support?.supported) return {supported: true, config: support.config ?? config, codec: config.codec};
      } catch (_) {}
    }
    return {supported: false, reason: 'no supported Annex-B H.264 VideoDecoder configuration'};
  })();
  return decoderProbePromise;
}

let prewarmChain = Promise.resolve();
export function prewarmWebCodecsScene(sceneIndex, layerCount, {fps = 60} = {}) {
  if (!Number.isInteger(sceneIndex) || sceneIndex < 0 || layerCount < 1) return Promise.resolve();
  prewarmChain = prewarmChain.catch(() => {}).then(async () => {
    for (let i = 0; i < layerCount; i++) {
      try {
        const response = await fetch(`/api/offline-source/${sceneIndex}/${i}?fps=${encodeURIComponent(fps)}`, {cache: 'force-cache'});
        if (response.ok) { try { await response.body?.cancel(); } catch (_) {} }
      } catch (_) {}
    }
  });
  return prewarmChain;
}

let sourceWorkerManager = null;
class SourceWorkerManager {
  constructor() {
    this.worker = new Worker('/static/browser_source_worker.js', {type: 'module'});
    this.seq = 0; this.sourceSeq = 0; this.pending = new Map(); this.failed = false;
    this.worker.onmessage = e => {
      const m = e.data || {}, p = this.pending.get(m.requestId);
      if (!p) return;
      this.pending.delete(m.requestId);
      m.type === 'error' ? p.reject(new Error(m.error)) : p.resolve(m);
    };
    this.worker.onerror = e => {
      this.failed = true;
      const err = new Error(e.message || 'source decoder worker failed');
      for (const p of this.pending.values()) p.reject(err);
      this.pending.clear();
    };
  }
  request(message) {
    if (this.failed) return Promise.reject(new Error('source decoder worker unavailable'));
    const requestId = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(requestId, {resolve, reject});
      this.worker.postMessage({...message, requestId});
    });
  }
  async open(url, config) {
    const sourceId = ++this.sourceSeq;
    const m = await this.request({type: 'open', sourceId, url, config});
    return new WorkerWebCodecsSceneSource(this, sourceId, m.fps, m.count, m.version);
  }
  close(sourceId) { if (!this.failed) this.worker.postMessage({type: 'close', sourceId}); }
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

async function openWorkerSource(url, config) {
  if (typeof Worker === 'undefined' || typeof VideoFrame === 'undefined') return null;
  try {
    if (!sourceWorkerManager || sourceWorkerManager.failed) sourceWorkerManager = new SourceWorkerManager();
    return await sourceWorkerManager.open(url, config);
  } catch (error) {
    console.warn('tubeviz source worker unavailable; using main-thread VideoDecoder', error);
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
    this.decoder = new VideoDecoder({
      output: frame => {
        const index = this.outputIndices.shift();
        const waiter = this.waiters.get(index);
        if (waiter) { this.waiters.delete(index); waiter.resolve(frame); }
        else frame.close();
      },
      error: error => {
        this.decoderError = error instanceof Error ? error : new Error(String(error));
        for (const waiter of this.waiters.values()) waiter.reject(this.decoderError);
        this.waiters.clear(); this.outputIndices.length = 0;
      },
    });
    this.decoder.configure(this.config);
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
    const url = `/api/offline-source/${sceneIndex}/${layerIndex}?fps=${encodeURIComponent(fps)}`;
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
