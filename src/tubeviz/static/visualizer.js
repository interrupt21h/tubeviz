// SPDX-License-Identifier: Apache-2.0
const canvas = document.querySelector('#canvas');
const ctx = canvas.getContext('2d', {alpha:true});
const videoFx = document.querySelector('#video-fx');
const fx = videoFx.getContext('2d', {alpha:false});
const audio = document.querySelector('#audio');
const meta = document.querySelector('#meta');
const clipMeta = document.querySelector('#clip-meta');
const decoders = Array.from({length:8}, (_,i)=>document.querySelector(`#decoder-${i}`));
const banks = [decoders.slice(0,4), decoders.slice(4,8)];
const bankState = [[], []];
const bankMode = ['single', 'single'];

let width=0,height=0,activeBank=-1,transition=null,activeScene=null;
let world=0,sectionLabel='unknown',sectionEnergy=0,phase=0,bloom=0,warp=0,barPulse=0,phaseFlash=0,anticipation=0;
let punch=0,sliceFx=0,focusLayer=0,freezeUntil=0;
let strobeFx=0,tunnelFx=0,kaleidoFx=0,rippleFx=0,edgeFx=0;
let slitScanFx=0,echoFx=0,corridorFx=0,maskFx=0,solarizeFx=0;
let datamoshFx=0,chromaDelayFx=0,vortexFx=0,motionTrailFx=0,sliceRecursionFx=0;
let beatWarpFx=0,beatLow=0,beatMid=0,beatHigh=0,tempoWarpFx=0;
let currentVibe='neutral',currentLocalBpm=120,currentBass=0,currentPercussive=0,currentTonal=0;
let shutterNext=0,frameCounter=0;
const liveFx={master:1,motion:1,trails:1,glitch:1,strobe:1};
const fragments=[]; const motifObjects=new Map();

const query=new URLSearchParams(location.search);
const offlineMode=query.get('offline')==='1';
let offlineTime=0,offlineFps=60,offlineCueIndex=0,offlineLoadedScene=-1,offlineRandState=0x51f15e;
function clockSeconds(){return offlineMode?offlineTime:audio.currentTime;}
function clockNowMs(){return offlineMode?offlineTime*1000:performance.now();}
function rand(){
  if(!offlineMode)return Math.random();
  let x=offlineRandState|0;
  x^=x<<13;x^=x>>>17;x^=x<<5;
  offlineRandState=x>>>0;
  return offlineRandState/4294967296;
}

function offscreen(alpha=false){const c=document.createElement('canvas');return [c,c.getContext('2d',{alpha})];}
const [history,historyCtx]=offscreen(false);
const [scratch,scratchCtx]=offscreen(true);
const [freezeCanvas,freezeCtx]=offscreen(false);
const [holdCanvas,holdCtx]=offscreen(false);
const [edgeCanvas,edgeCtx]=offscreen(true);
const [posterCanvas,posterCtx]=offscreen(false);
const [delayA,delayACtx]=offscreen(false);
const [delayB,delayBCtx]=offscreen(false);
const [delayC,delayCCtx]=offscreen(false);
const [exportCanvas,exportCtx]=offscreen(false);
const [vectorSample,vectorSampleCtx]=offscreen(false);
const [vectorScratch,vectorScratchCtx]=offscreen(true);
const [motionProbe,motionProbeCtx]=offscreen(false);
const [motionPrev,motionPrevCtx]=offscreen(false);
const [flowProbe,flowProbeCtx]=offscreen(false);
const [flowPrev,flowPrevCtx]=offscreen(false);
const [depthProbe,depthProbeCtx]=offscreen(false);
const [subjectMask,subjectMaskCtx]=offscreen(true);
const [subjectLayer,subjectLayerCtx]=offscreen(true);
const delayBuffers=[delayA,delayB,delayC];
const vectorGeometryCache=new Map();
const vectorEchoHistory=[];
let vectorEdgeCache={frame:-1,paths:[],salientPaths:[],points:[],salient:[]};
let vectorFlowCache={frame:-1,field:[],cols:0,rows:0,ready:false};
let vectorFlowInitialized=false;
let creativeDepthCache={frame:-1,cells:[],cols:16,rows:9};
const delayCtx=[delayACtx,delayBCtx,delayCCtx];
let delayWrite=0;

function resize(){
  width=canvas.width=videoFx.width=Math.floor(innerWidth*devicePixelRatio);
  height=canvas.height=videoFx.height=Math.floor(innerHeight*devicePixelRatio);
  for(const c of [history,scratch,freezeCanvas,holdCanvas,edgeCanvas,subjectLayer]){c.width=width;c.height=height;}
  for(const c of delayBuffers){c.width=Math.max(1,Math.floor(width/2));c.height=Math.max(1,Math.floor(height/2));}
  exportCanvas.width=width;exportCanvas.height=height;
  vectorSample.width=128;vectorSample.height=72;
  vectorScratch.width=width;vectorScratch.height=height;
  motionProbe.width=64;motionProbe.height=36;motionPrev.width=64;motionPrev.height=36;
  motionPrevCtx.fillStyle='#000';motionPrevCtx.fillRect(0,0,64,36);
  flowProbe.width=64;flowProbe.height=36;flowPrev.width=64;flowPrev.height=36;
  flowPrevCtx.fillStyle='#000';flowPrevCtx.fillRect(0,0,64,36);
  depthProbe.width=16;depthProbe.height=9;subjectMask.width=16;subjectMask.height=9;creativeDepthCache={frame:-1,cells:[],cols:16,rows:9};
  vectorGeometryCache.clear();vectorEchoHistory.length=0;
  vectorEdgeCache={frame:-1,paths:[],salientPaths:[],points:[],salient:[]};
  vectorFlowCache={frame:-1,field:[],cols:0,rows:0,ready:false};
  posterCanvas.width=Math.max(96,Math.min(320,Math.floor(width/5)));
  posterCanvas.height=Math.max(54,Math.min(180,Math.floor(height/5)));
}
addEventListener('resize',resize); resize();

const timeline=await fetch('/api/timeline').then(r=>r.json());
const status=await fetch('/api/status').then(r=>r.json()).catch(()=>({clips_enabled:false,scene_count:0}));
const tempoValues=(timeline.track.tempo_curve??[]).map(p=>p.bpm).filter(Number.isFinite).sort((a,b)=>a-b);
let tempoText=`${timeline.track.tempo_bpm.toFixed(1)} BPM`;
if(tempoValues.length>4){
  const lo=tempoValues[Math.floor(tempoValues.length*.10)],hi=tempoValues[Math.min(tempoValues.length-1,Math.floor(tempoValues.length*.90))];
  if(hi-lo>=3)tempoText=`${lo.toFixed(0)}–${hi.toFixed(0)} BPM variable`;
}
meta.textContent=`${tempoText} · ${timeline.track.key ?? 'key ?'} · ${timeline.track.sections.length} sections · ${timeline.motifs.length} motifs · ${status.scene_count ?? 0} scene groups`;
if(!status.clips_enabled||!status.scene_count) clipMeta.textContent='No clip scene plan; video canvas idle';

const wsProtocol=location.protocol==='https:'?'wss:':'ws:';
const ws=offlineMode?null:new WebSocket(`${wsProtocol}//${location.host}/ws`);
function send(command,extra={}){if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({command,...extra}));}

const fxToggle=document.querySelector('#fx-toggle');
const fxPanel=document.querySelector('#fx-panel');
fxToggle?.addEventListener('click',()=>fxPanel?.classList.toggle('open'));
for(const name of ['master','motion','trails','glitch','strobe']){
  const input=document.querySelector(`#fx-${name}`);
  const value=document.querySelector(`#fx-${name}-v`);
  if(!input)continue;
  const update=()=>{liveFx[name]=Number(input.value);if(value)value.textContent=liveFx[name].toFixed(2);};
  input.addEventListener('input',update);update();
}
function pauseAll(){decoders.forEach(v=>v.pause());}
if(!offlineMode){
  audio.addEventListener('play',()=>{send('play',{position:clockSeconds()});if(activeBank>=0)banks[activeBank].forEach(v=>v.play().catch(()=>{}));});
  audio.addEventListener('pause',()=>{send('pause');pauseAll();});
  audio.addEventListener('seeked',()=>send('seek',{position:clockSeconds()}));
}

function waitMetadata(v){if(v.readyState>=1)return Promise.resolve();return new Promise((res,rej)=>{const ok=()=>{clean();res();},bad=()=>{clean();rej(v.error||new Error('metadata load failed'));},clean=()=>{v.removeEventListener('loadedmetadata',ok);v.removeEventListener('error',bad);};v.addEventListener('loadedmetadata',ok,{once:true});v.addEventListener('error',bad,{once:true});});}
function mediaUrl(layer){if(layer.media_url)return layer.media_url;const parts=String(layer.media_file||"").split("/");const root=parts[0]==="originals"?"/originals/":"/media/";if(parts[0]==="originals"||parts[0]==="normalized")parts.shift();return root+parts.map(encodeURIComponent).join("/");}
function allLayers(scene){return [{...scene,role:'primary',opacity:scene.opacity??.92,blend_mode:scene.transform?.blend_mode??'normal'},...(scene.layers??[])].slice(0,4);}

async function loadBank(bankIndex,scene){
  const layers=allLayers(scene),vids=banks[bankIndex],states=[];
  for(let i=0;i<vids.length;i++){
    const v=vids[i],layer=layers[i];
    if(!layer){v.pause();v.removeAttribute('src');v.load();continue;}
    const url=mediaUrl(layer),abs=new URL(url,location.href).href;
    if(v.src!==abs){v.src=url;v.load();}
    await waitMetadata(v);
    const start=Number(layer.start??0),end=Number(layer.end??v.duration),span=Math.max(.05,end-start);
    const resume=i===0&&Number.isFinite(scene.resume_at)?scene.resume_at:start;
    v.currentTime=Math.max(start,Math.min(end-.02,resume));
    const t=layer.transform??{};v.playbackRate=t.materialized?1:(t.playback_rate??1);
    states.push({video:v,layer,start,end,span,transform:t,offlineBias:0});
    if(!audio.paused)v.play().catch(()=>{});
  }
  bankState[bankIndex]=states;bankMode[bankIndex]=scene.composition_mode??'single';
}

let activationGeneration=0;
async function activateScene(scene,{immediate=false}={}){
  if(!scene){activeScene=null;pauseAll();bankState[0]=[];bankState[1]=[];return;}
  const gen=++activationGeneration,next=activeBank<0?0:1-activeBank;
  try{
    await loadBank(next,scene);if(gen!==activationGeneration)return;
    const duration=immediate?0:Math.max(0,scene.crossfade_seconds??1.25);
    transition=activeBank<0?null:{from:activeBank,to:next,start:clockNowMs(),duration:duration*1000};
    if(activeBank<0||duration===0){if(activeBank>=0)banks[activeBank].forEach(v=>v.pause());activeBank=next;transition=null;}
    activeScene={...scene};focusLayer=0;resetVectorMotionState();
    const t=scene.transform??{};
    const fxNames=['ripple','kaleidoscope','tiles','tunnel','posterize','edge','strobe','shutter','slit_scan','frame_echo','mirror_corridor','mask_wipe','solarize','datamosh','block_displace','chroma_delay','vhs_tracking','vortex','motion_trails','slice_recursion'].filter(k=>(t[k]??0)>.08).join(',');
    const d=scene.direction??{},align=d.rhythm_alignment?` · sync ${(d.rhythm_alignment*100).toFixed(0)}%`:'';const family=d.effect_family?` · ${d.effect_family}`:'';const vectors=d.vector_effects?.length?` · ${d.vector_effects.length} vector fx`:'';
    clipMeta.textContent=`${scene.term}${scene.motif_id?` · ${scene.motif_id} #${scene.occurrence}`:''} · ${scene.composition_mode} · ${1+(scene.layers?.length??0)} video layers${align}${family}${vectors} · ${scene.title??scene.source_id}${fxNames?` · fx ${fxNames}`:''}`;
  }catch(e){console.warn('scene activation failed',e);clipMeta.textContent=`Clip group unavailable: ${scene.title??scene.source_id}`;}
}

function transformedRect(t,rect){
  const creative=activeScene?.direction?.creative??{};
  const camera=Math.min(1,creativeValue('camera_energy',creative.camera_energy??0)*liveFx.motion);
  const p=directedProgress(),targetX=Number(creative.camera_target_x??.5),targetY=Number(creative.camera_target_y??.5);
  const driftX=Number(creative.camera_drift_x??0),driftY=Number(creative.camera_drift_y??0);
  // Treat high-resolution footage as a virtual camera canvas.  The motion is a
  // smooth phrase envelope plus the existing beat impulse, and aims at the
  // scene's semantic/saliency target rather than dead centre.
  const cameraZoom=1+camera*(.018+.052*(.5-.5*Math.cos(Math.PI*Math.min(1,p))))+punch*.065;
  const zoom=Math.max(1,t.zoom??1)*cameraZoom*(1+punch*.055);
  const availableX=Math.max(0,rect.w*(zoom-1)),availableY=Math.max(0,rect.h*(zoom-1));
  const semanticPanX=(.5-targetX)*availableX*.72+Math.sin(p*Math.PI*1.7+phase*.08)*rect.w*.018*camera*driftX;
  const semanticPanY=(.5-targetY)*availableY*.72+Math.sin(p*Math.PI*1.3+phase*.07)*rect.h*.014*camera*driftY;
  const panX=(t.pan_x??0)*rect.w*.20+semanticPanX,panY=(t.pan_y??0)*rect.h*.20+semanticPanY;
  return{x:rect.x+panX,y:rect.y+panY,w:rect.w*zoom,h:rect.h*zoom};
}
function drawLayer(target,state,rect,alpha=1,blend=null){
  const{video,transform:t,layer}=state;if(video.readyState<2)return;
  target.save();target.globalAlpha=alpha*(layer.opacity??.75);target.globalCompositeOperation=blend||layer.blend_mode||t.blend_mode||'source-over';
  if('filter' in target)target.filter=`brightness(${t.brightness??1}) contrast(${t.contrast??1}) saturate(${t.saturation??1}) hue-rotate(${t.hue_degrees??0}deg) blur(${t.blur_px??0}px) grayscale(${t.grayscale??0})`;
  target.beginPath();target.rect(rect.x,rect.y,rect.w,rect.h);target.clip();
  target.translate(rect.x+rect.w/2,rect.y+rect.h/2);target.rotate((t.rotation_degrees??0)*Math.PI/180);target.scale(t.mirror?-1:1,1);target.translate(-(rect.x+rect.w/2),-(rect.y+rect.h/2));
  const d=transformedRect(t,rect),vw=video.videoWidth||width,vh=video.videoHeight||height,scale=Math.max(d.w/vw,d.h/vh),dw=vw*scale,dh=vh*scale;
  target.drawImage(video,d.x+(d.w-dw)/2,d.y+(d.h-dh)/2,dw,dh);target.restore();
}
function rectFor(mode,index,count){
  // Legacy split/mosaic/pip timelines no longer produce boxed thumbnails.
  return{x:0,y:0,w:width,h:height};
}
function organicMask(target,index,strength=1){
  const t=phase*.55+index*2.13;
  const cx=width*(.50+.27*Math.sin(t*.73+index));
  const cy=height*(.50+.23*Math.cos(t*.61-index*.7));
  const rx=width*(.20+.12*strength+.045*Math.sin(t*.91));
  const ry=height*(.22+.10*strength+.055*Math.cos(t*.79));
  const wobble=.22+.08*Math.sin(t*.43);
  target.beginPath();
  target.moveTo(cx+rx,cy);
  target.bezierCurveTo(cx+rx*(1-wobble),cy-ry*.9,cx+rx*.25,cy-ry*1.08,cx,cy-ry);
  target.bezierCurveTo(cx-rx*.72,cy-ry*.88,cx-rx*1.08,cy-ry*.18,cx-rx,cy);
  target.bezierCurveTo(cx-rx*.92,cy+ry*.78,cx-rx*.18,cy+ry*1.08,cx,cy+ry);
  target.bezierCurveTo(cx+rx*.70,cy+ry*.88,cx+rx*1.07,cy+ry*.25,cx+rx,cy);
  target.closePath();
}
function drawFlowLayer(state,index,alpha){
  fx.save();
  organicMask(fx,index,.65+.2*index);
  fx.clip();
  const blend=index%2?'screen':'overlay';
  drawLayer(fx,state,{x:0,y:0,w:width,h:height},alpha*(.38+.10*Math.sin(phase+index)),blend);
  fx.restore();
}
function drawBank(bankIndex,alpha){
  const states=bankState[bankIndex];if(!states.length)return;let mode=bankMode[bankIndex]??'single';
  if(['pip','split','mosaic'].includes(mode))mode='flow';
  const order=states.map((_,i)=>(i+focusLayer)%states.length);

  if(mode==='flow'&&states.length>1){
    drawLayer(fx,states[order[0]],{x:0,y:0,w:width,h:height},alpha,'source-over');
    for(let oi=1;oi<order.length;oi++)drawFlowLayer(states[order[oi]],oi,alpha);
    return;
  }

  if(mode==='strips'&&states.length>1){
    const strips=10;
    for(let n=0;n<strips;n++){
      const idx=(n+focusLayer)%states.length,base=width/strips;
      const x=n*base+Math.sin(phase*.8+n*.7)*base*.18;
      const w=base*(1.15+.18*Math.sin(phase*.5+n));
      drawLayer(fx,states[idx],{x,y:0,w,h:height},alpha,idx?states[idx].layer.blend_mode:'source-over');
    }
    return;
  }

  for(let oi=0;oi<order.length;oi++){
    const idx=order[oi],state=states[idx];
    let blend=oi===0?'source-over':state.layer.blend_mode,a=alpha;
    if(mode==='luma'&&oi>0){blend=oi%2?'screen':'multiply';a*=.58;}
    drawLayer(fx,state,{x:0,y:0,w:width,h:height},a,blend);
  }
}

