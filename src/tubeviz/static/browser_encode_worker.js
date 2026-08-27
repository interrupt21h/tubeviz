// SPDX-License-Identifier: Apache-2.0
// Dedicated WebCodecs output encoder + binary render transport worker.
// The main renderer transfers VideoFrames here; this worker owns VideoEncoder,
// socket backpressure and completion acknowledgement so codec/network callbacks
// never compete with timeline/compositor work on the page thread.

let encoder=null,ws=null,encoderError=null,encodedChunks=0,maxBuffered=24*1024*1024;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function waitOpen(socket){return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('encoder WebSocket open timeout')),10000);socket.addEventListener('open',()=>{clearTimeout(timer);resolve();},{once:true});socket.addEventListener('error',()=>{clearTimeout(timer);reject(new Error('encoder WebSocket connection failed'));},{once:true});});}
async function waitSocketBelow(limit){while(ws?.readyState===WebSocket.OPEN&&ws.bufferedAmount>limit)await sleep(2);if(ws?.readyState!==WebSocket.OPEN)throw new Error('encoder WebSocket closed unexpectedly');}
function waitCompleteAck(){return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('encoder completion acknowledgement timeout')),30000);const onMessage=e=>{if(typeof e.data!=='string')return;let p;try{p=JSON.parse(e.data);}catch(_){return;}if(p.type==='complete'){cleanup();resolve(p);}else if(p.type==='error'){cleanup();reject(new Error(p.error||'render stream failed'));}};const onClose=()=>{cleanup();reject(new Error('encoder WebSocket closed before completion'));};const cleanup=()=>{clearTimeout(timer);ws.removeEventListener('message',onMessage);ws.removeEventListener('close',onClose);};ws.addEventListener('message',onMessage);ws.addEventListener('close',onClose,{once:true});});}
async function init(m){
  if(typeof VideoEncoder==='undefined'||typeof VideoFrame==='undefined')throw new Error('VideoEncoder/VideoFrame unavailable in worker');
  maxBuffered=Math.max(1024*1024,Number(m.maxBufferedBytes)||maxBuffered);
  ws=new WebSocket(m.wsUrl);ws.binaryType='arraybuffer';await waitOpen(ws);
  encoder=new VideoEncoder({output(chunk){if(ws.readyState!==WebSocket.OPEN)return;const bytes=new Uint8Array(chunk.byteLength);chunk.copyTo(bytes);ws.send(bytes);encodedChunks++;},error(error){encoderError=error instanceof Error?error:new Error(String(error));}});
  encoder.configure(m.config);postMessage({type:'ready',requestId:m.requestId});
}
async function encodeFrame(m){
  if(encoderError)throw encoderError;if(!encoder||encoder.state==='closed')throw new Error('encoder worker not initialized');
  const frame=m.frame;try{encoder.encode(frame,{keyFrame:!!m.keyFrame});}finally{frame.close();}
  while((encoder.encodeQueueSize>6||ws.bufferedAmount>maxBuffered)&&!encoderError)await sleep(1);
  if(encoderError)throw encoderError;
  postMessage({type:'accepted',requestId:m.requestId,queued:encoder.encodeQueueSize,buffered:ws.bufferedAmount,chunks:encodedChunks});
}
async function complete(m){
  if(encoderError)throw encoderError;await encoder.flush();if(encoderError)throw encoderError;encoder.close();encoder=null;
  await waitSocketBelow(0);const ack=waitCompleteAck();ws.send(JSON.stringify({type:'complete',frames:m.frames,transport:'webcodecs',encoded_chunks:encodedChunks}));await ack;ws.close();
  postMessage({type:'complete',requestId:m.requestId,encodedChunks});
}
self.onmessage=async e=>{const m=e.data||{};try{if(m.type==='init'){await init(m);return;}if(m.type==='frame'){await encodeFrame(m);return;}if(m.type==='complete'){await complete(m);return;}if(m.type==='close'){try{encoder?.close();}catch(_){}try{ws?.close();}catch(_){}close();}}catch(error){postMessage({type:'error',requestId:m.requestId??null,error:String(error?.message||error)});}};
