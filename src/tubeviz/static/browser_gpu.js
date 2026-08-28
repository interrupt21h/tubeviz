// SPDX-License-Identifier: Apache-2.0
import {createGpuRendererCore} from '/static/browser_gpu_core.js?v=0.43.0-previewfix1';

const WORKER_PROBE_TIMEOUT_MS=4000;
const WORKER_INIT_TIMEOUT_MS=5000;
const WORKER_FRAME_TIMEOUT_MS=3500;

function waitForWorkerMessage(worker,predicate,timeoutMs,label){
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{cleanup();reject(new Error(`${label} timeout`));},timeoutMs);
    const onMessage=e=>{const m=e.data||{};if(!predicate(m))return;cleanup();m.type==='error'?reject(new Error(m.error||`${label} failed`)):resolve(m);};
    const onError=e=>{cleanup();reject(new Error(e?.message||`${label} worker error`));};
    const cleanup=()=>{clearTimeout(timer);worker.removeEventListener('message',onMessage);worker.removeEventListener('error',onError);};
    worker.addEventListener('message',onMessage);worker.addEventListener('error',onError);
  });
}

class WorkerGpuFinalizer{
  constructor(canvas,worker){
    this.canvas=canvas;this.worker=worker;this.width=0;this.height=0;this.seq=0;this.pending=new Map();this.inflight=0;this.failed=false;this.failureReason='';this.lastPromise=null;
    worker.onmessage=e=>{
      const m=e.data||{};
      if(m.type!=='done'&&m.type!=='error'&&m.type!=='device-lost')return;
      if(m.type==='device-lost'){
        this._failAll(m.error||'WebGPU device lost');return;
      }
      this.inflight=Math.max(0,this.inflight-1);
      const p=this.pending.get(m.id);
      if(p){this.pending.delete(m.id);clearTimeout(p.timer);m.type==='error'?p.reject(new Error(m.error||'WebGPU worker render failed')):p.resolve(m.ok!==false);}
      if(m.type==='error')this._markFailed(m.error||'WebGPU worker render failed');
    };
    worker.onerror=e=>this._failAll(e?.message||'WebGPU worker error');
  }
  _markFailed(reason){this.failed=true;this.failureReason=String(reason||'WebGPU worker failed');}
  _failAll(reason){
    this._markFailed(reason);this.inflight=0;
    for(const [id,p] of this.pending){clearTimeout(p.timer);p.reject(new Error(this.failureReason));this.pending.delete(id);}
  }
  resize(width,height){
    width=Math.max(1,Math.floor(width));height=Math.max(1,Math.floor(height));if(width===this.width&&height===this.height)return;
    this.width=width;this.height=height;if(!this.failed)this.worker.postMessage({type:'resize',width,height});
  }
  render(effectSource,sourceColorSource,params={}){
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
  resetHistory(){if(!this.failed)this.worker.postMessage({type:'reset-history'});}
  async sync(){if(!this.lastPromise)return !this.failed;try{return await this.lastPromise;}catch(_){return false;}}
  close(){try{this.worker.terminate();}catch(_){}this._failAll('WebGPU worker closed');}
}

async function probeWorkerWebGpu(worker){
  const result=waitForWorkerMessage(worker,m=>m.type==='probe-result'||m.type==='error',WORKER_PROBE_TIMEOUT_MS,'WebGPU worker probe');
  worker.postMessage({type:'probe'});
  const message=await result;
  if(message.ok!==true)throw new Error(message.error||'worker WebGPU probe failed');
  return message;
}

async function createWorkerGpuFinalizer(canvas){
  if(typeof Worker==='undefined'||typeof VideoFrame==='undefined'||typeof OffscreenCanvas==='undefined'||typeof canvas.transferControlToOffscreen!=='function')throw new Error('worker OffscreenCanvas/VideoFrame unavailable');
  const worker=new Worker('/static/browser_gpu_worker.js?v=0.43.0-previewfix1',{type:'module'});
  try{
    // Crucial ordering: prove worker-side WebGPU + WGSL + external-image copies on a
    // scratch OffscreenCanvas BEFORE transferring the visible canvas. Once an
    // HTMLCanvasElement has been transferred, getContext() can no longer be used on
    // the main thread, so an early transfer would destroy the main-thread fallback.
    await probeWorkerWebGpu(worker);
    const ready=waitForWorkerMessage(worker,m=>m.type==='ready'||m.type==='error',WORKER_INIT_TIMEOUT_MS,'WebGPU worker init');
    const offscreen=canvas.transferControlToOffscreen();
    worker.postMessage({type:'init',canvas:offscreen,width:Math.max(1,canvas.width),height:Math.max(1,canvas.height)},[offscreen]);
    await ready;
    return new WorkerGpuFinalizer(canvas,worker);
  }catch(error){try{worker.terminate();}catch(_){}throw error;}
}

async function createMainThreadGpuFinalizer(canvas){
  const finalizer=await createGpuRendererCore(canvas);
  // Force a tiny real render before declaring success. This catches shader/pipeline or
  // external-image-copy failures during initialization instead of on the first song frame.
  const a=document.createElement('canvas'),b=document.createElement('canvas');a.width=b.width=2;a.height=b.height=2;
  const ac=a.getContext('2d'),bc=b.getContext('2d');ac.fillStyle='#123';ac.fillRect(0,0,2,2);bc.fillStyle='#456';bc.fillRect(0,0,2,2);
  finalizer.resize(2,2);if(!finalizer.render(a,b,{fidelity:.9,time:0})||!await finalizer.sync())throw new Error('main-thread WebGPU self-test failed');
  return finalizer;
}

export async function createBrowserGpuFinalizer(canvas,mode='auto',{preferWorker=true}={}){
  if(mode==='off')return{finalizer:null,reason:'disabled'};
  if(!globalThis.isSecureContext)return{finalizer:null,reason:'WebGPU requires a secure context'};
  if(!globalThis.navigator?.gpu)return{finalizer:null,reason:'navigator.gpu unavailable'};

  let workerError=null;
  if(preferWorker){
    try{return{finalizer:await createWorkerGpuFinalizer(canvas),reason:'webgpu-worker'};}catch(error){workerError=error;}
  }

  // Live preview intentionally prefers main-thread WebGPU. Canvas2D composition is
  // already on the main thread, and direct GPU submission avoids two VideoFrame
  // transfers plus worker synchronization on every displayed preview frame.
  try{
    const suffix=preferWorker&&workerError?` (worker unavailable: ${String(workerError?.message||workerError)})`:' (live preview)';
    return{finalizer:await createMainThreadGpuFinalizer(canvas),reason:`webgpu-main${suffix}`};
  }catch(mainError){
    const workerText=preferWorker?String(workerError?.message||workerError):'not requested';
    const reason=`WebGPU unavailable: worker=${workerText}; main=${String(mainError?.message||mainError)}`;
    // Preview must remain usable even when the user selected WebGPU explicitly. The
    // caller can surface this reason while continuing with the Canvas2D compositor.
    return{finalizer:null,reason,requested:mode};
  }
}