function snapshot(){scratchCtx.clearRect(0,0,width,height);scratchCtx.drawImage(videoFx,0,0);}
function applyShutter(amount){
  if(amount<=.03)return;const now=clockNowMs(),interval=26+amount*150;
  if(now>=shutterNext){holdCtx.drawImage(videoFx,0,0);shutterNext=now+interval;return;}
  fx.drawImage(holdCanvas,0,0);
}
function applyRipple(amount){
  if(amount<=.025)return;snapshot();const slices=Math.max(12,Math.min(64,18+Math.floor(amount*55))),sh=height/slices,amp=width*(.004+.035*amount);
  fx.save();fx.globalAlpha=.32+.45*amount;
  for(let i=0;i<slices;i++){const y=i*sh,dx=Math.sin(i*.72+phase*13)*amp*(.35+.65*Math.sin(phase*3+i*.11)**2);fx.drawImage(scratch,0,y,width,sh+1,dx,y,width,sh+1);}
  fx.restore();
}
function applyTiles(amount){
  if(amount<=.035)return;
  snapshot();
  const count=3+Math.floor(amount*5);
  fx.save();fx.globalCompositeOperation='screen';
  for(let i=0;i<count;i++){
    const t=phase*.42+i*1.91;
    const cx=width*(.5+.36*Math.sin(t*.73));
    const cy=height*(.5+.32*Math.cos(t*.61));
    const r=Math.min(width,height)*(.07+.08*amount+.025*Math.sin(t));
    fx.save();
    fx.beginPath();
    fx.ellipse(cx,cy,r*(1.2+.2*Math.sin(t*.7)),r*(.8+.15*Math.cos(t*.9)),t*.13,0,Math.PI*2);
    fx.clip();
    fx.globalAlpha=.05+.16*amount;
    const scale=1.05+.16*amount;
    fx.translate(cx,cy);fx.scale(scale,scale);fx.translate(-cx,-cy);
    fx.drawImage(scratch,0,0,width,height);
    fx.restore();
  }
  fx.restore();
}

function applyKaleidoscope(amount){
  if(amount<=.035)return;
  snapshot();

  // Organic symmetry: the focal point drifts across the frame instead of
  // remaining pinned to dead center. Multiple low-opacity passes with slightly
  // different centers avoid the rigid "bullseye" look.
  const baseX=width*(.50+.16*Math.sin(phase*.37)+.07*Math.sin(phase*.91));
  const baseY=height*(.50+.13*Math.cos(phase*.29)+.06*Math.sin(phase*.73));
  const passes=amount>.45?3:2;

  fx.save();
  fx.globalCompositeOperation='screen';

  for(let pass=0;pass<passes;pass++){
    const drift=pass-(passes-1)/2;
    const cx=baseX+drift*width*(.035+.025*amount)*Math.sin(phase*.61+pass*1.7);
    const cy=baseY+drift*height*(.030+.020*amount)*Math.cos(phase*.53+pass*1.3);
    const segments=4+Math.floor(amount*5)+(pass%2);
    const step=Math.PI*2/segments;
    const radius=Math.hypot(width,height)*(.72+.10*Math.sin(phase*.19+pass));
    const rotation=phase*(.006+.008*amount)+(pass*.19);
    fx.globalAlpha=(.055+.14*amount)/(1+pass*.35);

    for(let i=0;i<segments;i++){
      const start=i*step+rotation;
      const end=(i+1)*step+rotation;

      fx.save();
      fx.beginPath();
      fx.moveTo(cx,cy);
      fx.arc(cx,cy,radius,start,end);
      fx.closePath();
      fx.clip();

      fx.translate(cx,cy);
      fx.rotate(start+step*.5);

      // Alternate reflection, but perturb scale/orientation enough that the
      // symmetry feels fluid rather than architectural.
      if((i+pass)%2)fx.scale(-1,1);
      const sx=.93+amount*.10+.035*Math.sin(phase*.47+i*1.31);
      const sy=.96+amount*.06+.028*Math.cos(phase*.39+i*.93);
      fx.scale(sx,sy);

      const sourceShiftX=Math.sin(phase*.23+i*.71+pass)*width*.055*amount;
      const sourceShiftY=Math.cos(phase*.27+i*.59-pass)*height*.045*amount;
      fx.drawImage(
        scratch,
        -width/2+sourceShiftX,
        -height/2+sourceShiftY,
        width,
        height
      );
      fx.restore();
    }
  }

  // Add a softer mirrored region that wanders independently. This breaks the
  // perfect radial structure and makes the effect feel more like liquid glass.
  if(amount>.16){
    const rw=width*(.28+.16*amount);
    const rh=height*(.32+.12*amount);
    const rx=(.50+.30*Math.sin(phase*.21))*width-rw/2;
    const ry=(.50+.25*Math.cos(phase*.17))*height-rh/2;
    fx.save();
    fx.globalAlpha=.035+.10*amount;
    fx.beginPath();
    fx.ellipse(rx+rw/2,ry+rh/2,rw/2,rh/2,phase*.09,0,Math.PI*2);
    fx.clip();
    fx.translate(rx+rw/2,ry+rh/2);
    fx.rotate(Math.sin(phase*.25)*.18*amount);
    fx.scale(-1,1);
    fx.drawImage(scratch,-rw/2,-rh/2,rw,rh);
    fx.restore();
  }

  fx.restore();
}
function applyTunnel(amount){
  if(amount<=.03)return;
  snapshot();
  const layers=2+Math.floor(amount*7);
  const cx=width*(.50+.14*Math.sin(phase*.31));
  const cy=height*(.50+.11*Math.cos(phase*.27));
  fx.save();fx.globalCompositeOperation='screen';
  for(let i=1;i<=layers;i++){
    const q=i/(layers+1);
    const rx=width*(.42-q*(.18+.18*amount));
    const ry=height*(.40-q*(.16+.16*amount));
    fx.save();
    fx.beginPath();
    fx.ellipse(cx,cy,Math.max(20,rx),Math.max(20,ry),phase*.025*i,0,Math.PI*2);
    fx.clip();
    const scale=1+q*(.035+.16*amount);
    fx.translate(cx,cy);fx.rotate(Math.sin(phase*.4+i*.8)*.035*amount);fx.scale(scale,scale);fx.translate(-cx,-cy);
    fx.globalAlpha=(.025+.085*amount)*(1-q*.48);
    fx.drawImage(scratch,0,0,width,height);
    fx.restore();
  }
  fx.restore();
}

function applyPosterize(amount){
  if(amount<=.04)return;posterCtx.drawImage(videoFx,0,0,posterCanvas.width,posterCanvas.height);const img=posterCtx.getImageData(0,0,posterCanvas.width,posterCanvas.height),d=img.data,levels=Math.max(2,Math.round(8-amount*5)),step=255/(levels-1);
  for(let i=0;i<d.length;i+=4){d[i]=Math.round(d[i]/step)*step;d[i+1]=Math.round(d[i+1]/step)*step;d[i+2]=Math.round(d[i+2]/step)*step;}
  posterCtx.putImageData(img,0,0);fx.save();fx.imageSmoothingEnabled=false;fx.globalAlpha=.18+.62*amount;fx.drawImage(posterCanvas,0,0,width,height);fx.restore();fx.imageSmoothingEnabled=true;
}
function applyEdge(amount){
  if(amount<=.035)return;snapshot();edgeCtx.clearRect(0,0,width,height);edgeCtx.save();if('filter'in edgeCtx)edgeCtx.filter='grayscale(1) contrast(2.2)';edgeCtx.drawImage(scratch,0,0);edgeCtx.globalCompositeOperation='difference';const d=(1.5+amount*5)*devicePixelRatio;edgeCtx.drawImage(scratch,d,d);edgeCtx.restore();fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.10+.52*amount;fx.drawImage(edgeCanvas,0,0);fx.restore();
}
function applyRgbSplit(amount){
  if(amount<=.02)return;snapshot();fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.18+amount*.30;const d=amount*18*devicePixelRatio;fx.drawImage(scratch,d,0);fx.drawImage(scratch,-d,0);fx.restore();
}
function applyPixel(amount){
  if(amount<=.03)return;const scale=Math.max(.06,1-amount*.88);snapshot();scratchCtx.imageSmoothingEnabled=false;posterCtx.imageSmoothingEnabled=false;posterCtx.clearRect(0,0,posterCanvas.width,posterCanvas.height);posterCtx.drawImage(scratch,0,0,posterCanvas.width*scale,posterCanvas.height*scale);fx.save();fx.imageSmoothingEnabled=false;fx.globalAlpha=.45+.45*amount;fx.drawImage(posterCanvas,0,0,posterCanvas.width*scale,posterCanvas.height*scale,0,0,width,height);fx.restore();fx.imageSmoothingEnabled=true;scratchCtx.imageSmoothingEnabled=true;
}
function applyGlitch(amount){
  if(amount<=.02)return;snapshot();fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.12+amount*.35;for(let i=0;i<2+Math.floor(amount*12);i++){const h=Math.max(2,(4+rand()*45*amount)*devicePixelRatio),y=rand()*Math.max(1,height-h),dx=(rand()-.5)*width*.11*amount;fx.drawImage(scratch,0,y,width,h,dx,y,width,h);}fx.restore();
}
function applyFeedback(amount){
  if(amount<=.02)return;fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.04+amount*.18;const d=amount*18*devicePixelRatio;fx.drawImage(history,-d,-d,width+d*2,height+d*2);fx.restore();
}
function applyScanlines(amount){
  if(amount<=.02)return;fx.save();fx.globalAlpha=.05+amount*.18;fx.fillStyle='#000';const step=Math.max(3,Math.floor((5-amount*2)*devicePixelRatio));for(let y=0;y<height;y+=step)fx.fillRect(0,y,width,Math.max(1,devicePixelRatio));fx.restore();
}
function applyVignette(amount){
  if(amount<=.02)return;const g=fx.createRadialGradient(width/2,height/2,Math.min(width,height)*.20,width/2,height/2,Math.max(width,height)*.65);g.addColorStop(0,'rgba(0,0,0,0)');g.addColorStop(1,`rgba(0,0,0,${Math.min(.85,amount)})`);fx.fillStyle=g;fx.fillRect(0,0,width,height);
}
function applyStrobe(amount){
  if(amount<=.035)return;const hz=6+amount*12,p=(clockSeconds()*hz)%1;if(p<.10+.14*amount){fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.18+.62*amount;fx.fillStyle='#fff';fx.fillRect(0,0,width,height);fx.restore();}else if(amount>.55&&p>.72){fx.save();fx.globalCompositeOperation='multiply';fx.globalAlpha=.22*amount;fx.fillStyle='#000';fx.fillRect(0,0,width,height);fx.restore();}
}

