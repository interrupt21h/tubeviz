// SPDX-License-Identifier: Apache-2.0
// Main-thread facade for the offline WebCodecs encoder/network worker.

export class WorkerVideoEncoderTransport{
  constructor(worker){
    this.worker=worker;this.seq=0;this.pending=new Map();this.framePromises=new Set();this.inflight=0;this.failed=false;this.failureReason='';this.lastQueued=0;this.lastBuffered=0;this.encodedChunks=0;
    worker.onmessage=e=>{
      const m=e.data||{},p=this.pending.get(m.requestId);if(!p){if(m.type==='error')this._fail(m.error);return;}
      this.pending.delete(m.requestId);
      if(p.kind==='frame')this.inflight=Math.max(0,this.inflight-1);
      if(m.type==='error'){p.reject(new Error(m.error||'encoder worker failed'));this._fail(m.error);return;}
      this.lastQueued=Number(m.queued||0);this.lastBuffered=Number(m.buffered||0);this.encodedChunks=Number(m.encodedChunks??m.chunks??this.encodedChunks);p.resolve(m);
    };
    worker.onerror=e=>this._fail(e?.message||'encoder worker error');
  }
  _fail(reason){
    if(this.failed)return;this.failed=true;this.failureReason=String(reason||'encoder worker failed');
    for(const [id,p] of this.pending){if(p.kind==='frame')this.inflight=Math.max(0,this.inflight-1);p.reject(new Error(this.failureReason));this.pending.delete(id);}
  }
  request(message,transfer=[],kind='control'){
    if(this.failed)return Promise.reject(new Error(this.failureReason));
    const requestId=++this.seq;
    const promise=new Promise((resolve,reject)=>{this.pending.set(requestId,{resolve,reject,kind});if(kind==='frame')this.inflight++;this.worker.postMessage({...message,requestId},transfer);});
    if(kind==='frame'){this.framePromises.add(promise);promise.finally(()=>this.framePromises.delete(promise)).catch(()=>{});}
    return promise;
  }
  sendFrame(frame,keyFrame=false){return this.request({type:'frame',frame,keyFrame},[frame],'frame');}
  async waitForCapacity(maxInflight=4){while(this.inflight>=maxInflight&&!this.failed&&this.framePromises.size)await Promise.race([...this.framePromises]);if(this.failed)throw new Error(this.failureReason);}
  async complete(frames){if(this.framePromises.size)await Promise.all([...this.framePromises]);return await this.request({type:'complete',frames});}
  close(){try{this.worker.postMessage({type:'close'});}catch(_){}try{this.worker.terminate();}catch(_){}}
}

export async function createWorkerVideoEncoderTransport({config,wsUrl,maxBufferedBytes=24*1024*1024}={}){
  if(typeof Worker==='undefined'||typeof VideoFrame==='undefined')return null;
  const worker=new Worker('/static/browser_encode_worker.js',{type:'module'}),client=new WorkerVideoEncoderTransport(worker);
  try{await client.request({type:'init',config,wsUrl,maxBufferedBytes});return client;}catch(error){client.close();console.warn('tubeviz encoder worker unavailable; using main-thread VideoEncoder',error);return null;}
}
