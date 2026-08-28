// SPDX-License-Identifier: Apache-2.0
import {createGpuRendererCore} from '/static/browser_gpu_core.js?v=0.42.2';
let renderer=null;

async function probeWebGpu(){
  if(!self.isSecureContext)throw new Error('worker WebGPU requires a secure context');
  if(!self.navigator?.gpu)throw new Error('WorkerNavigator.gpu unavailable');
  if(typeof OffscreenCanvas==='undefined')throw new Error('OffscreenCanvas unavailable in worker');
  const target=new OffscreenCanvas(4,4);
  const test=await createGpuRendererCore(target,{enableExternalLayers:false});test.resize(4,4);
  const effect=new OffscreenCanvas(4,4),source=new OffscreenCanvas(4,4);
  const ectx=effect.getContext('2d'),sctx=source.getContext('2d');
  if(!ectx||!sctx)throw new Error('worker 2D OffscreenCanvas unavailable for WebGPU probe');
  ectx.fillStyle='#c44';ectx.fillRect(0,0,4,4);sctx.fillStyle='#4c4';sctx.fillRect(0,0,4,4);
  if(!test.render(effect,source,{fidelity:.9,time:0}))throw new Error('worker WebGPU probe render failed');
  if(!await test.sync())throw new Error('worker WebGPU probe synchronization failed');
}

self.onmessage=async event=>{
  const m=event.data||{};
  try{
    if(m.type==='probe'){
      await probeWebGpu();self.postMessage({type:'probe-result',ok:true});return;
    }
    if(m.type==='init'){
      renderer=await createGpuRendererCore(m.canvas,{enableExternalLayers:false});renderer.resize(m.width||1,m.height||1);
      renderer.onDeviceLost=reason=>self.postMessage({type:'device-lost',error:reason});
      self.postMessage({type:'ready'});return;
    }
    if(!renderer)throw new Error('WebGPU worker not initialized');
    if(m.type==='resize'){renderer.resize(m.width,m.height);return;}
    if(m.type==='reset-history'){renderer.resetHistory();return;}
    if(m.type==='render'){
      const ok=renderer.render(m.effect,m.source,m.params||{});
      m.effect?.close();m.source?.close();
      if(!ok)throw new Error(renderer.failureReason||'WebGPU render returned false');
      if(!await renderer.sync())throw new Error(renderer.failureReason||'WebGPU synchronization failed');
      self.postMessage({type:'done',id:m.id,ok:true});return;
    }
  }catch(error){
    try{m.effect?.close();m.source?.close();}catch(_){}
    self.postMessage({type:m.type==='probe'?'probe-result':'error',id:m.id??null,ok:false,error:String(error?.message||error)});
  }
};