function captureDelayFrame(){
  if(frameCounter%3!==0)return;
  const c=delayCtx[delayWrite];
  c.clearRect(0,0,delayBuffers[delayWrite].width,delayBuffers[delayWrite].height);
  c.drawImage(videoFx,0,0,delayBuffers[delayWrite].width,delayBuffers[delayWrite].height);
  delayWrite=(delayWrite+1)%delayBuffers.length;
}
function delayed(age=1){
  const idx=(delayWrite-age+delayBuffers.length*4)%delayBuffers.length;
  return delayBuffers[idx];
}
function applySlitScan(amount){
  if(amount<=.025)return;
  snapshot();
  const stripes=16+Math.floor(amount*42), sh=height/stripes;
  fx.save();
  fx.globalAlpha=.20+.52*amount;
  for(let i=0;i<stripes;i++){
    const source=(i%3===0)?delayed(1):(i%3===1?delayed(2):scratch);
    const y=i*sh;
    const phaseShift=Math.sin(phase*7+i*.61)*width*.022*amount;
    fx.drawImage(source,0,(y/height)*source.height,source.width,(sh/height)*source.height+1,phaseShift,y,width,sh+1);
  }
  fx.restore();
}
function applyFrameEcho(amount){
  if(amount<=.025)return;
  fx.save();
  fx.globalCompositeOperation='screen';
  const taps=3;
  for(let i=1;i<=taps;i++){
    const d=delayed(i),scale=1+i*.018*amount,w=width*scale,h=height*scale;
    fx.globalAlpha=(.035+.12*amount)*(1-(i-1)*.18);
    fx.drawImage(d,(width-w)/2,(height-h)/2,w,h);
  }
  fx.restore();
}
function applyMirrorCorridor(amount){
  if(amount<=.03)return;
  snapshot();
  const bands=4+Math.floor(amount*8),bw=width/bands;
  fx.save();
  fx.globalCompositeOperation='screen';
  fx.globalAlpha=.10+.32*amount;
  for(let i=0;i<bands;i++){
    fx.save();
    const x=i*bw;
    fx.beginPath();fx.rect(x,0,bw+1,height);fx.clip();
    if(i%2){fx.translate(x*2+bw,0);fx.scale(-1,1);}
    const drift=Math.sin(phase*4+i)*height*.025*amount;
    fx.drawImage(scratch,0,drift,width,height);
    fx.restore();
  }
  fx.restore();
}
function applyMaskWipe(amount){
  if(amount<=.025)return;
  const old=delayed(2);
  const p=(clockSeconds()*(.10+.28*amount)+phase*.07)%1;
  fx.save();
  fx.beginPath();
  if(Math.floor(clockSeconds()*.5)%2===0){
    const r=Math.hypot(width,height)*(.08+p*.92);
    fx.arc(width/2,height/2,r,0,Math.PI*2);
  }else{
    const x=(p*1.4-.2)*width;
    fx.moveTo(x-width*.24,0);fx.lineTo(x+width*.18,0);fx.lineTo(x+width*.24,height);fx.lineTo(x-width*.18,height);fx.closePath();
  }
  fx.clip();
  fx.globalAlpha=.12+.42*amount;
  fx.globalCompositeOperation='screen';
  fx.drawImage(old,0,0,width,height);
  fx.restore();
}
function applySolarize(amount){
  if(amount<=.035)return;
  posterCtx.clearRect(0,0,posterCanvas.width,posterCanvas.height);
  posterCtx.drawImage(videoFx,0,0,posterCanvas.width,posterCanvas.height);
  const img=posterCtx.getImageData(0,0,posterCanvas.width,posterCanvas.height),d=img.data;
  const threshold=110+Math.floor((1-amount)*55);
  for(let i=0;i<d.length;i+=4){
    const l=(d[i]+d[i+1]+d[i+2])/3;
    if(l>threshold){d[i]=255-d[i];d[i+1]=255-d[i+1];d[i+2]=255-d[i+2];}
  }
  posterCtx.putImageData(img,0,0);
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.10+.48*amount;
  fx.drawImage(posterCanvas,0,0,width,height);fx.restore();
}
function applyDatamosh(amount){
  if(amount<=.03)return;
  const prev=delayed(1),blocks=4+Math.floor(amount*22);
  fx.save();fx.globalAlpha=.14+.42*amount;fx.globalCompositeOperation='screen';
  for(let i=0;i<blocks;i++){
    const bw=width*(.03+((i*37)%13)/130),bh=height*(.025+((i*19)%11)/120);
    const x=((i*97+frameCounter*7)%1000)/1000*Math.max(1,width-bw);
    const y=((i*53+frameCounter*3)%1000)/1000*Math.max(1,height-bh);
    const dx=Math.sin(i*2.7+phase*9)*width*.06*amount;
    const dy=Math.cos(i*1.9+phase*5)*height*.025*amount;
    fx.drawImage(prev,(x/width)*prev.width,(y/height)*prev.height,(bw/width)*prev.width,(bh/height)*prev.height,x+dx,y+dy,bw,bh);
  }
  fx.restore();
}
function applyBlockDisplace(amount){
  if(amount<=.03)return;
  snapshot();
  const cols=5+Math.floor(amount*9),rows=4+Math.floor(amount*7),bw=width/cols,bh=height/rows;
  fx.save();fx.globalAlpha=.12+.34*amount;
  for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){
    if(((x*7+y*11+frameCounter)%5)>1)continue;
    const ox=Math.sin(x*2.1+y+phase*11)*bw*.65*amount;
    const oy=Math.cos(y*1.7+x+phase*7)*bh*.45*amount;
    fx.drawImage(scratch,x*bw,y*bh,bw+1,bh+1,x*bw+ox,y*bh+oy,bw+1,bh+1);
  }
  fx.restore();
}
function applyChromaDelay(amount){
  if(amount<=.025)return;
  fx.save();fx.globalCompositeOperation='screen';
  const d1=delayed(1),d2=delayed(2),shift=width*.010*amount;
  fx.globalAlpha=.08+.18*amount;
  if('filter'in fx)fx.filter='hue-rotate(115deg) saturate(2)';
  fx.drawImage(d1,shift,0,width,height);
  if('filter'in fx)fx.filter='hue-rotate(-115deg) saturate(2)';
  fx.drawImage(d2,-shift,0,width,height);
  fx.restore();
}
function applyVhsTracking(amount){
  if(amount<=.025)return;
  snapshot();
  const bandH=height*(.015+.055*amount);
  const y=((clockSeconds()*(.18+.45*amount))%1)*(height+bandH)-bandH;
  fx.save();
  fx.globalAlpha=.22+.35*amount;
  const dx=Math.sin(clockSeconds()*31)*width*.025*amount;
  fx.drawImage(scratch,0,y,width,bandH,dx,y,width,bandH);
  fx.globalCompositeOperation='screen';
  fx.fillStyle=`rgba(255,255,255,${.05+.12*amount})`;fx.fillRect(0,y,width,Math.max(1,devicePixelRatio));
  fx.restore();
}
function applyVortex(amount){
  if(amount<=.03)return;
  snapshot();
  const segments=10+Math.floor(amount*18),cx=width/2,cy=height/2,r=Math.hypot(width,height),step=Math.PI*2/segments;
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.055+.24*amount;
  for(let i=0;i<segments;i++){
    fx.save();fx.beginPath();fx.moveTo(cx,cy);fx.arc(cx,cy,r,i*step,(i+1)*step);fx.closePath();fx.clip();
    fx.translate(cx,cy);fx.rotate(Math.sin(i*.9+phase*4)*amount*.20+i*step*.08);
    const sc=1+.04*amount*Math.sin(i+phase*3);fx.scale(sc,sc);fx.drawImage(scratch,-width/2,-height/2);fx.restore();
  }
  fx.restore();
}
function applyMotionTrails(amount){
  if(amount<=.025)return;
  snapshot();
  fx.save();fx.globalCompositeOperation='difference';fx.globalAlpha=.08+.25*amount;fx.drawImage(delayed(1),0,0,width,height);fx.restore();
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.05+.16*amount;fx.drawImage(delayed(2),-width*.008*amount,0,width,height);fx.restore();
}
function applySliceRecursion(amount){
  if(amount<=.03)return;
  snapshot();
  const slices=6+Math.floor(amount*16),sh=height/slices;
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.08+.28*amount;
  for(let i=0;i<slices;i++){
    const y=i*sh,q=(i%4)/4,scale=1-(.05+.20*amount)*(q+.15),w=width*scale;
    const dx=(width-w)/2+Math.sin(i+phase*6)*width*.012*amount;
    fx.drawImage(scratch,0,y,width,sh+1,dx,y,w,sh+1);
  }
  fx.restore();
}

function applyBeatWarp(amount,low,mid,high){
  if(amount<=.025)return;
  snapshot();
  const bass=Math.min(1,amount*low),mids=Math.min(1,amount*mid),treble=Math.min(1,amount*high);
  const cx=width*(.50+.10*Math.sin(phase*.37));
  const cy=height*(.52+.08*Math.cos(phase*.31));

  if(bass>.02){
    fx.save();fx.globalCompositeOperation='screen';
    const rings=3+Math.floor(bass*5);
    for(let i=rings;i>=1;i--){
      const q=i/rings,r=Math.min(width,height)*(.10+.34*q);
      fx.save();fx.beginPath();fx.arc(cx,cy,r,0,Math.PI*2);fx.clip();
      const scale=1+bass*(.025+.055*(1-q));
      fx.translate(cx,cy);fx.scale(scale,scale);fx.translate(-cx,-cy);
      fx.globalAlpha=.035+.12*bass*(1-q*.35);
      fx.drawImage(scratch,0,0,width,height);fx.restore();
    }
    fx.restore();
  }

  if(mids>.02){
    fx.save();fx.globalAlpha=.08+.22*mids;
    const slices=13,sh=height/slices;
    for(let i=0;i<slices;i++){
      const y=i*sh;
      const dx=Math.sin(i*.8+phase*10)*width*.016*mids;
      const skew=Math.cos(i*.43+phase*6)*sh*.22*mids;
      fx.drawImage(scratch,0,y,width,sh+1,dx,y+skew,width,sh+1);
    }
    fx.restore();
  }

  if(treble>.02){
    fx.save();fx.globalCompositeOperation='screen';
    const shift=width*(.003+.014*treble);
    fx.globalAlpha=.04+.15*treble;
    if('filter'in fx)fx.filter='hue-rotate(105deg) saturate(1.8)';
    fx.drawImage(scratch,shift,0,width,height);
    if('filter'in fx)fx.filter='hue-rotate(-105deg) saturate(1.8)';
    fx.drawImage(scratch,-shift,0,width,height);
    fx.restore();
  }
}
function applyTempoWarp(amount){
  if(amount<=.025)return;
  snapshot();
  const bands=18,sh=height/bands;
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.04+.18*amount;
  for(let i=0;i<bands;i++){
    const y=i*sh,q=i/(bands-1);
    const dx=Math.sin(phase*4+q*Math.PI*3)*width*.028*amount;
    const scale=1+.018*amount*Math.sin(phase*3+q*Math.PI*2);
    fx.drawImage(scratch,0,y,width,sh+1,dx,y,width*scale,sh+1);
  }
  fx.restore();
}

