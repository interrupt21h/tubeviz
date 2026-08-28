// SPDX-License-Identifier: Apache-2.0
// Dedicated sequential WebCodecs source decoder. TVZ2 stores normal-GOP H.264;
// each source decoder advances forward and resets only to the nearest preceding
// IDR on backwards/random timeline access. TVZ1 all-IDR caches remain readable.

const sources = new Map();
function parsePacked(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength < 12) throw new Error('invalid tubeviz source payload');
  const magic = String.fromCharCode(...bytes.subarray(0, 4));
  if (magic !== 'TVZ1' && magic !== 'TVZ2') throw new Error(`unsupported tubeviz source transport ${magic}`);
  const view = new DataView(buffer), count = view.getUint32(4, true), fps = view.getFloat32(8, true);
  let offset = 12; const units = [];
  for (let i = 0; i < count; i++) {
    let key = true;
    if (magic === 'TVZ2') { if (offset + 5 > bytes.byteLength) throw new Error('truncated source payload'); key = view.getUint8(offset) !== 0; offset++; }
    else if (offset + 4 > bytes.byteLength) throw new Error('truncated source payload');
    const n = view.getUint32(offset, true); offset += 4;
    if (!n || offset + n > bytes.byteLength) throw new Error('truncated source access unit');
    units.push({key, data: bytes.subarray(offset, offset + n)}); offset += n;
  }
  if (!units[0]?.key) throw new Error('source transport does not begin with a key frame');
  return {version: magic === 'TVZ2' ? 2 : 1, fps, units};
}
function nearestKey(s, index) { for (let i = index; i >= 0; i--) if (s.units[i]?.key) return i; return 0; }
function decoderError(error, fallback='source decoder failed') { return error instanceof Error ? error : new Error(String(error || fallback)); }
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
}
async function openSource(m) {
  const response = await fetch(m.url, {cache: 'force-cache'});
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
  const packed = parsePacked(await response.arrayBuffer());
  const state = {fps: packed.fps, units: packed.units, version: packed.version, config: m.config, decodedThrough: -1, chain: Promise.resolve(), closed: false};
  await createDecoder(state); sources.set(m.sourceId, state);
  postMessage({type: 'opened', requestId: m.requestId, sourceId: m.sourceId, fps: state.fps, count: state.units.length, version: state.version});
}
async function decodeFrame(s, index) {
  if (s.error) throw s.error;
  if (s.closed) throw new Error('source decoder closed');
  if (index <= s.decodedThrough) await restartAt(s, nearestKey(s, index));
  const framePromise = new Promise((resolve, reject) => s.waiters.set(index, {resolve, reject}));
  const duration = Math.round(1e6 / s.fps);
  for (let i = s.decodedThrough + 1; i <= index; i++) {
    const unit = s.units[i]; s.outputIndices.push(i);
    s.decoder.decode(new EncodedVideoChunk({type: unit.key ? 'key' : 'delta', timestamp: Math.round(i * 1e6 / s.fps), duration, data: unit.data}));
    s.decodedThrough = i;
    if (s.decoder.decodeQueueSize > 10 && i < index) await s.decoder.flush();
  }
  return await framePromise;
}
async function frameSource(m) {
  const s = sources.get(m.sourceId); if (!s) throw new Error('source not open');
  const index = Math.max(0, Math.min(s.units.length - 1, Number.isInteger(m.index) ? m.index : Math.round(Math.max(0, Number(m.relativeSeconds) || 0) * s.fps)));
  const work = s.chain.then(() => decodeFrame(s, index));
  s.chain = work.then(() => {}, () => {});
  const frame = await work;
  try { postMessage({type: 'frame', requestId: m.requestId, sourceId: m.sourceId, index, frame}, [frame]); }
  catch (error) { try { frame.close(); } catch (_) {} throw error; }
}
function closeSource(id) {
  const s = sources.get(id); if (!s) return;
  s.closed=true;rejectWaiters(s,new Error('source decoder closed'));
  try { if (s.decoder?.state !== 'closed') s.decoder.close(); } catch (_) {}
  sources.delete(id);
}
self.onmessage = async e => {
  const m = e.data || {};
  try {
    if (m.type === 'open') { await openSource(m); return; }
    if (m.type === 'frame') { await frameSource(m); return; }
    if (m.type === 'close') { closeSource(m.sourceId); return; }
    if (m.type === 'close-all') { for (const id of [...sources.keys()]) closeSource(id); return; }
  } catch (error) {
    postMessage({type: 'error', requestId: m.requestId ?? null, sourceId: m.sourceId ?? null, error: String(error?.message || error)});
  }
};
