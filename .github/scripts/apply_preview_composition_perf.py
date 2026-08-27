from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise RuntimeError(f"expected text not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


vis = "src/tubeviz/static/visualizer.js"

replace_once(
    vis,
    """function drawBank(bankIndex,alpha){
  const states=bankState[bankIndex];if(!states.length)return;let mode=bankMode[bankIndex]??'single';
  if(mode==='pip')mode='flow';
  const order=states.map((_,i)=>(i+focusLayer)%states.length);

  if(mode==='flow'&&states.length>1){
    drawLayer(fx,states[order[0]],{x:0,y:0,w:width,h:height},alpha,'source-over');
    for(let oi=1;oi<order.length;oi++)drawFlowLayer(states[order[oi]],oi,alpha);
    return;
  }""",
    """function drawBank(bankIndex,alpha){
  const states=bankState[bankIndex];if(!states.length)return;let mode=bankMode[bankIndex]??'single';
  if(mode==='pip')mode='flow';
  const order=states.map((_,i)=>(i+focusLayer)%states.length);
  // A live preview that is already missing its frame budget should stop paying
  // for secondary full-frame video draws. The timeline/compositor state remains
  // intact and secondary layers return automatically once the EMA recovers.
  if(responsivePreview&&previewFrameEma>30){
    drawLayer(fx,states[order[0]],{x:0,y:0,w:width,h:height},alpha,'source-over');
    return;
  }

  if(mode==='flow'&&states.length>1){
    const flowOrder=responsivePreview?order.slice(0,2):order;
    drawLayer(fx,states[flowOrder[0]],{x:0,y:0,w:width,h:height},alpha,'source-over');
    for(let oi=1;oi<flowOrder.length;oi++)drawFlowLayer(states[flowOrder[oi]],oi,alpha);
    return;
  }""",
)

replace_once(
    vis,
    """  if(mode==='mosaic'&&states.length>1){
    const cols=3,rows=2,cw=width/cols,ch=height/rows,shift=Math.floor(phase*.22);
    for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){
      const cell=row*cols+col,idx=order[(cell+shift)%order.length]; if(cell%3===0)continue;
      fx.save();fx.beginPath();fx.rect(col*cw,row*ch,cw+.5,ch+.5);fx.clip();drawLayer(fx,states[idx],{x:0,y:0,w:width,h:height},alpha*.86,states[idx].layer.blend_mode||'source-over');fx.restore();
    }return;
  }""",
    """  if(mode==='mosaic'&&states.length>1){
    const cols=responsivePreview?2:3,rows=2,cw=width/cols,ch=height/rows,shift=Math.floor(phase*.22);
    for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){
      const cell=row*cols+col,idx=order[(cell+shift)%order.length];
      if((responsivePreview&&cell===0)||(!responsivePreview&&cell%3===0))continue;
      fx.save();fx.beginPath();fx.rect(col*cw,row*ch,cw+.5,ch+.5);fx.clip();drawLayer(fx,states[idx],{x:0,y:0,w:width,h:height},alpha*.86,states[idx].layer.blend_mode||'source-over');fx.restore();
    }return;
  }""",
)

replace_once(
    vis,
    """  if(mode==='strips'&&states.length>1){
    const strips=10;""",
    """  if(mode==='strips'&&states.length>1){
    const strips=responsivePreview?6:10;""",
)

replace_once(
    vis,
    """  for(let oi=0;oi<order.length;oi++){
    const idx=order[oi],state=states[idx];""",
    """  const drawOrder=responsivePreview?order.slice(0,2):order;
  for(let oi=0;oi<drawOrder.length;oi++){
    const idx=drawOrder[oi],state=states[idx];""",
)

replace_once(
    vis,
    """  // Onset fragments are now fluid refraction droplets. They never draw a
  // rectangular video patch, which eliminates the intermittent square overlays.
  let fragmentDrawn=0;
  for(let i=fragments.length-1;i>=0;i--){""",
    """  // Responsive preview samples the pre-WebGPU 2D composition for overlays.
  // Pulling the WebGPU swapchain back into Canvas2D can serialize GPU/CPU work.
  const overlaySource=responsivePreview?videoFx:finalVideoCanvas();
  const fragmentBudget=responsivePreview?(previewFrameEma>30?0:(previewFrameEma>22?1:2)):Number.POSITIVE_INFINITY;
  const motifBudget=responsivePreview?(previewFrameEma>26?0:1):Number.POSITIVE_INFINITY;
  // Onset fragments are now fluid refraction droplets. They never draw a
  // rectangular video patch, which eliminates the intermittent square overlays.
  let fragmentDrawn=0;
  for(let i=fragments.length-1;i>=0;i--){""",
)

replace_once(vis, "if(responsivePreview&&fragmentDrawn>=3)continue;", "if(fragmentDrawn>=fragmentBudget)continue;")
replace_once(vis, "ctx.drawImage(finalVideoCanvas(),f.vx*55,f.vy*55,width,height);", "ctx.drawImage(overlaySource,f.vx*55,f.vy*55,width,height);")
replace_once(vis, "if(responsivePreview&&motifDrawn>=2){mi++;continue;}", "if(motifDrawn>=motifBudget){mi++;continue;}")
replace_once(vis, "ctx.drawImage(finalVideoCanvas(),0,0,width,height);", "ctx.drawImage(overlaySource,0,0,width,height);")

# Extend the existing 0.40.2 release notes and regression checks.
changelog = Path("CHANGELOG.md")
text = changelog.read_text()
needle = "- Bound live overlay refractions to three onset fragments and two motif refractions per displayed frame while still updating the complete logical overlay state.\n"
replacement = "- Bound live overlay refractions adaptively and source them from the pre-WebGPU composition to avoid synchronizing the GPU swapchain back into Canvas2D; overlay copies disappear entirely while the preview is over budget.\n- Degrade expensive multi-source compositions gracefully under load: responsive flow/default compositions cap companion layers, mosaic/strip grammars use cheaper live approximations, and an overloaded preview temporarily displays the primary layer only. Full/offline rendering retains the exact composition graph.\n"
if needle not in text:
    raise RuntimeError("0.40.2 overlay changelog bullet not found")
changelog.write_text(text.replace(needle, replacement, 1))

test = "tests/test_render_optimization.py"
replace_once(
    test,
    """    assert "fragmentDrawn>=3" in js
    assert "motifDrawn>=2" in js
""",
    """    assert "fragmentBudget=responsivePreview" in js
    assert "motifBudget=responsivePreview" in js
    assert "overlaySource=responsivePreview?videoFx:finalVideoCanvas()" in js
    assert "previewFrameEma>30" in js
    assert "flowOrder=responsivePreview?order.slice(0,2):order" in js
    assert "const strips=responsivePreview?6:10" in js
""",
)