function directedProgress(){
  if(!activeScene)return 0;
  const start=Number(activeScene.time??0),now=offlineMode?offlineTime:clockSeconds();
  let end=timeline.track.duration;
  const plan=timeline.scene_plan??[];
  const idx=plan.findIndex(x=>x.scene_id===activeScene.scene_id&&Math.abs((x.time??0)-start)<1e-5);
  if(idx>=0&&idx+1<plan.length)end=Number(plan[idx+1].time);
  return Math.max(0,Math.min(1,(now-start)/Math.max(.05,end-start)));
}
function automationValue(name,fallback=0){
  const points=activeScene?.direction?.automation?.[name];
  if(!Array.isArray(points)||!points.length)return fallback;
  const p=directedProgress();
  if(p<=points[0][0])return Number(points[0][1]);
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];
    if(p<=b[0]){
      const q=(p-a[0])/Math.max(1e-6,b[0]-a[0]);
      return Number(a[1])+(Number(b[1])-Number(a[1]))*q;
    }
  }
  return Number(points[points.length-1][1]);
}
function creativeValue(name,fallback=0){
  const creative=activeScene?.direction?.creative;
  if(!creative)return fallback;
  const points=creative.automation?.[name];
  if(!Array.isArray(points)||!points.length)return Number(creative[name]??fallback);
  const p=directedProgress();
  if(p<=points[0][0])return Number(points[0][1]);
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];
    if(p<=b[0]){const q=(p-a[0])/Math.max(1e-6,b[0]-a[0]);return Number(a[1])+(Number(b[1])-Number(a[1]))*q;}
  }
  return Number(points[points.length-1][1]);
}
function creativeTarget(){
  const c=activeScene?.direction?.creative??{};
  return{x:Number(c.camera_target_x??.5)*width,y:Number(c.camera_target_y??.5)*height,r:Number(c.semantic?.subject_radius??.28)*Math.min(width,height)};
}
function preserveCreativeSubject(amount){
  if(amount<=.02)return;
  const {x,y,r}=creativeTarget(),c=activeScene?.direction?.creative??{},semantic=Math.max(Number(c.semantic?.person??0),Number(c.semantic?.face??0),Number(c.semantic?.text??0));
  // Strong semantic subjects get a content-derived foreground mask.  It is
  // intentionally coarse and feathered by canvas resampling: focal proximity and
  // color continuity protect the actual subject rather than a permanent ellipse.
  if(amount>.12&&semantic>.18){
    const map=updateCreativeDepth();
    if(map.cells.length){
      const image=subjectMaskCtx.createImageData(map.cols,map.rows);
      for(const cell of map.cells){const a=Math.max(0,Math.min(1,cell.subject??0));const i=(cell.y*map.cols+cell.x)*4;image.data[i]=image.data[i+1]=image.data[i+2]=255;image.data[i+3]=Math.round(255*a);}
      subjectMaskCtx.clearRect(0,0,map.cols,map.rows);subjectMaskCtx.putImageData(image,0,0);
      subjectLayerCtx.clearRect(0,0,width,height);subjectLayerCtx.globalCompositeOperation='source-over';subjectLayerCtx.globalAlpha=1;subjectLayerCtx.drawImage(scratch,0,0,width,height);
      subjectLayerCtx.globalCompositeOperation='destination-in';subjectLayerCtx.imageSmoothingEnabled=true;subjectLayerCtx.drawImage(subjectMask,0,0,width,height);subjectLayerCtx.globalCompositeOperation='source-over';
      fx.save();fx.globalCompositeOperation='source-over';fx.globalAlpha=.12+.43*amount;fx.drawImage(subjectLayer,0,0,width,height);fx.restore();
    }
  }
  fx.save();fx.globalCompositeOperation='source-over';
  // A low-amplitude feather remains as a fallback and prevents hard mask seams.
  for(let i=4;i>=1;i--){const q=i/4;fx.save();fx.beginPath();fx.ellipse(x,y,r*(.75+.25*q),r*(1.02+.20*q),0,0,Math.PI*2);fx.clip();fx.globalAlpha=(.025+.075*amount)*(1.15-q*.15);fx.drawImage(scratch,0,0,width,height);fx.restore();}
  fx.restore();
}
function applyFlowWarpCreative(amount){
  if(amount<=.02)return;const flow=updateOpticalFlow().field;if(!flow.length)return;snapshot();
  const subject=activeScene?.direction?.creative?.subject_preserve??0,{x:cx,y:cy,r}=creativeTarget();
  fx.save();fx.globalAlpha=.10+.34*amount;
  const max=Math.min(60,flow.length);
  for(let i=0;i<max;i++){const v=flow[i];const px=v.x*width,py=v.y*height,dist=Math.hypot(px-cx,py-cy);const protect=dist<r?1-subject*.78:1;if(protect<.15)continue;const pw=width*.075*(.6+.8*v.strength),ph=height*.09*(.6+.8*v.strength);const sx=Math.max(0,Math.min(width-pw,px-pw/2)),sy=Math.max(0,Math.min(height-ph,py-ph/2));const dx=v.vx*width*.040*amount*v.strength*protect,dy=v.vy*height*.055*amount*v.strength*protect;fx.drawImage(scratch,sx,sy,pw,ph,sx+dx,sy+dy,pw,ph);}
  fx.restore();preserveCreativeSubject(subject*amount);
}
function applyFlowRgbCreative(amount){
  if(amount<=.02)return;const flow=updateOpticalFlow().field;if(!flow.length)return;snapshot();
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.035+.13*amount;
  for(const [hue,sign] of [[110,1],[-120,-1]]){if('filter'in fx)fx.filter=`hue-rotate(${hue}deg) saturate(1.9)`;for(const v of flow.slice(0,28)){const pw=width*.08,ph=height*.10,px=v.x*width,py=v.y*height,sx=Math.max(0,Math.min(width-pw,px-pw/2)),sy=Math.max(0,Math.min(height-ph,py-ph/2));fx.drawImage(scratch,sx,sy,pw,ph,sx+sign*v.vx*width*.026*amount,sy+sign*v.vy*height*.035*amount,pw,ph);}}
  fx.restore();
}
function applyTemporalRgbCreative(amount){
  if(amount<=.02)return;fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.045+.16*amount;const shift=width*.007*amount;
  if('filter'in fx)fx.filter='hue-rotate(115deg) saturate(2.0)';fx.drawImage(delayed(1),shift,0,width,height);
  if('filter'in fx)fx.filter='hue-rotate(-125deg) saturate(2.0)';fx.drawImage(delayed(2),-shift,0,width,height);fx.restore();
}
function applyTemporalSmearCreative(amount){
  if(amount<=.02)return;snapshot();const bands=18+Math.floor(amount*24),sh=height/bands;fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.045+.20*amount;
  for(let i=0;i<bands;i++){const y=i*sh,src=(i%3===0)?delayed(2):(i%2?delayed(1):scratch),dx=Math.sin(i*.71+phase*2.7)*width*.025*amount;fx.drawImage(src,0,(y/height)*src.height,src.width,(sh/height)*src.height+1,dx,y,width,sh+1);}fx.restore();
}
function updateCreativeDepth(){
  if(creativeDepthCache.frame>=0&&frameCounter-creativeDepthCache.frame<3)return creativeDepthCache;
  const cols=16,rows=9,c=activeScene?.direction?.creative??{},sem=c.semantic??{},target=creativeTarget();
  depthProbeCtx.clearRect(0,0,cols,rows);depthProbeCtx.drawImage(scratch,0,0,cols,rows);
  let data;try{data=depthProbeCtx.getImageData(0,0,cols,rows).data;}catch(_){return creativeDepthCache;}
  const cells=[],tx=Math.max(0,Math.min(cols-1,Math.floor((target.x/width)*cols))),ty=Math.max(0,Math.min(rows-1,Math.floor((target.y/height)*rows))),ti=(ty*cols+tx)*4,tr=data[ti],tg=data[ti+1],tb=data[ti+2],semSubject=Math.max(Number(sem.person??0),Number(sem.face??0),Number(sem.text??0)),radius=Math.max(.08,target.r/Math.min(width,height));
  for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){
    const i=(y*cols+x)*4,r=data[i],g=data[i+1],b=data[i+2],mx=Math.max(r,g,b),mn=Math.min(r,g,b),sat=(mx-mn)/255,lum=(.2126*r+.7152*g+.0722*b)/255;
    const nx=(x+.5)/cols,ny=(y+.5)/rows,dx=(nx-target.x/width),dy=(ny-target.y/height),rad=Math.hypot(dx,dy),colorDist=Math.hypot(r-tr,g-tg,b-tb)/441.673;
    const proximity=Math.max(0,1-rad/(radius*1.35)),subject=proximity*(.36+.64*Math.max(0,1-colorDist*1.35))*(.35+.65*semSubject);
    // 0 is near and 1 is far. Perspective, image contrast, focal-region
    // continuity and scene semantics form a cheap content-derived depth proxy.
    let depth=.18+.56*(1-ny)+.10*(1-sat)+.06*(1-lum);
    if(semSubject>.05)depth-=subject*.48;
    if(Number(sem.sky??0)>.1&&ny<.48)depth+=.16*Number(sem.sky);
    if(Number(sem.architecture??0)>.1)depth+=.05*Math.abs(nx-.5)*Number(sem.architecture);
    cells.push({x,y,depth:Math.max(0,Math.min(1,depth)),lum,sat,subject:Math.max(0,Math.min(1,subject))});
  }
  creativeDepthCache={frame:frameCounter,cells,cols,rows};return creativeDepthCache;
}
function applyDepthParallaxCreative(amount){
  if(amount<=.02)return;snapshot();const c=activeScene?.direction?.creative??{},target=creativeTarget(),map=updateCreativeDepth();
  const dirX=Number(c.camera_drift_x??0),dirY=Number(c.camera_drift_y??0),cw=width/map.cols,ch=height/map.rows;fx.save();fx.globalAlpha=.09+.25*amount;
  for(const cell of map.cells){const d=(cell.depth-.50)*amount,focus=1-Math.min(1,Math.hypot((cell.x+.5)*cw-target.x,(cell.y+.5)*ch-target.y)/(Math.min(width,height)*.55));const dx=(dirX*.74+Math.sin(phase*.3+cell.y*.51+cell.x*.13)*.26)*width*.034*d,dy=(dirY*.64+Math.cos(phase*.27+cell.x*.37)*.18)*height*.024*d,expand=1+.026*amount*Math.abs(d)+.008*amount*focus;const sx=cell.x*cw,sy=cell.y*ch,dw=cw*expand,dh=ch*expand;fx.drawImage(scratch,sx,sy,cw+1,ch+1,sx+dx-(dw-cw)/2,sy+dy-(dh-ch)/2,dw+1,dh+1);}
  fx.restore();preserveCreativeSubject((c.subject_preserve??0)*amount);
  const fog=Number(c.depth_fog??0)*amount;if(fog>.02){const g=fx.createLinearGradient(0,0,0,height);g.addColorStop(0,`rgba(205,225,255,${.04+.13*fog})`);g.addColorStop(.55,'rgba(180,205,235,0)');g.addColorStop(1,'rgba(0,0,0,0)');fx.save();fx.globalCompositeOperation='screen';fx.fillStyle=g;fx.fillRect(0,0,width,height);fx.restore();}
}
function applyBackgroundWarpCreative(amount){
  if(amount<=.02)return;snapshot();const {x,y,r}=creativeTarget(),c=activeScene?.direction?.creative??{};fx.save();
  // Two broad displaced passes move the environment while the subject region is restored.
  fx.globalCompositeOperation='screen';fx.globalAlpha=.045+.17*amount;const dx=Math.sin(phase*.8)*width*.020*amount,dy=Math.cos(phase*.67)*height*.014*amount;fx.drawImage(scratch,dx,dy,width,height);fx.drawImage(scratch,-dx*.65,-dy*.65,width,height);fx.restore();preserveCreativeSubject((c.subject_preserve??0)*amount);
}
function applyRecursiveFeedbackCreative(amount){
  if(amount<=.02)return;const c=activeScene?.direction?.creative??{},target=creativeTarget(),scale=1+Number(c.feedback_scale??.004)*(.35+.9*amount),rot=Number(c.feedback_rotation??0)*Math.PI/180*amount;
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.025+.13*amount;fx.translate(target.x,target.y);fx.rotate(rot);fx.scale(scale,scale);fx.translate(-target.x,-target.y);fx.drawImage(history,0,0,width,height);fx.restore();
}
function applyLocalSymmetryCreative(amount){
  if(amount<=.025)return;snapshot();const c=activeScene?.direction?.creative??{},target=creativeTarget(),segments=Math.max(2,Math.min(12,Number(c.symmetry_segments??4))),radius=Math.min(width,height)*(.13+.16*amount),step=Math.PI*2/segments;
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.035+.12*amount;fx.beginPath();fx.arc(target.x,target.y,radius*1.15,0,Math.PI*2);fx.clip();
  for(let i=0;i<segments;i++){fx.save();fx.translate(target.x,target.y);fx.rotate(i*step+phase*.015*amount);if(i%2)fx.scale(-1,1);const sc=1+.025*Math.sin(phase*.23+i);fx.scale(sc,sc);fx.translate(-target.x,-target.y);fx.drawImage(scratch,0,0,width,height);fx.restore();}
  fx.restore();
}
function applySourceTextureCreative(bloomAmount,streakAmount){
  if(bloomAmount<=.02&&streakAmount<=.02)return;snapshot();
  if(bloomAmount>.02){fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.035+.16*bloomAmount;if('filter'in fx)fx.filter=`brightness(${1.25+.55*bloomAmount}) contrast(${1.15+.55*bloomAmount}) blur(${2+8*bloomAmount}px)`;fx.drawImage(scratch,0,0,width,height);fx.restore();}
  if(streakAmount>.02){posterCtx.clearRect(0,0,posterCanvas.width,posterCanvas.height);if('filter'in posterCtx)posterCtx.filter=`brightness(${1.35+.7*streakAmount}) contrast(${1.7+.8*streakAmount})`;posterCtx.drawImage(scratch,0,0,posterCanvas.width,posterCanvas.height);posterCtx.filter='none';fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.025+.11*streakAmount;const strips=14;for(let i=0;i<strips;i++){const sx=i*posterCanvas.width/strips,sw=Math.max(1,posterCanvas.width/strips*.55),dx=i*width/strips+Math.sin(i+phase*.4)*width*.012*streakAmount;fx.drawImage(posterCanvas,sx,0,sw,posterCanvas.height,dx,0,width/strips*(.55+.7*streakAmount),height);}fx.restore();}
}
function applyPaletteCreative(amount){
  if(amount<=.02)return;const palette=activeScene?.direction?.color?.palette??[];if(!palette.length)return;const target=creativeTarget();const g=fx.createLinearGradient(target.x-width*.35,target.y-height*.25,target.x+width*.45,target.y+height*.30);const usable=palette.slice(0,Math.min(5,palette.length));usable.forEach((color,i)=>g.addColorStop(i/Math.max(1,usable.length-1),color));fx.save();fx.globalCompositeOperation='soft-light';fx.globalAlpha=.025+.14*amount;fx.fillStyle=g;fx.fillRect(0,0,width,height);fx.restore();
}
function heroEnvelope(){
  const c=activeScene?.direction?.creative??{},amount=Number(c.hero_amount??0);if(!c.hero_kind||amount<=0)return 0;const p=directedProgress(),a=Number(c.hero_start??0),b=Number(c.hero_end??1);if(p<a||p>b)return 0;const q=(p-a)/Math.max(1e-6,b-a),attack=Math.min(1,q/.16),release=Math.min(1,(1-q)/.22);const smooth=x=>x*x*(3-2*x);return amount*Math.min(smooth(attack),smooth(release));
}
function applyHeroCreative(){
  const c=activeScene?.direction?.creative??{},a=heroEnvelope();if(a<=.02)return;
  switch(c.hero_kind){
    case'subject_echo':applyTemporalSmearCreative(.55*a);applyTemporalRgbCreative(.38*a);preserveCreativeSubject(Math.min(1,(c.subject_preserve??.6)+.25)*a);break;
    case'flow_melt':applyFlowWarpCreative(.92*a);applyTemporalSmearCreative(.55*a);applyFlowRgbCreative(.35*a);break;
    case'depth_burst':applyDepthParallaxCreative(.92*a);applyRecursiveFeedbackCreative(.58*a);break;
    case'recursive_portal':applyLocalSymmetryCreative(.78*a);applyRecursiveFeedbackCreative(.82*a);applySourceTextureCreative(.42*a,.26*a);break;
    case'time_prism':default:applyTemporalRgbCreative(.68*a);applyTemporalSmearCreative(.48*a);applyLocalSymmetryCreative(.40*a);applyBlockDisplace(.26*a);break;
  }
}

