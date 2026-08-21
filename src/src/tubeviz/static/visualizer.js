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
const delayBuffers=[delayA,delayB,delayC];
const delayCtx=[delayACtx,delayBCtx,delayCCtx];
let delayWrite=0;

function resize(){
  width=canvas.width=videoFx.width=Math.floor(innerWidth*devicePixelRatio);
  height=canvas.height=videoFx.height=Math.floor(innerHeight*devicePixelRatio);
  for(const c of [history,scratch,freezeCanvas,holdCanvas,edgeCanvas]){c.width=width;c.height=height;}
  for(const c of delayBuffers){c.width=Math.max(1,Math.floor(width/2));c.height=Math.max(1,Math.floor(height/2));}
  exportCanvas.width=width;exportCanvas.height=height;
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
function mediaUrl(layer){if(layer.media_url)return layer.media_url;return `/media/${layer.media_file.split('/').map(encodeURIComponent).join('/')}`;}
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
    activeScene={...scene};focusLayer=0;
    const t=scene.transform??{};
    const fxNames=['ripple','kaleidoscope','tiles','tunnel','posterize','edge','strobe','shutter','slit_scan','frame_echo','mirror_corridor','mask_wipe','solarize','datamosh','block_displace','chroma_delay','vhs_tracking','vortex','motion_trails','slice_recursion'].filter(k=>(t[k]??0)>.08).join(',');
    clipMeta.textContent=`${scene.term}${scene.motif_id?` · ${scene.motif_id} #${scene.occurrence}`:''} · ${scene.composition_mode} · ${1+(scene.layers?.length??0)} video layers · ${scene.title??scene.source_id}${fxNames?` · fx ${fxNames}`:''}`;
  }catch(e){console.warn('scene activation failed',e);clipMeta.textContent=`Clip group unavailable: ${scene.title??scene.source_id}`;}
}

function transformedRect(t,rect){
  const zoom=Math.max(1,t.zoom??1)*(1+punch*.11),panX=(t.pan_x??0)*rect.w*.20,panY=(t.pan_y??0)*rect.h*.20;
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

function applyPostFx(){
  if(!activeScene)return;
  const t=activeScene.transform??{},m=liveFx.master;
  const motion=m*liveFx.motion,trails=m*liveFx.trails,glitchScale=m*liveFx.glitch,strobeScale=m*liveFx.strobe;

  const feedback=Math.min(1,(t.feedback??0)*trails);
  const glitch=Math.min(1,((t.glitch??0)+sliceFx)*glitchScale);
  const pixel=Math.min(1,(t.pixelate??0)*glitchScale);
  const rgb=Math.min(1,(t.rgb_split??0)*glitchScale);
  const scan=Math.min(1,(t.scanlines??0)*m);
  const vignette=Math.min(1,(t.vignette??0)*m);
  const ripple=Math.min(1,((t.ripple??0)+rippleFx)*motion);
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
  const datamosh=Math.min(1,((t.datamosh??0)+datamoshFx)*glitchScale);
  const blocks=Math.min(1,(t.block_displace??0)*glitchScale);
  const chromaDelay=Math.min(1,((t.chroma_delay??0)+chromaDelayFx)*trails);
  const tracking=Math.min(1,(t.vhs_tracking??0)*glitchScale);
  const vortex=Math.min(1,((t.vortex??0)+vortexFx)*motion);
  const motionTrails=Math.min(1,((t.motion_trails??0)+motionTrailFx)*trails);
  const sliceRecursion=Math.min(1,((t.slice_recursion??0)+sliceRecursionFx)*motion);

  // Capture the pre-temporal frame before time-based effects mutate it.
  captureDelayFrame();

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
  activeBank=1;activeScene={...current};focusLayer=0;transition=null;offlineLoadedScene=index;
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
