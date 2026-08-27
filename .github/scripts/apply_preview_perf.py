from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise RuntimeError(f"expected text not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, *, minimum: int = 1) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count < minimum:
        raise RuntimeError(f"expected at least {minimum} occurrences of {old!r} in {path}, found {count}")
    p.write_text(text.replace(old, new))


VIS = "src/tubeviz/static/visualizer.js"

replace_once(
    VIS,
    """const ctx = canvas.getContext('2d', {alpha:true});
const videoFx = document.querySelector('#video-fx');
const fx = videoFx.getContext('2d', {alpha:false});""",
    """const ctx = canvas.getContext('2d', {alpha:true,desynchronized:true});
const videoFx = document.querySelector('#video-fx');
const fx = videoFx.getContext('2d', {alpha:false,desynchronized:true});""",
)

replace_once(
    VIS,
    """const offlineMode=query.get('offline')==='1';
const browserGpuMode=(query.get('gpu')||'auto').toLowerCase();
const previewQuality=(query.get('preview')||'auto').toLowerCase();
let adaptivePreviewHeight=720,renderPixelRatio=1,previewFrameEma=0,previewLastResize=0;""",
    """const offlineMode=query.get('offline')==='1';
const browserGpuMode=(query.get('gpu')||'auto').toLowerCase();
const previewQuality=(query.get('preview')||'auto').toLowerCase();
const previewProfile=(query.get('preview_profile')||'responsive').toLowerCase();
const responsivePreview=!offlineMode&&previewProfile!=='full';
const adaptivePreviewSteps=responsivePreview?[360,480,540,720]:[540,720,1080];
let adaptivePreviewHeight=responsivePreview?540:720,renderPixelRatio=1,previewFrameEma=0,previewLastResize=0;
let previewFrameIntervalEma=0,previewMeasuredFps=0,previewLastStatus=0,lastLiveRenderAt=0;""",
)

replace_once(
    VIS,
    """function updateRendererStatus(extra=''){
  if(!renderMeta)return;
  const renderer=browserGpuActive?'WebGPU':'Canvas2D';
  const reason=String(extra||gpuInit.reason||'');
  renderMeta.textContent=`Preview renderer: ${renderer}${reason?` · ${reason}`:''}`;
}""",
    """function previewTargetFps(){
  if(offlineMode||!responsivePreview)return 60;
  if(previewFrameEma>52)return 20;
  if(previewFrameEma>34)return 24;
  return 30;
}
function updateRendererStatus(extra=''){
  if(!renderMeta)return;
  const renderer=browserGpuActive?'WebGPU':'Canvas2D';
  const reason=String(extra||gpuInit.reason||'');
  const profile=responsivePreview?'responsive':'full';
  const size=width>0&&height>0?`${width}×${height}`:'resolving';
  const fps=previewMeasuredFps>0?`${previewMeasuredFps.toFixed(0)} fps`:`≤${previewTargetFps()} fps`;
  const cpu=previewFrameEma>0?` · CPU ${previewFrameEma.toFixed(1)} ms`:'';
  renderMeta.textContent=`Preview renderer: ${renderer} · ${profile} · ${size} · ${fps}${cpu}${reason?` · ${reason}`:''}`;
}""",
)

replace_once(
    VIS,
    """function offscreen(alpha=false){const c=document.createElement('canvas');return [c,c.getContext('2d',{alpha})];}
const [history,historyCtx]=offscreen(false);
const [scratch,scratchCtx]=offscreen(true);""",
    """function offscreen(alpha=false,readFrequently=false){
  const c=document.createElement('canvas');
  return[c,c.getContext('2d',{alpha,desynchronized:true,willReadFrequently:readFrequently})];
}
const [history,historyCtx]=offscreen(false);
const [scratch,scratchCtx]=offscreen(true);""",
)

for old, new in [
    ("const [posterCanvas,posterCtx]=offscreen(false);", "const [posterCanvas,posterCtx]=offscreen(false,true);"),
    ("const [vectorSample,vectorSampleCtx]=offscreen(false);", "const [vectorSample,vectorSampleCtx]=offscreen(false,true);"),
    ("const [motionProbe,motionProbeCtx]=offscreen(false);", "const [motionProbe,motionProbeCtx]=offscreen(false,true);"),
    ("const [motionPrev,motionPrevCtx]=offscreen(false);", "const [motionPrev,motionPrevCtx]=offscreen(false,true);"),
    ("const [flowProbe,flowProbeCtx]=offscreen(false);", "const [flowProbe,flowProbeCtx]=offscreen(false,true);"),
    ("const [flowPrev,flowPrevCtx]=offscreen(false);", "const [flowPrev,flowPrevCtx]=offscreen(false,true);"),
    ("const [depthProbe,depthProbeCtx]=offscreen(false);", "const [depthProbe,depthProbeCtx]=offscreen(false,true);"),
    ("const [channelSample,channelSampleCtx]=offscreen(false);", "const [channelSample,channelSampleCtx]=offscreen(false,true);"),
]:
    replace_once(VIS, old, new)

replace_once(
    VIS,
    """  vectorSample.width=128;vectorSample.height=72;
  vectorScratch.width=width;vectorScratch.height=height;
  motionProbe.width=64;motionProbe.height=36;motionPrev.width=64;motionPrev.height=36;
  motionPrevCtx.fillStyle='#000';motionPrevCtx.fillRect(0,0,64,36);
  flowProbe.width=64;flowProbe.height=36;flowPrev.width=64;flowPrev.height=36;
  flowPrevCtx.fillStyle='#000';flowPrevCtx.fillRect(0,0,64,36);
  depthProbe.width=16;depthProbe.height=9;subjectMask.width=16;subjectMask.height=9;creativeDepthCache={frame:-1,cells:[],cols:16,rows:9};
  channelSample.width=channelOut.width=Math.max(120,Math.min(280,Math.floor(width/6)));
  channelSample.height=channelOut.height=Math.max(68,Math.round(channelSample.width*height/Math.max(1,width)));""",
    """  vectorSample.width=responsivePreview?96:128;vectorSample.height=responsivePreview?54:72;
  vectorScratch.width=width;vectorScratch.height=height;
  const probeW=responsivePreview?48:64,probeH=responsivePreview?27:36;
  motionProbe.width=probeW;motionProbe.height=probeH;motionPrev.width=probeW;motionPrev.height=probeH;
  motionPrevCtx.fillStyle='#000';motionPrevCtx.fillRect(0,0,probeW,probeH);
  flowProbe.width=probeW;flowProbe.height=probeH;flowPrev.width=probeW;flowPrev.height=probeH;
  flowPrevCtx.fillStyle='#000';flowPrevCtx.fillRect(0,0,probeW,probeH);
  depthProbe.width=16;depthProbe.height=9;subjectMask.width=16;subjectMask.height=9;creativeDepthCache={frame:-1,cells:[],cols:16,rows:9};
  const channelMax=responsivePreview?200:280;
  channelSample.width=channelOut.width=Math.max(100,Math.min(channelMax,Math.floor(width/6)));
  channelSample.height=channelOut.height=Math.max(56,Math.round(channelSample.width*height/Math.max(1,width)));""",
)

replace_once(
    VIS,
    """  posterCanvas.width=Math.max(96,Math.min(320,Math.floor(width/5)));
  posterCanvas.height=Math.max(54,Math.min(180,Math.floor(height/5)));
  delayWrite=0;delayCount=0;historyReady=false;
  historyCtx.fillStyle='#000';historyCtx.fillRect(0,0,width,height);
}""",
    """  const posterMaxW=responsivePreview?240:320,posterMaxH=responsivePreview?135:180;
  posterCanvas.width=Math.max(96,Math.min(posterMaxW,Math.floor(width/5)));
  posterCanvas.height=Math.max(54,Math.min(posterMaxH,Math.floor(height/5)));
  delayWrite=0;delayCount=0;historyReady=false;
  historyCtx.fillStyle='#000';historyCtx.fillRect(0,0,width,height);
  updateRendererStatus();
}""",
)

replace_once(
    VIS,
    """function updateAdaptivePreview(frameMs){
  if(offlineMode||previewQuality!=='auto'||!Number.isFinite(frameMs))return;
  previewFrameEma=previewFrameEma?previewFrameEma*.92+frameMs*.08:frameMs;
  const now=performance.now();if(now-previewLastResize<2500)return;
  let next=adaptivePreviewHeight;
  if(previewFrameEma>37&&adaptivePreviewHeight>540)next=adaptivePreviewHeight>=1080?720:540;
  else if(previewFrameEma<18&&adaptivePreviewHeight<1080)next=adaptivePreviewHeight<=540?720:1080;
  if(next!==adaptivePreviewHeight){adaptivePreviewHeight=next;previewLastResize=now;resize();}
}""",
    """function updateAdaptivePreview(frameMs){
  if(offlineMode||!Number.isFinite(frameMs))return;
  previewFrameEma=previewFrameEma?previewFrameEma*.86+frameMs*.14:frameMs;
  const now=performance.now();
  if(previewQuality!=='auto')return;
  const minimumWait=responsivePreview?900:2500;
  if(now-previewLastResize<minimumWait)return;
  let index=Math.max(0,adaptivePreviewSteps.indexOf(adaptivePreviewHeight));
  let next=index;
  if(previewFrameEma>52)next=Math.max(0,index-2);
  else if(previewFrameEma>30)next=Math.max(0,index-1);
  else if(previewFrameEma<15&&now-previewLastResize>6000)next=Math.min(adaptivePreviewSteps.length-1,index+1);
  if(next!==index){adaptivePreviewHeight=adaptivePreviewSteps[next];previewLastResize=now;resize();}
}""",
)

replace_once(
    VIS,
    """function extractVectorEdges(force=false){
  if(!force&&vectorEdgeCache.frame>=0&&frameCounter-vectorEdgeCache.frame<4)return vectorEdgeCache;""",
    """function extractVectorEdges(force=false){
  const cacheFrames=responsivePreview?8:4;
  if(!force&&vectorEdgeCache.frame>=0&&frameCounter-vectorEdgeCache.frame<cacheFrames)return vectorEdgeCache;""",
)

replace_once(
    VIS,
    """function updateOpticalFlow(force=false){
  if(!force&&vectorFlowCache.frame>=0&&frameCounter-vectorFlowCache.frame<2)return vectorFlowCache;""",
    """function updateOpticalFlow(force=false){
  const cacheFrames=responsivePreview?4:2;
  if(!force&&vectorFlowCache.frame>=0&&frameCounter-vectorFlowCache.frame<cacheFrames)return vectorFlowCache;""",
)

replace_once(
    VIS,
    """function renderVectorSceneGraph(){
  const allEffects=activeScene?.direction?.vector_effects;if(!Array.isArray(allEffects)||!allEffects.length)return;""",
    """function renderVectorSceneGraph(){
  const allEffects=activeScene?.direction?.vector_effects;if(!Array.isArray(allEffects)||!allEffects.length)return;
  if(responsivePreview&&previewFrameEma>36)return;""",
)

replace_once(
    VIS,
    """  const budget=(role==='payoff'&&sectionEnergy>.76)?2:1,effects=[...visible.slice(0,budget),...hidden];""",
    """  const budget=responsivePreview?1:((role==='payoff'&&sectionEnergy>.76)?2:1);
  // Hidden vector deformations are valuable for final fidelity but are the most
  // expensive part of live Canvas geometry. Responsive preview renders only the
  // strongest visible family and leaves the full hidden stack to full/offline mode.
  const effects=responsivePreview?visible.slice(0,budget):[...visible.slice(0,budget),...hidden];""",
)

replace_once(
    VIS,
    """  const gpuCommon=!!browserGpuFinalizer;

  // Directed color happens on the composed video, then temporal processing""",
    """  const gpuCommon=!!browserGpuFinalizer;
  const previewLite=responsivePreview;

  // Directed color happens on the composed video, then temporal processing""",
)

replace_once(
    VIS,
    """  if(!gpuCommon){
    applyDirectedColor();
    applySpectralDisplacement(Math.min(1,directedWarp+beatWarpFx*.20));
    applyPrismaticShift(Math.min(1,directedChroma+(activeScene?.direction?.color?.chromatic_aberration??0)*.25));
    if(directedBloom>.02){snapshot();fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.08+.28*directedBloom;if('filter'in fx)fx.filter=`brightness(${1+.45*directedBloom}) saturate(${1+.35*directedBloom})`;fx.drawImage(scratch,0,0,width,height);fx.restore();}
  }

  // WebGPU keeps temporal history resident on the GPU. Only the rare Canvas2D
  // mask path still needs the half-resolution CPU delay ring when GPU is active.
  const needsCpuDelay=!gpuCommon||mask>.025;
  if(needsCpuDelay)captureDelayFrame();""",
    """  if(!gpuCommon){
    applyDirectedColor();
    if(!previewLite){
      applySpectralDisplacement(Math.min(1,directedWarp+beatWarpFx*.20));
      applyPrismaticShift(Math.min(1,directedChroma+(activeScene?.direction?.color?.chromatic_aberration??0)*.25));
      if(directedBloom>.02){snapshot();fx.save();fx.globalCompositeOperation='screen';fx.globalAlpha=.08+.28*directedBloom;if('filter'in fx)fx.filter=`brightness(${1+.45*directedBloom}) saturate(${1+.35*directedBloom})`;fx.drawImage(scratch,0,0,width,height);fx.restore();}
    }
  }

  // Responsive live preview avoids CPU delay/history readback entirely. Full
  // preview and offline rendering retain the exact compatibility paths.
  const needsCpuDelay=!previewLite&&(!gpuCommon||mask>.025);
  if(needsCpuDelay)captureDelayFrame();""",
)

replace_once(
    VIS,
    """  if(!gpuCommon){
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
    applyRecursiveFeedbackCreative(creativeFeedback);
  }
  // Local symmetry and hero effects are intentionally rare and remain on the
  // compatibility compositor until their semantics can be expressed exactly.
  applyLocalSymmetryCreative(creativeSymmetry);
  applyHeroCreative(gpuCommon);

  applyShutter(shutter);
  const beatState=currentBeatWarpState();
  if(!gpuCommon)applyBeatWarp(beatState);
  if(!gpuCommon)applyTempoWarp(tempoWarpFx);
  if(!gpuCommon)applySlitScan(slitScan);
  if(!gpuCommon)applyMotionTrails(motionTrails);
  if(!gpuCommon)applyFrameEcho(frameEcho);
  if(!gpuCommon)applyRipple(ripple);
  if(!gpuCommon)applyBlockDisplace(blocks);
  if(!gpuCommon)applyDatamosh(datamosh);
  if(!gpuCommon)applyVhsTracking(tracking);
  applyTiles(tiles);
  applyMirrorCorridor(corridor);
  applyKaleidoscope(kaleido);
  applyVortex(vortex);
  applyTunnel(tunnel);
  applySliceRecursion(sliceRecursion);
  applyMaskWipe(mask);
  if(!gpuCommon){applyPosterize(posterize);applySolarize(solarize);applyEdge(edge);applyPixel(pixel);}
  if(!gpuCommon){applyChromaDelay(chromaDelay);applyRgbSplit(rgb);}
  if(!gpuCommon)applyGlitch(glitch);
  if(!gpuCommon)applyFeedback(feedback);""",
    """  if(!gpuCommon&&!previewLite){
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
    applyRecursiveFeedbackCreative(creativeFeedback);
  }
  // Full/offline mode keeps exact CPU-local semantics. Responsive mode expresses
  // their musical energy through the fused GPU/cheap Canvas approximation below.
  if(!previewLite){
    applyLocalSymmetryCreative(creativeSymmetry);
    applyHeroCreative(gpuCommon);
    applyShutter(shutter);
  }

  const beatState=currentBeatWarpState();
  if(!gpuCommon){
    const liveBeat=previewLite?{...beatState,amount:beatState.amount*.72}:beatState;
    applyBeatWarp(liveBeat);
  }
  if(!gpuCommon&&!previewLite)applyTempoWarp(tempoWarpFx);
  if(!gpuCommon&&!previewLite)applySlitScan(slitScan);
  if(!gpuCommon&&!previewLite)applyMotionTrails(motionTrails);
  if(!gpuCommon&&!previewLite)applyFrameEcho(frameEcho);
  if(!gpuCommon){
    const liveRipple=previewLite?Math.min(1,ripple+.18*kaleido+.22*vortex+.18*tunnel+.14*sliceRecursion):ripple;
    applyRipple(liveRipple);
  }
  if(!gpuCommon&&!previewLite)applyBlockDisplace(blocks);
  if(!gpuCommon&&!previewLite)applyDatamosh(datamosh);
  if(!gpuCommon&&!previewLite)applyVhsTracking(tracking);
  if(!previewLite){
    applyTiles(tiles);
    applyMirrorCorridor(corridor);
    applyKaleidoscope(kaleido);
    applyVortex(vortex);
    applyTunnel(tunnel);
    applySliceRecursion(sliceRecursion);
    applyMaskWipe(mask);
  }
  if(!gpuCommon&&!previewLite){applyPosterize(posterize);applySolarize(solarize);applyEdge(edge);applyPixel(pixel);}
  if(!gpuCommon&&!previewLite){applyChromaDelay(chromaDelay);applyRgbSplit(rgb);}
  if(!gpuCommon)applyGlitch(previewLite?glitch*.70:glitch);
  if(!gpuCommon)applyFeedback(previewLite?feedback*.65:feedback);""",
)

replace_once(
    VIS,
    """  renderVectorSceneGraph();

  let gpuFinished=false;""",
    """  renderVectorSceneGraph();

  let gpuFinished=false;""",
)

replace_once(
    VIS,
    """    gpuFinished=browserGpuFinalizer.render(videoFx,sourceColorAnchor,{
      fidelity:sourceFidelityAlpha(),vignette,scanlines:scan,strobe,time:clockSeconds(),
      warp:Math.min(1,directedWarp+creativeFlow*.75+ripple*.42),
      chroma:Math.min(1,directedChroma+rgb*.55+chromaDelay*.45+heroChroma*.45),depth:Math.min(1,creativeDepth+heroDepth*.82),
      bloom:Math.min(1,directedBloom+creativeBloom*.75),paletteStrength:creativePalette,palette:colorToRgb01(palette),
      feedback:Math.min(1,feedback+creativeFeedback*.8+heroFeedback*.62),temporal:Math.min(1,creativeTemporal+creativeSmear*.5+frameEcho*.45+motionTrails*.35+heroTemporal*.65),
      flow:Math.min(1,creativeFlow+heroFlow*.85),targetX:target.x/Math.max(1,width),targetY:target.y/Math.max(1,height),""",
    """    const previewStructural=previewLite?Math.min(1,kaleido*.35+vortex*.45+tunnel*.35+sliceRecursion*.30+corridor*.20+creativeSymmetry*.24):0;
    gpuFinished=browserGpuFinalizer.render(videoFx,sourceColorAnchor,{
      fidelity:sourceFidelityAlpha(),vignette,scanlines:scan,strobe,time:clockSeconds(),
      warp:Math.min(1,directedWarp+creativeFlow*.75+ripple*.42+previewStructural*.42),
      chroma:Math.min(1,directedChroma+rgb*.55+chromaDelay*.45+heroChroma*.45),depth:Math.min(1,creativeDepth+heroDepth*.82+previewStructural*.12),
      bloom:Math.min(1,directedBloom+creativeBloom*.75),paletteStrength:creativePalette,palette:colorToRgb01(palette),
      feedback:Math.min(1,feedback+creativeFeedback*.8+heroFeedback*.62+previewStructural*.12),temporal:Math.min(1,creativeTemporal+creativeSmear*.5+frameEcho*.45+motionTrails*.35+heroTemporal*.65+previewStructural*.18),
      flow:Math.min(1,creativeFlow+heroFlow*.85+previewStructural*.18),targetX:target.x/Math.max(1,width),targetY:target.y/Math.max(1,height),""",
)

replace_once(
    VIS,
    """function drawOverlay(){
  ctx.clearRect(0,0,width,height);
  if(activeBank<0)return;
  ctx.save();ctx.globalCompositeOperation='screen';

  // Onset fragments are now fluid refraction droplets. They never draw a
  // rectangular video patch, which eliminates the intermittent square overlays.
  for(let i=fragments.length-1;i>=0;i--){""",
    """function drawOverlay(){
  ctx.clearRect(0,0,width,height);
  if(activeBank<0)return;
  ctx.save();ctx.globalCompositeOperation='screen';

  // Onset fragments are now fluid refraction droplets. They never draw a
  // rectangular video patch, which eliminates the intermittent square overlays.
  let fragmentDrawn=0;
  for(let i=fragments.length-1;i>=0;i--){""",
)

replace_once(
    VIS,
    """    f.x+=f.vx*.006;f.y+=f.vy*.006;f.life*=.962;
    if(f.life<.03){fragments.splice(i,1);continue;}

    const cx=f.x*width,cy=f.y*height;""",
    """    f.x+=f.vx*.006;f.y+=f.vy*.006;f.life*=.962;
    if(f.life<.03){fragments.splice(i,1);continue;}
    if(responsivePreview&&fragmentDrawn>=3)continue;
    fragmentDrawn++;

    const cx=f.x*width,cy=f.y*height;""",
)

replace_once(
    VIS,
    """  let mi=0;
  for(const m of motifObjects.values()){""",
    """  let mi=0,motifDrawn=0;
  for(const m of motifObjects.values()){""",
)

replace_once(
    VIS,
    """    m.visualStrength=(m.visualStrength??0)*.94;
    if(m.visualStrength<=.025){mi++;continue;}

    const strength=Math.min(1,m.visualStrength);""",
    """    m.visualStrength=(m.visualStrength??0)*.94;
    if(m.visualStrength<=.025){mi++;continue;}
    if(responsivePreview&&motifDrawn>=2){mi++;continue;}
    motifDrawn++;

    const strength=Math.min(1,m.visualStrength);""",
)

replace_once(
    VIS,
    """let liveFrameScheduled=false;
function primaryLiveVideo(){
  if(activeBank<0)return null;
  return bankState[activeBank]?.[0]?.video??null;
}
function scheduleLiveFrame(){
  if(offlineMode||liveFrameScheduled)return;
  liveFrameScheduled=true;
  const v=primaryLiveVideo();
  if(v&&!v.paused&&typeof v.requestVideoFrameCallback==='function'){
    v.requestVideoFrameCallback(()=>{liveFrameScheduled=false;frame();});
  }else if(audio.paused){
    setTimeout(()=>{liveFrameScheduled=false;frame();},100);
  }else{
    requestAnimationFrame(()=>{liveFrameScheduled=false;frame();});
  }
}
function frame(){
  const started=performance.now();
  advanceDynamics();
  renderVideo();
  if(browserGpuFinalizer&&!activeScene)browserGpuFinalizer.render(videoFx,videoFx,{time:clockSeconds()});
  drawOverlay();maintainRanges();
  updateAdaptivePreview(performance.now()-started);
  scheduleLiveFrame();
}""",
    """let liveFrameScheduled=false;
function primaryLiveVideo(){
  if(activeBank<0)return null;
  return bankState[activeBank]?.[0]?.video??null;
}
function runLiveFrame(now=performance.now()){
  const targetMs=1000/previewTargetFps();
  const elapsed=lastLiveRenderAt>0?now-lastLiveRenderAt:targetMs;
  const delay=responsivePreview?Math.max(0,targetMs-elapsed):0;
  if(delay>1){
    setTimeout(()=>{liveFrameScheduled=false;frame();},delay);
  }else{
    liveFrameScheduled=false;frame();
  }
}
function scheduleLiveFrame(){
  if(offlineMode||liveFrameScheduled)return;
  liveFrameScheduled=true;
  const v=primaryLiveVideo();
  if(v&&!v.paused&&typeof v.requestVideoFrameCallback==='function'){
    v.requestVideoFrameCallback(now=>runLiveFrame(now));
  }else if(audio.paused){
    setTimeout(()=>{liveFrameScheduled=false;frame();},100);
  }else{
    requestAnimationFrame(now=>runLiveFrame(now));
  }
}
function frame(){
  const started=performance.now();
  if(lastLiveRenderAt>0){
    const interval=Math.max(1,started-lastLiveRenderAt);
    previewFrameIntervalEma=previewFrameIntervalEma?previewFrameIntervalEma*.88+interval*.12:interval;
    previewMeasuredFps=1000/previewFrameIntervalEma;
  }
  lastLiveRenderAt=started;
  advanceDynamics();
  renderVideo();
  if(browserGpuFinalizer&&!activeScene)browserGpuFinalizer.render(videoFx,videoFx,{time:clockSeconds()});
  drawOverlay();maintainRanges();
  updateAdaptivePreview(performance.now()-started);
  const now=performance.now();
  if(now-previewLastStatus>600){previewLastStatus=now;updateRendererStatus();}
  scheduleLiveFrame();
}""",
)

# Studio preview controls: responsive is the default interaction mode; full preserves exact live behavior.
GUI_HTML = "src/tubeviz/static/gui.html"
replace_once(
    GUI_HTML,
    """      <div class="grid two tight">
        <label>Preview quality
          <select id="previewQuality"><option value="auto">auto · adaptive 540p–1080p</option><option value="540p">540p</option><option value="720p">720p</option><option value="1080p">1080p</option><option value="native">native display density</option></select>
        </label>
        <label>Preview GPU
          <select id="previewGpu"><option value="auto">auto · WebGPU if available</option><option value="webgpu">prefer WebGPU · safe fallback</option><option value="off">Canvas2D only</option></select>
        </label>
      </div>""",
    """      <div class="grid three tight">
        <label>Preview mode
          <select id="previewMode"><option value="responsive">responsive · optimized live FX</option><option value="full">full fidelity · slower</option></select>
        </label>
        <label>Preview quality
          <select id="previewQuality"><option value="auto">auto · adaptive 360p–720p</option><option value="360p">360p</option><option value="540p">540p</option><option value="720p">720p</option><option value="1080p">1080p</option><option value="native">native display density</option></select>
        </label>
        <label>Preview GPU
          <select id="previewGpu"><option value="auto">auto · WebGPU if available</option><option value="webgpu">prefer WebGPU · safe fallback</option><option value="off">Canvas2D only</option></select>
        </label>
      </div>""",
)

# Add explicit 360p sizing.
replace_once(
    VIS,
    """  if(previewQuality==='540p')targetHeight=540;
  else if(previewQuality==='720p')targetHeight=720;""",
    """  if(previewQuality==='360p')targetHeight=360;
  else if(previewQuality==='540p')targetHeight=540;
  else if(previewQuality==='720p')targetHeight=720;""",
)

GUI_JS = "src/tubeviz/static/gui.js"
replace_once(
    GUI_JS,
    """  analysisPreset:"Curated starting point for the creative/editing controls below. Presets never choose devices, credentials, models, or paid AI features. Every applied value remains editable.",""",
    """  analysisPreset:"Curated starting point for the creative/editing controls below. Presets never choose devices, credentials, models, or paid AI features. Every applied value remains editable.",
  previewMode:"Responsive preview prioritizes smooth interaction by capping live frame rate, adapting resolution, and approximating CPU-heavy effects. Full fidelity preserves exact browser effect paths at higher cost.",""",
)

replace_once(
    GUI_JS,
    """    waitForPreview(job.id,job.preview_url,preview,{quality:value("previewQuality")||"auto",gpu:value("previewGpu")||"auto"});""",
    """    waitForPreview(job.id,job.preview_url,preview,{profile:value("previewMode")||"responsive",quality:value("previewQuality")||"auto",gpu:value("previewGpu")||"auto"});""",
)

replace_once(
    GUI_JS,
    """          previewWindow.location=`${url}${sep}studio_preview=${encodeURIComponent(jobId)}&preview=${encodeURIComponent(previewOptions.quality||"auto")}&gpu=${encodeURIComponent(previewOptions.gpu||"auto")}&t=${Date.now()}`;""",
    """          previewWindow.location=`${url}${sep}studio_preview=${encodeURIComponent(jobId)}&preview_profile=${encodeURIComponent(previewOptions.profile||"responsive")}&preview=${encodeURIComponent(previewOptions.quality||"auto")}&gpu=${encodeURIComponent(previewOptions.gpu||"auto")}&t=${Date.now()}`;""",
)

TEST = "tests/test_render_optimization.py"
replace_once(TEST, '    assert "adaptivePreviewHeight=720" in js\n', '    assert "adaptivePreviewHeight=responsivePreview?540:720" in js\n')
replace_once(
    TEST,
    """    assert "updateAdaptivePreview" in js
    assert "createBrowserGpuFinalizer" in js""",
    """    assert "updateAdaptivePreview" in js
    assert "adaptivePreviewSteps=responsivePreview?[360,480,540,720]" in js
    assert "previewTargetFps" in js
    assert "preview_profile" in js
    assert "willReadFrequently:readFrequently" in js
    assert "createBrowserGpuFinalizer" in js""",
)
replace_once(
    TEST,
    """    for token in ("posterize", "solarize", "blockDisplace", "slitScan", "datamosh"):
        assert token in gpu
""",
    """    for token in ("posterize", "solarize", "blockDisplace", "slitScan", "datamosh"):
        assert token in gpu


def test_studio_defaults_to_responsive_preview_profile():
    html = Path("src/tubeviz/static/gui.html").read_text()
    gui = Path("src/tubeviz/static/gui.js").read_text()
    assert 'id="previewMode"' in html
    assert '<option value="responsive">responsive · optimized live FX</option>' in html
    assert "auto · adaptive 360p–720p" in html
    assert "preview_profile=" in gui
    assert 'profile:value("previewMode")||"responsive"' in gui


def test_responsive_preview_throttles_expensive_live_paths():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "const responsivePreview=!offlineMode&&previewProfile!=='full'" in js
    assert "const targetMs=1000/previewTargetFps()" in js
    assert "if(responsivePreview&&previewFrameEma>36)return" in js
    assert "const effects=responsivePreview?visible.slice(0,budget)" in js
    assert "if(!gpuCommon&&!previewLite)" in js
    assert "fragmentDrawn>=3" in js
    assert "motifDrawn>=2" in js
""",
)

# Version/cache bump.
replace_all("pyproject.toml", 'version = "0.40.1"', 'version = "0.40.2"')
replace_all("src/tubeviz/__init__.py", '__version__ = "0.40.1"', '__version__ = "0.40.2"')
replace_all("src/tubeviz/native_src/src/main.cpp", "0.40.1", "0.40.2")
replace_all(GUI_HTML, "v=0.40.1", "v=0.40.2")

changelog = Path("CHANGELOG.md")
text = changelog.read_text()
heading = "# 0.40.2 — Responsive web preview\n"
if not text.startswith(heading):
    changelog.write_text(
        heading
        + """
- Make Studio's browser preview **responsive by default** while leaving deterministic offline/browser rendering and final native output unchanged. A new Preview mode selector keeps full-fidelity live behavior available explicitly when exact browser-effect inspection matters more than interaction speed.
- Cap responsive live preview at roughly 30 fps, with automatic 24/20 fps backoff when the main-thread compositor is overloaded. `requestVideoFrameCallback()` remains the source clock, but 60 fps footage no longer forces tubeviz to run the entire preview compositor 60 times per second.
- Start adaptive preview at 540p and use a 360p/480p/540p/720p ladder. Slow frames downshift quickly and recovery upshifts conservatively; the previous automatic path could climb to 1080p and never fall below 540p.
- Skip the hidden vector-deformation stack during responsive preview, render at most one visible vector family, cache edge/flow probes longer, and suspend vector work completely while frame cost remains high. Full/offline rendering retains the complete vector graph.
- Approximate CPU-only local symmetry, hero/structural, temporal and deformation treatments through the fused WebGPU parameters (or cheap Canvas beat/ripple/glitch punctuation when WebGPU is unavailable) instead of executing every full-resolution Canvas path on every live frame.
- Mark readback-heavy probe canvases with `willReadFrequently`, use smaller responsive vector/flow/RGB/posterization probes, and request desynchronized display Canvas contexts to reduce GPU↔CPU synchronization stalls.
- Bound live overlay refractions to three onset fragments and two motif refractions per displayed frame while still updating the complete logical overlay state.
- Expand the preview HUD with the active renderer, responsive/full profile, current internal resolution, measured display fps and main-thread frame cost so preview degradation is visible instead of mysterious.

"""
        + text
    )