function applyDirectedColor(){
  const dir=activeScene?.direction;if(!dir)return;
  const color=dir.color??{},hue=automationValue('hue',color.hue_shift_degrees??0);
  const sat=automationValue('saturation',color.saturation_scale??1);
  const contrast=color.contrast_scale??1,brightness=color.brightness_scale??1;
  if(Math.abs(hue)<.2&&Math.abs(sat-1)<.01&&Math.abs(contrast-1)<.01&&Math.abs(brightness-1)<.01)return;
  snapshot();
  fx.save();
  if('filter'in fx)fx.filter=`hue-rotate(${hue}deg) saturate(${sat}) contrast(${contrast}) brightness(${brightness})`;
  fx.globalAlpha=.28+.34*Math.min(1,Math.abs(hue)/90+.25*Math.abs(sat-1));
  fx.globalCompositeOperation='source-over';
  fx.drawImage(scratch,0,0,width,height);
  fx.restore();
}
function applySpectralDisplacement(amount){
  if(amount<=.015)return;
  snapshot();
  const dir=activeScene?.direction??{},motion=dir.motion??.3,complexity=dir.complexity??.4;
  const bands=18+Math.floor(22*amount),sh=height/bands;
  const dxBase=width*(.006+.040*amount);
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.06+.24*amount;
  for(let i=0;i<bands;i++){
    const y=i*sh,q=i/Math.max(1,bands-1);
    const freq=2.4+complexity*5.5;
    const dx=Math.sin(q*Math.PI*freq+phase*(5+motion*9))*dxBase*(.4+.6*Math.sin(phase+i*.17)**2);
    const dy=Math.cos(q*Math.PI*3+phase*3.1)*height*.004*amount;
    fx.drawImage(scratch,0,y,width,sh+1,dx,y+dy,width,sh+1);
  }
  fx.restore();
}
function applyPrismaticShift(amount){
  if(amount<=.015)return;
  snapshot();
  const color=activeScene?.direction?.color??{};
  const shift=width*(.002+.018*amount);
  const angle=(color.target_hue??180)*Math.PI/180;
  const dx=Math.cos(angle)*shift,dy=Math.sin(angle)*shift*.5;
  fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.08+.25*amount;
  if('filter'in fx)fx.filter='hue-rotate(95deg) saturate(1.7)';
  fx.drawImage(scratch,dx,dy,width,height);
  if('filter'in fx)fx.filter='hue-rotate(-110deg) saturate(1.8)';
  fx.drawImage(scratch,-dx,-dy,width,height);
  fx.restore();
}
function resetVectorMotionState(){
  vectorFlowInitialized=false;vectorFlowCache={frame:-1,field:[],cols:0,rows:0,ready:false};
  flowPrevCtx.fillStyle='#000';flowPrevCtx.fillRect(0,0,flowPrev.width,flowPrev.height);
  motionPrevCtx.fillStyle='#000';motionPrevCtx.fillRect(0,0,motionPrev.width,motionPrev.height);
}
function vectorRand(seed,index=0){
  let x=(Number(seed||1)+index*0x9e3779b9)>>>0;
  x^=x<<13;x^=x>>>17;x^=x<<5;
  return (x>>>0)/4294967296;
}
function effectCurveValue(effect,name,fallback=null){
  const points=effect?.automation?.[name];
  if(!Array.isArray(points)||!points.length)return fallback??effect?.[name]??effect?.amount??0;
  const p=directedProgress();
  if(p<=points[0][0])return Number(points[0][1]);
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];
    if(p<=b[0]){
      const q=(p-a[0])/Math.max(1e-6,b[0]-a[0]);
      return Number(a[1])+(Number(b[1])-Number(a[1]))*q;
    }
  }
  return Number(points[points.length-1][1]);
}
function vectorColor(effect,alpha=1,hueOffset=0){
  const c=activeScene?.direction?.color??{},base=Number(c.target_hue??190);
  const hue=(base+hueOffset+360)%360;
  const sat=65+25*Math.min(1,activeScene?.direction?.motion_match??.5);
  const light=55+20*Math.min(1,sectionEnergy);
  return `hsla(${hue},${sat}%,${light}%,${Math.max(0,Math.min(1,alpha))})`;
}
function percentile(values,q){
  if(!values.length)return 0;
  const sorted=[...values].sort((a,b)=>a-b),i=Math.max(0,Math.min(sorted.length-1,Math.floor((sorted.length-1)*q)));
  return sorted[i];
}
function rdp(points,epsilon){
  if(points.length<3)return points.slice();
  const a=points[0],b=points[points.length-1],dx=b.x-a.x,dy=b.y-a.y,den=Math.hypot(dx,dy)||1;
  let max=0,index=0;
  for(let i=1;i<points.length-1;i++){
    const p=points[i],d=Math.abs(dy*p.x-dx*p.y+b.x*a.y-b.y*a.x)/den;
    if(d>max){max=d;index=i;}
  }
  if(max<=epsilon)return[a,b];
  const left=rdp(points.slice(0,index+1),epsilon),right=rdp(points.slice(index),epsilon);
  return left.slice(0,-1).concat(right);
}
function chaikin(points,iterations=1){
  let out=points.slice();
  for(let k=0;k<iterations;k++){
    if(out.length<3)break;
    const next=[out[0]];
    for(let i=0;i<out.length-1;i++){
      const a=out[i],b=out[i+1];
      next.push({x:.75*a.x+.25*b.x,y:.75*a.y+.25*b.y,mag:(a.mag+b.mag)*.5,sal:(a.sal+b.sal)*.5});
      next.push({x:.25*a.x+.75*b.x,y:.25*a.y+.75*b.y,mag:(a.mag+b.mag)*.5,sal:(a.sal+b.sal)*.5});
    }
    next.push(out[out.length-1]);out=next;
  }
  return out;
}
function pathArcLength(path){let d=0;for(let i=1;i<path.length;i++)d+=Math.hypot(path[i].x-path[i-1].x,path[i].y-path[i-1].y);return d;}
function pathCentroid(path){let x=0,y=0;for(const p of path){x+=p.x;y+=p.y;}return{x:x/Math.max(1,path.length),y:y/Math.max(1,path.length)};}
function resamplePath(path,count){
  if(path.length<=1||count<=2)return path.slice();const dist=[0];for(let i=1;i<path.length;i++)dist.push(dist[i-1]+Math.hypot(path[i].x-path[i-1].x,path[i].y-path[i-1].y));const total=dist[dist.length-1]||1,out=[];
  for(let k=0;k<count;k++){const target=total*k/(count-1);let i=1;while(i<dist.length&&dist[i]<target)i++;if(i>=dist.length){out.push({...path[path.length-1]});continue;}const a=path[i-1],b=path[i],q=(target-dist[i-1])/Math.max(1e-6,dist[i]-dist[i-1]);out.push({x:a.x+(b.x-a.x)*q,y:a.y+(b.y-a.y)*q,mag:(a.mag??0)+((b.mag??0)-(a.mag??0))*q,sal:(a.sal??0)+((b.sal??0)-(a.sal??0))*q});}
  return out;
}
function stabilizeContourPaths(current,previous){
  if(!previous?.length)return current;
  const used=new Set();
  return current.map(path=>{
    const c=pathCentroid(path.points);let best=-1,score=1e9;
    for(let i=0;i<previous.length;i++){if(used.has(i))continue;const old=previous[i],oc=pathCentroid(old.points),d=Math.hypot(c.x-oc.x,c.y-oc.y),ratio=Math.abs(Math.log((path.arc+1)/(old.arc+1)));const s=d*3+ratio;if(s<score){score=s;best=i;}}
    if(best<0||score>.38)return path;used.add(best);let old=previous[best].points;
    const n=Math.min(path.points.length,old.length);if(n<3)return path;let cur=resamplePath(path.points,n),prev=resamplePath(old,n);
    const same=Math.hypot(cur[0].x-prev[0].x,cur[0].y-prev[0].y)+Math.hypot(cur[n-1].x-prev[n-1].x,cur[n-1].y-prev[n-1].y),rev=Math.hypot(cur[0].x-prev[n-1].x,cur[0].y-prev[n-1].y)+Math.hypot(cur[n-1].x-prev[0].x,cur[n-1].y-prev[0].y);if(rev<same)prev=prev.reverse();
    cur=cur.map((p,i)=>({...p,x:p.x*.72+prev[i].x*.28,y:p.y*.72+prev[i].y*.28}));return{...path,points:cur};
  });
}
function orderedComponentPaths(binary,mags,w,h){
  const visited=new Uint8Array(w*h),paths=[],dirs=[[-1,-1],[0,-1],[1,-1],[-1,0],[1,0],[-1,1],[0,1],[1,1]];
  const neighbors=i=>{const x=i%w,y=(i/w)|0,out=[];for(const[dX,dY]of dirs){const nx=x+dX,ny=y+dY;if(nx>0&&nx<w-1&&ny>0&&ny<h-1){const n=ny*w+nx;if(binary[n])out.push(n);}}return out;};
  const starts=[];
  for(let i=0;i<binary.length;i++)if(binary[i]){const degree=neighbors(i).length;if(degree<=1)starts.push(i);}
  for(let i=0;i<binary.length;i++)if(binary[i])starts.push(i);
  for(const start of starts){
    if(visited[start]||!binary[start])continue;
    const component=[],queue=[start];visited[start]=1;
    while(queue.length){const cur=queue.pop();component.push(cur);for(const n of neighbors(cur))if(!visited[n]){visited[n]=1;queue.push(n);}}
    if(component.length<6)continue;
    const set=new Set(component),degree1=component.filter(i=>neighbors(i).filter(n=>set.has(n)).length===1);
    let cur=degree1[0]??component.reduce((best,i)=>mags[i]>mags[best]?i:best,component[0]),prev=-1,angle=null;
    const ordered=[],remaining=new Set(component);
    while(cur>=0&&remaining.has(cur)){
      remaining.delete(cur);const x=cur%w,y=(cur/w)|0;ordered.push({x,y,mag:mags[cur],sal:mags[cur]});
      const options=neighbors(cur).filter(n=>remaining.has(n));if(!options.length)break;
      let best=options[0],bestScore=1e9;
      for(const n of options){const nx=n%w,ny=(n/w)|0,a=Math.atan2(ny-y,nx-x);let turn=angle===null?0:Math.abs(Math.atan2(Math.sin(a-angle),Math.cos(a-angle)));const score=turn*.9-(mags[n]/255)*.25;if(score<bestScore){bestScore=score;best=n;}}
      const bx=best%w,by=(best/w)|0;angle=Math.atan2(by-y,bx-x);prev=cur;cur=best;
    }
    // Branchy components may contain useful leftovers. Trace them separately.
    if(ordered.length>=6)paths.push(ordered);
    while(remaining.size>=6){
      let seed=[...remaining][0],sub=[],last=-1,cur2=seed,a0=null;
      while(cur2>=0&&remaining.has(cur2)){remaining.delete(cur2);const x=cur2%w,y=(cur2/w)|0;sub.push({x,y,mag:mags[cur2],sal:mags[cur2]});const opts=neighbors(cur2).filter(n=>remaining.has(n));if(!opts.length)break;let best=opts[0],score=1e9;for(const n of opts){const nx=n%w,ny=(n/w)|0,a=Math.atan2(ny-y,nx-x);const turn=a0===null?0:Math.abs(Math.atan2(Math.sin(a-a0),Math.cos(a-a0)));if(turn<score){score=turn;best=n;}}const bx=best%w,by=(best/w)|0;a0=Math.atan2(by-y,bx-x);last=cur2;cur2=best;}
      if(sub.length>=6)paths.push(sub);
    }
  }
  return paths;
}
function extractVectorEdges(force=false){
  if(!force&&vectorEdgeCache.frame>=0&&frameCounter-vectorEdgeCache.frame<4)return vectorEdgeCache;
  const w=vectorSample.width,h=vectorSample.height;
  vectorSampleCtx.drawImage(videoFx,0,0,w,h);
  let data;try{data=vectorSampleCtx.getImageData(0,0,w,h).data;}catch{return vectorEdgeCache;}
  const lum=new Float32Array(w*h),mag=new Float32Array(w*h),ang=new Float32Array(w*h);let mean=0;
  for(let i=0,p=0;i<lum.length;i++,p+=4){const y=.2126*data[p]+.7152*data[p+1]+.0722*data[p+2];lum[i]=y;mean+=y;}mean/=lum.length;
  const candidates=[];
  for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){
    const i=y*w+x,gx=-lum[i-w-1]-2*lum[i-1]-lum[i+w-1]+lum[i-w+1]+2*lum[i+1]+lum[i+w+1],gy=-lum[i-w-1]-2*lum[i-w]-lum[i-w+1]+lum[i+w-1]+2*lum[i+w]+lum[i+w+1];
    const m=Math.hypot(gx,gy);mag[i]=m;ang[i]=Math.atan2(gy,gx);if(m>25)candidates.push(m);
  }
  const high=Math.max(95,percentile(candidates,.82)),low=high*.46,nms=new Float32Array(w*h);
  for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){
    const i=y*w+x,m=mag[i];if(m<low)continue;let deg=(ang[i]*180/Math.PI+180)%180,a=i-1,b=i+1;
    if(deg>=22.5&&deg<67.5){a=i-w-1;b=i+w+1;}else if(deg>=67.5&&deg<112.5){a=i-w;b=i+w;}else if(deg>=112.5&&deg<157.5){a=i-w+1;b=i+w-1;}
    if(m>=mag[a]&&m>=mag[b])nms[i]=m;
  }
  const binary=new Uint8Array(w*h),stack=[];
  for(let i=0;i<nms.length;i++)if(nms[i]>=high){binary[i]=1;stack.push(i);}
  const dirs=[-w-1,-w,-w+1,-1,1,w-1,w,w+1];
  while(stack.length){const i=stack.pop(),x=i%w;for(const d of dirs){const n=i+d;if(n<=0||n>=nms.length-1)continue;const nx=n%w;if(Math.abs(nx-x)>1)continue;if(!binary[n]&&nms[n]>=low){binary[n]=1;stack.push(n);}}}
  const rawPaths=orderedComponentPaths(binary,nms,w,h),paths=[];
  for(const raw of rawPaths){
    const arc=pathArcLength(raw),xs=raw.map(p=>p.x),ys=raw.map(p=>p.y),bw=Math.max(...xs)-Math.min(...xs),bh=Math.max(...ys)-Math.min(...ys);
    if(arc<10||Math.max(bw, bh)<5)continue;
    let path=rdp(raw,1.25);if(path.length<3)continue;path=chaikin(path,1);
    const score=arc*(raw.reduce((a,p)=>a+p.mag,0)/raw.length)/high;
    paths.push({points:path.map(p=>({x:p.x/(w-1),y:p.y/(h-1),mag:p.mag,sal:p.sal})),score,arc,bboxArea:(bw*bh)/(w*h)});
  }
  paths.sort((a,b)=>b.score-a.score);
  // Keep a small number of long, meaningful contours. This is the main anti-hair gate.
  let kept=paths.filter(p=>p.arc>=12&&p.bboxArea>.0015).slice(0,22);
  kept=stabilizeContourPaths(kept,vectorEdgeCache.paths);
  const salientPaths=kept.filter(p=>p.bboxArea>.008||p.arc>22).slice(0,10);
  const points=[];for(const path of kept)for(let i=0;i<path.points.length;i+=Math.max(1,Math.floor(path.points.length/6)))points.push(path.points[i]);
  const salient=[];for(const path of salientPaths)for(let i=0;i<path.points.length;i+=Math.max(1,Math.floor(path.points.length/4)))salient.push(path.points[i]);
  vectorEdgeCache={frame:frameCounter,paths:kept,salientPaths,points,salient};
  if(frameCounter%7===0&&kept.length){vectorEchoHistory.unshift(kept.slice(0,9).map(path=>path.points.map(p=>({...p}))));if(vectorEchoHistory.length>6)vectorEchoHistory.pop();}
  return vectorEdgeCache;
}
function strokeSmoothPath(path,effect,alpha,hueOffset=0,driftX=0,driftY=0){
  if(!path||path.length<2)return;
  fx.strokeStyle=vectorColor(effect,alpha,hueOffset);fx.beginPath();
  const p0=path[0];fx.moveTo(p0.x*width+driftX,p0.y*height+driftY);
  for(let i=1;i<path.length-1;i++){const p=path[i],n=path[i+1],mx=(p.x+n.x)*.5*width+driftX,my=(p.y+n.y)*.5*height+driftY;fx.quadraticCurveTo(p.x*width+driftX,p.y*height+driftY,mx,my);}
  const last=path[path.length-1];fx.lineTo(last.x*width+driftX,last.y*height+driftY);fx.stroke();
}
function drawContours(effect,semantic=false){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015)return;
  const edges=extractVectorEdges(),paths=semantic?edges.salientPaths:edges.paths;
  const max=Math.min(paths.length,Math.max(1,Math.round((semantic?5:9)*(.45+.65*amount))));
  fx.save();fx.globalCompositeOperation=effect.blend_mode||'screen';fx.lineJoin='round';fx.lineCap='round';fx.lineWidth=Math.max(.7,(effect.line_width??1.2))*devicePixelRatio;
  for(let i=0;i<max;i++){
    const path=paths[i],quality=Math.min(1,path.arc/32),alpha=(effect.opacity??.22)*amount*(semantic?.48:.38)*(.55+.45*quality);
    strokeSmoothPath(path.points,effect,alpha,semantic?28:0);
  }
  fx.restore();
}
function luminanceImage(imageData){const d=imageData.data,out=new Float32Array(imageData.width*imageData.height);for(let i=0,p=0;i<out.length;i++,p+=4)out[i]=.2126*d[p]+.7152*d[p+1]+.0722*d[p+2];return out;}
function updateOpticalFlow(force=false){
  if(!force&&vectorFlowCache.frame>=0&&frameCounter-vectorFlowCache.frame<2)return vectorFlowCache;
  const w=flowProbe.width,h=flowProbe.height;flowProbeCtx.drawImage(videoFx,0,0,w,h);
  let curImg,prevImg;try{curImg=flowProbeCtx.getImageData(0,0,w,h);prevImg=flowPrevCtx.getImageData(0,0,w,h);}catch{return vectorFlowCache;}
  if(!vectorFlowInitialized){flowPrevCtx.putImageData(curImg,0,0);vectorFlowInitialized=true;vectorFlowCache={frame:frameCounter,field:[],cols:0,rows:0,ready:false};return vectorFlowCache;}
  const cur=luminanceImage(curImg),prev=luminanceImage(prevImg),field=[],step=6,patch=2,search=3;
  let totalDelta=0;for(let i=0;i<cur.length;i++)totalDelta+=Math.abs(cur[i]-prev[i]);
  if(totalDelta/cur.length<1.2){flowPrevCtx.putImageData(curImg,0,0);vectorFlowCache={frame:frameCounter,field:[],cols:0,rows:0,ready:false};return vectorFlowCache;}
  for(let y=patch+search;y<h-patch-search;y+=step)for(let x=patch+search;x<w-patch-search;x+=step){
    let zero=0;for(let py=-patch;py<=patch;py++)for(let px=-patch;px<=patch;px++){const c=cur[(y+py)*w+x+px],q=prev[(y+py)*w+x+px];zero+=(c-q)*(c-q);}
    let best=zero,bx=0,by=0;
    for(let sy=-search;sy<=search;sy++)for(let sx=-search;sx<=search;sx++){if(sx===0&&sy===0)continue;let err=0;for(let py=-patch;py<=patch;py++)for(let px=-patch;px<=patch;px++){const c=cur[(y+py)*w+x+px],q=prev[(y+py+sy)*w+x+px+sx];const d=c-q;err+=d*d;}if(err<best){best=err;bx=-sx;by=-sy;}}
    const improve=zero>1?Math.max(0,(zero-best)/zero):0,speed=Math.hypot(bx,by)/search,strength=Math.min(1,improve*.8+speed*.35);
    if(strength>.10)field.push({x:x/(w-1),y:y/(h-1),vx:bx/search,vy:by/search,strength});
  }
  flowPrevCtx.putImageData(curImg,0,0);field.sort((a,b)=>b.strength-a.strength);vectorFlowCache={frame:frameCounter,field,cols:Math.floor(w/step),rows:Math.floor(h/step),ready:field.length>0};return vectorFlowCache;
}
function sampleFlow(field,x,y,fallbackX=0,fallbackY=0){
  if(!field.length)return{vx:fallbackX,vy:fallbackY,strength:.18};let best=null,bd=1e9;
  for(const v of field){const dx=v.x-x,dy=v.y-y,d=dx*dx+dy*dy;if(d<bd){bd=d;best=v;}}
  if(!best||bd>.08)return{vx:fallbackX,vy:fallbackY,strength:.15};return best;
}
function drawFlowRibbons(effect,particles=false){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015)return;
  const params=effect.parameters??{},mx=Number(params.motion_x??0),my=Number(params.motion_y??0),flow=updateOpticalFlow().field;
  const curl=effectCurveValue(effect,'curl',.18),maxCount=particles?28:12,count=Math.min(maxCount,Math.max(1,Math.round(effect.count*(particles?.22:.34))));
  const seeds=flow.length?flow.slice(0,Math.min(flow.length,count*2)):[];
  fx.save();fx.globalCompositeOperation=effect.blend_mode||'screen';fx.lineCap='round';fx.lineJoin='round';
  for(let i=0;i<count;i++){
    const seed=seeds[i%Math.max(1,seeds.length)]??{x:vectorRand(effect.seed,i*2),y:vectorRand(effect.seed,i*2+1),strength:.18,vx:mx,vy:my};
    let x=seed.x,y=seed.y;const pts=[{x,y}],steps=particles?3:Math.max(7,Math.round(8+8*amount));
    for(let step=0;step<steps;step++){
      const v=sampleFlow(flow,x,y,mx,my),phaseCurl=Math.sin(phase*.7+i*.9+step*.33)*curl*.32;
      let vx=v.vx,vy=v.vy,cs=Math.cos(phaseCurl),sn=Math.sin(phaseCurl),rx=vx*cs-vy*sn,ry=vx*sn+vy*cs,norm=Math.hypot(rx,ry)||1;
      const ds=(particles?.008:.014)*(1+.9*amount)*(.55+.65*v.strength);x+=rx/norm*ds;y+=ry/norm*ds;if(x<0||x>1||y<0||y>1)break;pts.push({x,y});
    }
    if(pts.length<2)continue;const alpha=(effect.opacity??.2)*amount*(particles?.38:.55)*(.5+.5*(seed.strength??.2));
    fx.lineWidth=Math.max(.65,(effect.line_width??1.4)*devicePixelRatio*(particles?.45:.72));strokeSmoothPath(pts,effect,alpha,i*5.5);
  }
  fx.restore();
}
function drawVectorEcho(effect){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015)return;extractVectorEdges();
  fx.save();fx.globalCompositeOperation='screen';fx.lineJoin='round';fx.lineCap='round';fx.lineWidth=Math.max(.7,(effect.line_width??1.1))*devicePixelRatio;
  const generations=Math.min(vectorEchoHistory.length,Math.max(1,Math.min(4,effect.count)));
  for(let g=0;g<generations;g++){
    const paths=vectorEchoHistory[g],fade=(1-g/(generations+1))*amount,drift=(g+1)*width*.0025*Math.sin(phase*.7+g);
    for(let i=0;i<Math.min(paths.length,6);i++)strokeSmoothPath(paths[i],effect,(effect.opacity??.16)*fade*.45,g*11,drift,g*height*.0012);
  }
  fx.restore();
}
function drawPerspectiveGrid(effect){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015)return;
  const p=effect.parameters??{},mx=Number(p.motion_x??0),my=Number(p.motion_y??0);
  const vx=width*(.5+.24*mx+.07*Math.sin(phase*.35)),vy=height*(.38+.18*my+.05*Math.cos(phase*.28));
  const count=Math.max(6,Math.min(40,effect.count));
  fx.save();fx.globalCompositeOperation='screen';fx.strokeStyle=vectorColor(effect,(effect.opacity??.15)*amount);fx.lineWidth=(effect.line_width??1)*devicePixelRatio;
  for(let i=0;i<=count;i++){
    const x=i/count*width;fx.beginPath();fx.moveTo(vx,vy);fx.lineTo(x,height);fx.stroke();
  }
  for(let j=1;j<=12;j++){
    const q=j/12,pow=q*q*q,y=vy+(height-vy)*pow;
    const spread=(width*(.12+.88*pow));fx.beginPath();fx.moveTo(vx-spread*.5,y);fx.lineTo(vx+spread*.5,y);fx.stroke();
  }
  fx.restore();
}
function geometryKey(effect){return `${activeScene?.scene_id??0}:${effect.kind}:${effect.seed}:${effect.count}:${width}x${height}`;}
function generatedSites(effect){
  const key=geometryKey(effect)+':sites';if(vectorGeometryCache.has(key))return vectorGeometryCache.get(key);
  const edges=extractVectorEdges(true).salient;
  const sites=[];
  const desired=Math.max(6,Math.min(70,effect.count));
  for(let i=0;i<desired;i++){
    if(i<edges.length&&i<Math.floor(desired*.55))sites.push({x:edges[i].x*width,y:edges[i].y*height});
    else sites.push({x:vectorRand(effect.seed,i*2)*width,y:vectorRand(effect.seed,i*2+1)*height});
  }
  vectorGeometryCache.set(key,sites);return sites;
}
function circumcircle(a,b,c){
  const d=2*(a.x*(b.y-c.y)+b.x*(c.y-a.y)+c.x*(a.y-b.y));if(Math.abs(d)<1e-8)return null;
  const aa=a.x*a.x+a.y*a.y,bb=b.x*b.x+b.y*b.y,cc=c.x*c.x+c.y*c.y;
  const x=(aa*(b.y-c.y)+bb*(c.y-a.y)+cc*(a.y-b.y))/d;
  const y=(aa*(c.x-b.x)+bb*(a.x-c.x)+cc*(b.x-a.x))/d;
  return{x,y,r2:(x-a.x)**2+(y-a.y)**2};
}
function delaunay(effect){
  const key=geometryKey(effect)+':tri';if(vectorGeometryCache.has(key))return vectorGeometryCache.get(key);
  const sites=generatedSites(effect);const margin=Math.max(width,height)*8;
  const pts=[...sites,{x:-margin,y:-margin},{x:width+margin,y:-margin},{x:width/2,y:height+margin}];
  const n=sites.length;let tris=[[n,n+1,n+2]];
  for(let pi=0;pi<n;pi++){
    const p=pts[pi],bad=[];
    for(let ti=0;ti<tris.length;ti++){const t=tris[ti],c=circumcircle(pts[t[0]],pts[t[1]],pts[t[2]]);if(c&&((p.x-c.x)**2+(p.y-c.y)**2)<=c.r2+1e-5)bad.push(ti);}
    const edges=[];
    for(const ti of bad){const t=tris[ti];for(const e of [[t[0],t[1]],[t[1],t[2]],[t[2],t[0]]]){const k=e[0]<e[1]?`${e[0]}:${e[1]}`:`${e[1]}:${e[0]}`;edges.push({e,k});}}
    const counts=new Map();for(const x of edges)counts.set(x.k,(counts.get(x.k)||0)+1);
    const boundary=edges.filter(x=>counts.get(x.k)===1).map(x=>x.e);
    tris=tris.filter((_,i)=>!bad.includes(i));
    for(const e of boundary)tris.push([e[0],e[1],pi]);
  }
  tris=tris.filter(t=>t.every(i=>i<n));
  const result={sites,pts,tris};vectorGeometryCache.set(key,result);return result;
}
function drawDelaunay(effect){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015)return;
  const explode=Math.min(1,effectCurveValue(effect,'explode',0)),geo=delaunay(effect);
  snapshot();fx.save();fx.globalCompositeOperation=effect.blend_mode||'screen';
  for(let ti=0;ti<geo.tris.length;ti++){
    const t=geo.tris[ti],a=geo.pts[t[0]],b=geo.pts[t[1]],c=geo.pts[t[2]],cx=(a.x+b.x+c.x)/3,cy=(a.y+b.y+c.y)/3;
    const angle=Math.atan2(cy-height/2,cx-width/2),push=explode*amount*Math.min(width,height)*.12*(.35+.65*vectorRand(effect.seed,ti));
    fx.save();fx.beginPath();fx.moveTo(a.x,a.y);fx.lineTo(b.x,b.y);fx.lineTo(c.x,c.y);fx.closePath();fx.clip();
    if(effect.displace&&explode>.02){fx.globalAlpha=.32+.46*amount;fx.drawImage(scratch,Math.cos(angle)*push,Math.sin(angle)*push,width,height);}
    fx.restore();
    if(effect.visible!==false){fx.strokeStyle=vectorColor(effect,(effect.opacity??.25)*amount,ti*2.1);fx.lineWidth=(effect.line_width??1)*devicePixelRatio;fx.beginPath();fx.moveTo(a.x,a.y);fx.lineTo(b.x,b.y);fx.lineTo(c.x,c.y);fx.closePath();fx.stroke();}
  }
  fx.restore();
}
function drawVoronoi(effect){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015)return;
  const geo=delaunay(effect),edgeMap=new Map();
  for(let ti=0;ti<geo.tris.length;ti++){const t=geo.tris[ti],cc=circumcircle(geo.pts[t[0]],geo.pts[t[1]],geo.pts[t[2]]);if(!cc)continue;for(const e of [[t[0],t[1]],[t[1],t[2]],[t[2],t[0]]]){const k=e[0]<e[1]?`${e[0]}:${e[1]}`:`${e[1]}:${e[0]}`;if(!edgeMap.has(k))edgeMap.set(k,[]);edgeMap.get(k).push(cc);}}
  fx.save();fx.globalCompositeOperation='screen';fx.strokeStyle=vectorColor(effect,(effect.opacity??.2)*amount,35);fx.lineWidth=(effect.line_width??1)*devicePixelRatio;
  for(const centers of edgeMap.values())if(centers.length===2){fx.beginPath();fx.moveTo(centers[0].x,centers[0].y);fx.lineTo(centers[1].x,centers[1].y);fx.stroke();}
  fx.restore();
  if(effect.displace)applyVectorDisplacement({...effect,amount:amount*.45});
}
function portalPath(effect,index,amount){
  const seed=effect.seed+index*7919,cx=width*(.25+.5*vectorRand(seed,1)),cy=height*(.25+.5*vectorRand(seed,2));
  const radius=Math.min(width,height)*effectCurveValue(effect,'radius',.25)*(.55+.7*amount),vertices=7+(seed%5);
  fx.beginPath();
  for(let i=0;i<=vertices;i++){const a=i/vertices*Math.PI*2,r=radius*(.76+.24*Math.sin(a*3+phase*1.7+seed*.001));const x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r;if(i===0)fx.moveTo(x,y);else fx.lineTo(x,y);}
  fx.closePath();return{cx,cy,radius};
}
function drawPortal(effect){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015||activeBank<0)return;
  const companions=bankState[activeBank]?.slice(1)??[];if(!companions.length)return;
  const count=Math.min(effect.count,companions.length);
  for(let i=0;i<count;i++){
    fx.save();const shape=portalPath(effect,i,amount);fx.clip();drawLayer(fx,companions[i],{x:0,y:0,w:width,h:height},Math.min(.9,(effect.opacity??.5)+amount*.35),'screen');fx.restore();
    fx.save();fx.strokeStyle=vectorColor(effect,(effect.opacity??.4)*amount,i*55);fx.lineWidth=(effect.line_width??2)*devicePixelRatio;portalPath(effect,i,amount);fx.stroke();fx.restore();
  }
}
function drawMotifGlyph(effect){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015)return;
  const rotation=effectCurveValue(effect,'rotation',0),arms=Math.max(3,Math.min(12,effect.count)),cx=width*.5,cy=height*.5;
  const base=Math.min(width,height)*(.055+.08*amount);
  fx.save();fx.translate(cx,cy);fx.rotate(rotation*Math.PI+phase*.08*(1+amount));fx.globalCompositeOperation='screen';fx.strokeStyle=vectorColor(effect,(effect.opacity??.2)*amount,70);fx.lineWidth=(effect.line_width??1.5)*devicePixelRatio;
  for(let arm=0;arm<arms;arm++){fx.save();fx.rotate(arm/arms*Math.PI*2);fx.beginPath();fx.moveTo(0,0);let x=0,y=0;for(let n=1;n<=6;n++){const len=base*(.16+.13*n),bend=Math.sin(effect.seed*.001+n*1.7)*base*.12;x+=len*.38;y+=(n%2?1:-1)*bend;fx.quadraticCurveTo(x-len*.18,y*.6,x,y);}fx.stroke();fx.restore();}
  fx.restore();
}
function applyMotionTransplant(effect){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015||activeBank<0)return;
  const companion=bankState[activeBank]?.[1]?.video;if(!companion||companion.readyState<2)return;
  const w=motionProbe.width,h=motionProbe.height;
  motionProbeCtx.drawImage(companion,0,0,w,h);
  let cur,prev;
  try{cur=motionProbeCtx.getImageData(0,0,w,h);prev=motionPrevCtx.getImageData(0,0,w,h);}catch{return;}
  const field=[];
  for(let gy=1;gy<h-1;gy+=3)for(let gx=1;gx<w-1;gx+=3){
    const i=(gy*w+gx)*4;
    const lum=(d,j)=>.2126*d[j]+.7152*d[j+1]+.0722*d[j+2];
    const dt=(lum(cur.data,i)-lum(prev.data,i))/255;
    const dx=(lum(cur.data,i+4)-lum(cur.data,i-4))/255;
    const dy=(lum(cur.data,i+w*4)-lum(cur.data,i-w*4))/255;
    const strength=Math.min(1,Math.abs(dt)*2.8);
    if(strength>.06)field.push({x:gx/w,y:gy/h,dx:dx*Math.sign(dt||1),dy:dy*Math.sign(dt||1),strength});
  }
  motionPrevCtx.putImageData(cur,0,0);
  if(!field.length)return;
  snapshot();
  const cellW=width/(w/3),cellH=height/(h/3);
  fx.save();fx.globalAlpha=.15+.38*amount;
  for(const v of field.slice(0,70)){
    const sx=Math.max(0,v.x*width-cellW),sy=Math.max(0,v.y*height-cellH);
    const sw=Math.min(width-sx,cellW*2),sh=Math.min(height-sy,cellH*2);
    const mx=(v.dx*width*.11+Math.sin(phase+v.y*9)*width*.004)*amount*v.strength;
    const my=(v.dy*height*.11+Math.cos(phase*.8+v.x*7)*height*.004)*amount*v.strength;
    fx.drawImage(scratch,sx,sy,sw,sh,sx+mx,sy+my,sw,sh);
  }
  fx.restore();
}
function applyVectorDisplacement(effect){
  const amount=Math.min(1,effectCurveValue(effect,'amount',effect.amount));if(amount<.015)return;
  snapshot();const strips=Math.max(6,Math.min(36,effect.count)),sh=height/strips;
  fx.save();fx.globalCompositeOperation='source-over';fx.globalAlpha=.18+.34*amount;
  for(let i=0;i<strips;i++){const y=i*sh,angle=phase*(1.5+amount*2)+i*.73+effect.seed*.0001;const dx=Math.sin(angle)*width*.026*amount,dy=Math.cos(angle*1.31)*height*.008*amount;fx.drawImage(scratch,0,y,width,sh+1,dx,y+dy,width,sh+1);}
  fx.restore();
}
function renderVectorSceneGraph(){
  const allEffects=activeScene?.direction?.vector_effects;if(!Array.isArray(allEffects)||!allEffects.length)return;
  // Compatibility guard for v0.22/v0.23 timelines: older plans scheduled many
  // visible vector families simultaneously. Keep all invisible deformation,
  // but select only the strongest family vocabulary at render time.
  const family=activeScene?.direction?.effect_family??'cinematic',role=activeScene?.direction?.narrative_role??'develop';
  const priority={dream:['vector_echo','contours','portal','semantic_outline'],liquid:['flow_ribbons','vector_echo','portal','flow_particles'],analog:['perspective_grid','contours','semantic_outline'],fracture:['delaunay_fracture','voronoi','portal'],hyper:['flow_ribbons','delaunay_fracture','flow_particles','perspective_grid'],prismatic:['portal','voronoi','flow_ribbons'],cinematic:['semantic_outline','contours','perspective_grid','portal']}[family]??['contours'];
  const hidden=allEffects.filter(e=>e.visible===false),visible=allEffects.filter(e=>e.visible!==false);
  visible.sort((a,b)=>{const ai=priority.indexOf(a.kind),bi=priority.indexOf(b.kind);return(ai<0?99:ai)-(bi<0?99:bi);});
  const budget=(role==='payoff'&&sectionEnergy>.76)?2:1,effects=[...visible.slice(0,budget),...hidden];
  // Edge extraction is shared by all geometry derived from the current frame.
  if(effects.some(e=>['contours','semantic_outline','vector_echo','delaunay_fracture','voronoi'].includes(e.kind)))extractVectorEdges();
  for(const effect of effects){
    const amount=effectCurveValue(effect,'amount',effect.amount??0);if(amount<=.012)continue;
    switch(effect.kind){
      case'contours':drawContours(effect,false);break;
      case'semantic_outline':drawContours(effect,true);break;
      case'flow_ribbons':drawFlowRibbons(effect,false);break;
      case'flow_particles':drawFlowRibbons(effect,true);break;
      case'vector_echo':drawVectorEcho(effect);break;
      case'perspective_grid':drawPerspectiveGrid(effect);break;
      case'delaunay_fracture':drawDelaunay(effect);break;
      case'voronoi':drawVoronoi(effect);break;
      case'portal':drawPortal(effect);break;
      case'motif_glyph':drawMotifGlyph(effect);break;
      case'motion_transplant':applyMotionTransplant(effect);break;
      case'vector_displacement':applyVectorDisplacement(effect);break;
    }
  }
}
function codecEffectEnvelope(effect){
  if(activeScene?.codec_materialization?.materialized)return 0;
  const p=directedProgress(),a=Number(effect.start??0),b=Number(effect.end??1);
  if(p<a||p>b)return 0;
  const q=(p-a)/Math.max(1e-6,b-a),attack=Number(effect.attack??.12),release=Number(effect.release??.18);
  const smooth=x=>x*x*(3-2*x);
  const ai=attack>0?smooth(Math.max(0,Math.min(1,q/attack))):1;
  const ro=release>0?1-smooth(Math.max(0,Math.min(1,(q-(1-release))/release))):1;
  const pulse=Number(effect.pulse??0);let shape=Math.min(ai,ro);
  if(pulse>0)shape*=.45+.55*Math.abs(Math.sin(q*Math.PI*pulse));
  return Math.max(0,Math.min(1.5,Number(effect.amount??0)*shape));
}
function codecFallback(){
  const out={datamosh:0,blocks:0,vortex:0,ripple:0,rgb:0,tracking:0,feedback:0};
  for(const effect of activeScene?.direction?.codec_effects??[]){
    const a=codecEffectEnvelope(effect);if(a<=.005)continue;
    switch(effect.kind){
      case'datamosh':case'mv_feedback':out.datamosh=Math.max(out.datamosh,a*.88);out.feedback=Math.max(out.feedback,a*.35);break;
      case'mv_explode':case'mv_implode':case'mv_radial_wave':out.ripple=Math.max(out.ripple,a*.72);out.blocks=Math.max(out.blocks,a*.40);break;
      case'mv_spiral':out.vortex=Math.max(out.vortex,a*.78);break;
      case'mv_shear':out.blocks=Math.max(out.blocks,a*.55);break;
      case'mv_jitter':out.rgb=Math.max(out.rgb,a*.35);out.tracking=Math.max(out.tracking,a*.55);break;
      case'mv_wave':case'mv_drift':out.ripple=Math.max(out.ripple,a*.30);out.tracking=Math.max(out.tracking,a*.24);break;
      case'mv_freeze':out.datamosh=Math.max(out.datamosh,a*.40);break;
      case'mv_invert':out.rgb=Math.max(out.rgb,a*.30);out.vortex=Math.max(out.vortex,a*.30);break;
    }
  }
  return out;
}
function applyPostFx(){
  if(!activeScene)return;
  const t=activeScene.transform??{},m=liveFx.master;
  const motion=m*liveFx.motion,trails=m*liveFx.trails,glitchScale=m*liveFx.glitch,strobeScale=m*liveFx.strobe;

  const codec=codecFallback();
  const directedFeedback=automationValue('feedback',0),directedGlitch=automationValue('glitch',0);
  const directedWarp=automationValue('spectral_warp',0),directedChroma=automationValue('chromatic',0);
  const directedBloom=automationValue('bloom',0),directedFlow=automationValue('flow',0);
  const feedback=Math.min(1,((t.feedback??0)+directedFeedback+codec.feedback)*trails);
  const glitch=Math.min(1,((t.glitch??0)+sliceFx+directedGlitch)*glitchScale);
  const pixel=Math.min(1,(t.pixelate??0)*glitchScale);
  const rgb=Math.min(1,((t.rgb_split??0)+codec.rgb)*glitchScale);
  const scan=Math.min(1,(t.scanlines??0)*m);
  const vignette=Math.min(1,(t.vignette??0)*m);
  const ripple=Math.min(1,((t.ripple??0)+rippleFx+directedFlow*.28+codec.ripple)*motion);
  const kaleido=Math.min(1,((t.kaleidoscope??0)+kaleidoFx)*motion);
  const tiles=Math.min(1,(t.tiles??0)*motion);
  const tunnel=Math.min(1,((t.tunnel??0)+tunnelFx)*motion);
  const posterize=Math.min(1,(t.posterize??0)*m);
  const edge=Math.min(1,((t.edge??0)+edgeFx)*m);
  const strobe=Math.min(1,((t.strobe??0)+strobeFx)*strobeScale);
  const shutter=Math.min(1,(t.shutter??0)*motion);

  const slitScan=Math.min(1,((t.slit_scan??0)+slitScanFx)*motion);
  const frameEcho=Math.min(1,((t.frame_echo??0)+echoFx)*trails);
  const corridor=Math.min(1,((t.mirror_corridor??0)+corridorFx)*motion);
  const mask=Math.min(1,((t.mask_wipe??0)+maskFx)*motion);
  const solarize=Math.min(1,((t.solarize??0)+solarizeFx)*m);
  const datamosh=Math.min(1,((t.datamosh??0)+datamoshFx+codec.datamosh)*glitchScale);
  const blocks=Math.min(1,((t.block_displace??0)+codec.blocks)*glitchScale);
  const chromaDelay=Math.min(1,((t.chroma_delay??0)+chromaDelayFx+directedChroma*.24)*trails);
  const tracking=Math.min(1,((t.vhs_tracking??0)+codec.tracking)*glitchScale);
  const vortex=Math.min(1,((t.vortex??0)+vortexFx+codec.vortex)*motion);
  const motionTrails=Math.min(1,((t.motion_trails??0)+motionTrailFx)*trails);
  const sliceRecursion=Math.min(1,((t.slice_recursion??0)+sliceRecursionFx)*motion);

  const creative=activeScene?.direction?.creative??{};
  const creativeFlow=Math.min(1,creativeValue('flow_warp',creative.flow_warp??0)*motion);
  const creativeFlowTrails=Math.min(1,creativeValue('flow_trails',creative.flow_trails??0)*trails);
  const creativeFlowRgb=Math.min(1,creativeValue('flow_rgb',creative.flow_rgb??0)*glitchScale);
  const creativeTemporal=Math.min(1,creativeValue('temporal_echo',creative.temporal_echo??0)*trails);
  const creativeTemporalRgb=Math.min(1,creativeValue('temporal_rgb',creative.temporal_rgb??0)*trails);
  const creativeSmear=Math.min(1,creativeValue('temporal_smear',creative.temporal_smear??0)*trails);
  const creativeDepth=Math.min(1,creativeValue('depth_parallax',creative.depth_parallax??0)*motion);
  const creativeBackground=Math.min(1,creativeValue('background_warp',creative.background_warp??0)*motion);
  const creativeFeedback=Math.min(1,creativeValue('feedback',creative.feedback??0)*trails);
  const creativeSymmetry=Math.min(1,creativeValue('local_symmetry',creative.local_symmetry??0)*motion);
  const creativeBloom=Math.min(1,creativeValue('texture_bloom',creative.texture_bloom??0)*m);
  const creativeStreaks=Math.min(1,creativeValue('texture_streaks',creative.texture_streaks??0)*motion);
  const creativePalette=Math.min(1,creativeValue('palette_strength',creative.palette_strength??0)*m);

  // Directed color happens on the composed video, then temporal processing
  // evolves continuously over the shot rather than toggling static filters.
  applyDirectedColor();
  applySpectralDisplacement(Math.min(1,directedWarp+beatWarpFx*.20));
  applyPrismaticShift(Math.min(1,directedChroma+(activeScene?.direction?.color?.chromatic_aberration??0)*.25));
  if(directedBloom>.02){snapshot();fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.08+.28*directedBloom;if('filter'in fx)fx.filter=`brightness(${1+.45*directedBloom}) saturate(${1+.35*directedBloom})`;fx.drawImage(scratch,0,0,width,height);fx.restore();}

  // Capture the pre-temporal frame before time-based effects mutate it.
  captureDelayFrame();

  // v0.33 creative-state pipeline: source-derived and semantic-aware effects run
  // before legacy punctuation FX, so later glitches can accent rather than erase them.
  applyPaletteCreative(creativePalette);
  applySourceTextureCreative(creativeBloom,creativeStreaks);
  applyDepthParallaxCreative(creativeDepth);
  applyBackgroundWarpCreative(creativeBackground);
  applyFlowWarpCreative(creativeFlow);
  applyFlowRgbCreative(creativeFlowRgb);
  applyTemporalSmearCreative(creativeSmear);
  applyTemporalRgbCreative(creativeTemporalRgb);
  applyMotionTrails(creativeFlowTrails*.78);
  applyFrameEcho(creativeTemporal*.70);
  applyLocalSymmetryCreative(creativeSymmetry);
  applyRecursiveFeedbackCreative(creativeFeedback);
  applyHeroCreative();

  applyShutter(shutter);
  applyBeatWarp(beatWarpFx,beatLow,beatMid,beatHigh);
  applyTempoWarp(tempoWarpFx);
  applySlitScan(slitScan);
  applyMotionTrails(motionTrails);
  applyFrameEcho(frameEcho);
  applyRipple(ripple);
  applyBlockDisplace(blocks);
  applyDatamosh(datamosh);
  applyVhsTracking(tracking);
  applyTiles(tiles);
  applyMirrorCorridor(corridor);
  applyKaleidoscope(kaleido);
  applyVortex(vortex);
  applyTunnel(tunnel);
  applySliceRecursion(sliceRecursion);
  applyMaskWipe(mask);
  applyPosterize(posterize);
  applySolarize(solarize);
  applyEdge(edge);
  applyPixel(pixel);
  applyChromaDelay(chromaDelay);
  applyRgbSplit(rgb);
  applyGlitch(glitch);
  applyFeedback(feedback);
  applyScanlines(scan);
  applyVignette(vignette);
  applyStrobe(strobe);
  renderVectorSceneGraph();

  historyCtx.globalAlpha=.92;
  historyCtx.drawImage(videoFx,0,0);
}
function renderVideo(){
  if(clockNowMs()<freezeUntil){fx.drawImage(freezeCanvas,0,0);return;}
  fx.fillStyle='#000';fx.fillRect(0,0,width,height);if(activeBank<0)return;
  if(transition){const p=transition.duration<=0?1:Math.min(1,(clockNowMs()-transition.start)/transition.duration);drawBank(transition.from,1-p);const saved=activeBank;activeBank=transition.to;drawBank(transition.to,p);activeBank=saved;if(p>=1){banks[transition.from].forEach(v=>v.pause());activeBank=transition.to;transition=null;}}
  else drawBank(activeBank,1);applyPostFx();
}
function maintainRanges(){for(const states of bankState)for(const st of states){const v=st.video;if(audio.paused)continue;if(v.currentTime>=st.end-.03||v.currentTime<st.start-.1){v.currentTime=st.start;v.play().catch(()=>{});}}}
function seekActive(delta=null,fraction=null){
  if(activeBank<0)return;
  for(const st of bankState[activeBank]){
    if(offlineMode){
      const rate=st.transform?.materialized?1:(st.transform?.playback_rate??1);
      const sceneStart=activeScene?.time??0;
      const elapsed=Math.max(0,offlineTime-sceneStart);
      const base=(elapsed*rate)%st.span;
      let current=(base+(st.offlineBias??0))%st.span;if(current<0)current+=st.span;
      const desired=fraction==null
        ?(current+(delta??0))
        :st.span*Math.max(0,Math.min(.95,fraction));
      let wrapped=desired%st.span;if(wrapped<0)wrapped+=st.span;
      st.offlineBias=wrapped-base;
      continue;
    }
    let target=fraction==null?st.video.currentTime+(delta??0):st.start+st.span*Math.max(0,Math.min(.95,fraction));
    while(target<st.start)target+=st.span;while(target>=st.end)target-=st.span;st.video.currentTime=target;
  }
}

function upsertMotif(p,mode){
  const prev=motifObjects.get(p.motif_id)||{};
  const visualStrength=mode==='recall'?1:(mode==='introduce'?.48:(mode==='foreshadow'?.16:.22));
  motifObjects.set(p.motif_id,{
    ...prev,...p,
    opacity:mode==='foreshadow'?.12:1,
    pulse:mode==='recall'?1:.2,
    visualStrength:Math.max(prev.visualStrength??0,visualStrength)
  });
}
function cue(c){const p=c.parameters||{};switch(c.action){
  case'play_scene':case'crossfade_scene':activateScene(p);break;
  case'video_edit_punch':punch=Math.max(punch,p.amount??.2);break;
  case'video_edit_beat_warp':
  case'beat_warp':
    beatWarpFx=Math.max(beatWarpFx,p.amount??.35);
    beatLow=Math.max(beatLow,p.low??0);beatMid=Math.max(beatMid,p.mid??0);beatHigh=Math.max(beatHigh,p.high??0);
    break;
  case'video_edit_tempo_warp':
  case'tempo_shift':tempoWarpFx=Math.max(tempoWarpFx,p.amount??.4);break;
  case'video_edit_retrigger':seekActive(-(p.back_seconds??.12));break;
  case'video_edit_jump':seekActive(null,p.fraction??.5);break;
  case'video_edit_slice':sliceFx=Math.max(sliceFx,p.amount??.3);break;
  case'video_edit_switch':if(activeBank>=0){const n=bankState[activeBank].length;if(n)focusLayer=(focusLayer+1)%n;}break;
  case'video_edit_freeze':freezeCtx.drawImage(videoFx,0,0);freezeUntil=clockNowMs()+(p.duration??.12)*1000;break;
  case'video_edit_strobe':strobeFx=Math.max(strobeFx,p.amount??.4);break;
  case'video_edit_tunnel':tunnelFx=Math.max(tunnelFx,p.amount??.4);break;
  case'video_edit_kaleidoscope':kaleidoFx=Math.max(kaleidoFx,p.amount??.35);break;
  case'video_edit_ripple':rippleFx=Math.max(rippleFx,p.amount??.4);break;
  case'video_edit_edge':edgeFx=Math.max(edgeFx,p.amount??.35);break;
  case'video_edit_slitscan':slitScanFx=Math.max(slitScanFx,p.amount??.35);break;
  case'video_edit_echo':echoFx=Math.max(echoFx,p.amount??.35);break;
  case'video_edit_corridor':corridorFx=Math.max(corridorFx,p.amount??.35);break;
  case'video_edit_mask':maskFx=Math.max(maskFx,p.amount??.35);break;
  case'video_edit_solarize':solarizeFx=Math.max(solarizeFx,p.amount??.35);break;
  case'video_edit_datamosh':datamoshFx=Math.max(datamoshFx,p.amount??.4);break;
  case'video_edit_chroma_delay':chromaDelayFx=Math.max(chromaDelayFx,p.amount??.35);break;
  case'video_edit_vortex':vortexFx=Math.max(vortexFx,p.amount??.35);break;
  case'video_edit_motion_trails':motionTrailFx=Math.max(motionTrailFx,p.amount??.4);break;
  case'video_edit_slice_recursion':sliceRecursionFx=Math.max(sliceRecursionFx,p.amount??.4);break;
  case'camera_impulse':punch=Math.max(punch,(p.amount??0)*2);break;
  case'bar_pulse':barPulse=Math.max(barPulse,p.amount??.2);break;
  case'spawn_fragment':for(let i=0;i<(p.count??2);i++)fragments.push({x:rand(),y:rand(),vx:(rand()-.5)*(p.velocity??.5),vy:(rand()-.5)*(p.velocity??.5),size:.02+rand()*.08,life:1});break;
  case'energy_bloom':
    bloom=Math.max(bloom,p.amount??0);
    if((p.bass_weight??0)>.28)rippleFx=Math.max(rippleFx,(p.amount??0)*(p.bass_weight??0)*.55);
    if((p.percussive_ratio??0)>.55)slitScanFx=Math.max(slitScanFx,(p.amount??0)*(p.percussive_ratio??0)*.22);
    break;
  case'harmonic_warp':
    warp=Math.max(warp,p.amount??0);
    rippleFx=Math.max(rippleFx,(p.amount??0)*(.22+.22*(1-(p.tonal_stability??.5))));
    if((p.tonal_stability??.5)>.62)vortexFx=Math.max(vortexFx,(p.amount??0)*.28);
    if((p.brightness??.5)>.62)chromaDelayFx=Math.max(chromaDelayFx,(p.amount??0)*.24);
    else edgeFx=Math.max(edgeFx,(p.amount??0)*.18);
    break;
  case'enter_section':
    world=p.world;sectionLabel=p.label;sectionEnergy=p.energy;
    currentVibe=p.vibe??'neutral';currentLocalBpm=p.local_bpm??120;
    currentBass=p.bass_weight??0;currentPercussive=p.percussive_ratio??0;currentTonal=p.tonal_stability??0;
    break;case'phase_transition':phaseFlash=1;strobeFx=Math.max(strobeFx,.6);tunnelFx=Math.max(tunnelFx,.45);break;
  case'introduce_motif':upsertMotif(p,'introduce');break;case'foreshadow_motif':upsertMotif(p,'foreshadow');break;case'recall_motif':upsertMotif(p,'recall');kaleidoFx=Math.max(kaleidoFx,.25);break;
  case'anticipate_motif':anticipation=Math.max(anticipation,p.amount??.3);break;
}}
function restoreState(m){motifObjects.clear();if(m.world){world=m.world.world_id;sectionLabel=m.world.section_label;sectionEnergy=m.world.energy;}for(const p of Object.values(m.motifs??{}))upsertMotif(p,'restore');if(m.scene)activateScene(m.scene,{immediate:true});}
if(ws)ws.addEventListener('message',ev=>{const m=JSON.parse(ev.data);if(m.type==='frame')m.cues.forEach(cue);else if(m.type==='state')restoreState(m);else if(m.type==='ended')pauseAll();});

function drawOverlay(){
  ctx.clearRect(0,0,width,height);
  if(activeBank<0)return;
  ctx.save();ctx.globalCompositeOperation='screen';

  // Onset fragments are now fluid refraction droplets. They never draw a
  // rectangular video patch, which eliminates the intermittent square overlays.
  for(let i=fragments.length-1;i>=0;i--){
    const f=fragments[i];
    f.x+=f.vx*.006;f.y+=f.vy*.006;f.life*=.962;
    if(f.life<.03){fragments.splice(i,1);continue;}

    const cx=f.x*width,cy=f.y*height;
    const radius=(.018+f.size*.55)*Math.min(width,height)*(0.7+f.life*.3);
    ctx.save();
    ctx.globalAlpha=f.life*.16;
    ctx.beginPath();
    const wobble=.22+.12*Math.sin(phase*2+i);
    ctx.moveTo(cx+radius,cy);
    ctx.bezierCurveTo(cx+radius*(1-wobble),cy-radius*.85,cx+radius*.15,cy-radius*1.08,cx,cy-radius*.92);
    ctx.bezierCurveTo(cx-radius*.78,cy-radius*.82,cx-radius*1.06,cy-radius*.12,cx-radius*.94,cy);
    ctx.bezierCurveTo(cx-radius*.88,cy+radius*.76,cx-radius*.12,cy+radius*1.02,cx,cy+radius*.90);
    ctx.bezierCurveTo(cx+radius*.72,cy+radius*.84,cx+radius*1.05,cy+radius*.18,cx+radius,cy);
    ctx.closePath();ctx.clip();

    const zoom=1.02+f.life*.07;
    ctx.translate(cx,cy);ctx.rotate((f.vx-f.vy)*.08);ctx.scale(zoom,zoom);ctx.translate(-cx,-cy);
    ctx.drawImage(videoFx,f.vx*55,f.vy*55,width,height);
    ctx.restore();
  }

  let mi=0;
  for(const m of motifObjects.values()){
    m.pulse=(m.pulse??0)*.93;
    m.visualStrength=(m.visualStrength??0)*.94;
    if(m.visualStrength<=.025){mi++;continue;}

    const strength=Math.min(1,m.visualStrength);
    const size=(.08+.04*(m.mutation??0)+.025*m.pulse)*Math.min(width,height);
    const drift=phase*.32+mi*2.7;
    const x=width*(.50+.31*Math.sin(drift*.71));
    const y=height*(.50+.27*Math.cos(drift*.57));

    // Motifs are soft irregular refractions, not mini video windows.
    ctx.save();
    ctx.globalAlpha=(.025+.085*strength)*(m.opacity??1);
    ctx.beginPath();
    const rx=size*(1.0+.18*Math.sin(drift));
    const ry=size*(.74+.12*Math.cos(drift*.8));
    ctx.moveTo(x+rx,y);
    ctx.bezierCurveTo(x+rx*.76,y-ry*.78,x+rx*.18,y-ry*1.05,x,y-ry);
    ctx.bezierCurveTo(x-rx*.68,y-ry*.88,x-rx*1.04,y-ry*.20,x-rx,y);
    ctx.bezierCurveTo(x-rx*.88,y+ry*.72,x-rx*.18,y+ry*1.08,x,y+ry);
    ctx.bezierCurveTo(x+rx*.72,y+ry*.92,x+rx*1.06,y+ry*.18,x+rx,y);
    ctx.closePath();ctx.clip();

    const zoom=1.04+.10*strength;
    ctx.translate(x,y);ctx.rotate(Math.sin(drift*.43)*.12*strength);ctx.scale(zoom,zoom);ctx.translate(-x,-y);
    ctx.drawImage(videoFx,0,0,width,height);
    ctx.restore();
    mi++;
  }

  ctx.restore();ctx.globalAlpha=1;
}

function decay(base){return offlineMode?Math.pow(base,60/offlineFps):base;}
function advanceDynamics(){
  frameCounter++;
  phase=offlineMode?offlineTime*.24:phase+.004;
  punch*=decay(.79);sliceFx*=decay(.86);bloom*=decay(.92);warp*=decay(.94);barPulse*=decay(.85);phaseFlash*=decay(.86);anticipation*=decay(.95);
  strobeFx*=decay(.78);tunnelFx*=decay(.90);kaleidoFx*=decay(.91);rippleFx*=decay(.90);edgeFx*=decay(.88);
  slitScanFx*=decay(.90);echoFx*=decay(.91);corridorFx*=decay(.91);maskFx*=decay(.90);solarizeFx*=decay(.86);
  datamoshFx*=decay(.88);chromaDelayFx*=decay(.90);vortexFx*=decay(.91);motionTrailFx*=decay(.91);sliceRecursionFx*=decay(.89);
  beatWarpFx*=decay(.76);beatLow*=decay(.82);beatMid*=decay(.80);beatHigh*=decay(.76);tempoWarpFx*=decay(.93);
}
function frame(){
  advanceDynamics();
  renderVideo();drawOverlay();maintainRanges();requestAnimationFrame(frame);
}

function sceneIndexAt(t){
  let found=-1;
  for(let i=0;i<timeline.scene_plan.length;i++){if(timeline.scene_plan[i].time<=t)found=i;else break;}
  return found;
}
async function seekDecoder(video,target){
  if(!Number.isFinite(target)||video.readyState<1)return;
  target=Math.max(0,Math.min(Math.max(0,video.duration-.001),target));

  // `seeked` means the media seek operation has completed. The old renderer
  // also waited for requestVideoFrameCallback(), but paused decoders may not
  // schedule that callback promptly; its 1s fallback became a per-frame stall.
  if(Math.abs(video.currentTime-target)<.0015)return;
  await new Promise((resolve,reject)=>{
    let done=false;
    const finish=()=>{if(done)return;done=true;cleanup();resolve();};
    const fail=()=>{if(done)return;done=true;cleanup();reject(video.error||new Error('video seek failed'));};
    const cleanup=()=>{
      video.removeEventListener('seeked',finish);
      video.removeEventListener('error',fail);
      clearTimeout(timer);
    };
    const timer=setTimeout(finish,750);
    video.addEventListener('seeked',finish,{once:true});
    video.addEventListener('error',fail,{once:true});
    video.currentTime=target;
  });
}
async function seekOfflineBank(bankIndex,scene,t){
  const states=bankState[bankIndex];
  const elapsed=Math.max(0,t-scene.time);
  await Promise.all(states.map(st=>{
    const rate=st.transform?.materialized?1:(st.transform?.playback_rate??1);
    let offset=(elapsed*rate+(st.offlineBias??0))%st.span;if(offset<0)offset+=st.span;
    return seekDecoder(st.video,Math.min(st.end-.002,st.start+offset));
  }));
}
async function prepareOfflineScene(index){
  if(index===offlineLoadedScene)return;
  pauseAll();bankState[0]=[];bankState[1]=[];
  if(index<0){activeBank=-1;activeScene=null;offlineLoadedScene=index;return;}
  const current=timeline.scene_plan[index];
  if(index>0)await loadBank(0,timeline.scene_plan[index-1]);
  await loadBank(1,current);
  activeBank=1;activeScene={...current};focusLayer=0;transition=null;offlineLoadedScene=index;resetVectorMotionState();
}
function processOfflineCues(t){
  while(offlineCueIndex<timeline.cues.length&&timeline.cues[offlineCueIndex].time<=t+1e-9){
    const c=timeline.cues[offlineCueIndex++];
    if(c.action!=='play_scene'&&c.action!=='crossfade_scene')cue(c);
  }
}
async function renderOfflineVideo(t,index){
  await prepareOfflineScene(index);
  fx.fillStyle='#000';fx.fillRect(0,0,width,height);
  if(index<0)return;
  const current=timeline.scene_plan[index],previous=index>0?timeline.scene_plan[index-1]:null;
  await seekOfflineBank(1,current,t);
  const fade=Math.max(0,current.crossfade_seconds??0);
  const progress=fade>0?Math.max(0,Math.min(1,(t-current.time)/fade)):1;
  if(previous&&progress<1&&bankState[0].length){
    await seekOfflineBank(0,previous,t);
    drawBank(0,1-progress);
    const saved=activeBank;activeBank=1;drawBank(1,progress);activeBank=saved;
  }else{
    const saved=activeBank;activeBank=1;drawBank(1,1);activeBank=saved;
  }
  activeScene=current;
  if(clockNowMs()<freezeUntil)fx.drawImage(freezeCanvas,0,0);else applyPostFx();
}
window.tubevizOfflineInit=async function(options={}){
  if(!offlineMode)throw new Error('tubeviz offline API requires ?offline=1');
  offlineFps=Math.max(1,Number(options.fps??60));
  offlineTime=0;offlineCueIndex=0;offlineLoadedScene=-1;frameCounter=0;phase=0;
  offlineRandState=(Number(options.seed??0x51f15e)>>>0)||0x51f15e;
  fragments.length=0;motifObjects.clear();pauseAll();
  document.querySelector('#hud')?.remove();
  await prepareOfflineScene(sceneIndexAt(0));processOfflineCues(0);
  return {duration:timeline.track.duration,scenes:timeline.scene_plan.length,fps:offlineFps};
};
window.tubevizRenderFrame=async function(t,frameIndex){
  if(!offlineMode)throw new Error('tubeviz offline API requires ?offline=1');
  offlineTime=Math.max(0,Number(t));
  offlineRandState=(((Number(frameIndex)+1)*2654435761)>>>0)||1;
  const index=sceneIndexAt(offlineTime);
  await prepareOfflineScene(index);
  processOfflineCues(offlineTime);
  advanceDynamics();
  await renderOfflineVideo(offlineTime,index);
  drawOverlay();
  return {time:offlineTime,frame:Number(frameIndex)};
};

function exportMime(format){return format==='jpeg'?'image/jpeg':'image/png';}
window.tubevizExportFrame=async function(format='jpeg',quality=.92){
  if(!offlineMode)throw new Error('tubeviz offline API requires ?offline=1');
  exportCtx.globalCompositeOperation='source-over';
  exportCtx.globalAlpha=1;
  exportCtx.fillStyle='#000';
  exportCtx.fillRect(0,0,width,height);
  exportCtx.drawImage(videoFx,0,0,width,height);
  exportCtx.drawImage(canvas,0,0,width,height);

  const blob=await new Promise((resolve,reject)=>{
    exportCanvas.toBlob(
      b=>b?resolve(b):reject(new Error('canvas frame export failed')),
      exportMime(format),
      Math.max(0,Math.min(1,Number(quality)))
    );
  });
  const bytes=new Uint8Array(await blob.arrayBuffer());
  let binary='';
  const chunk=0x8000;
  for(let i=0;i<bytes.length;i+=chunk){
    binary+=String.fromCharCode(...bytes.subarray(i,i+chunk));
  }
  return btoa(binary);
};
window.tubevizRenderAndExport=async function(t,frameIndex,format='jpeg',quality=.92){
  const start=window.performance.now();
  await window.tubevizRenderFrame(t,frameIndex);
  const rendered=window.performance.now();
  const data=await window.tubevizExportFrame(format,quality);
  const exported=window.performance.now();
  return {
    data,
    render_ms:rendered-start,
    export_ms:exported-rendered
  };
};

if(!offlineMode)requestAnimationFrame(frame);
