from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


visualizer = "src/tubeviz/static/visualizer.js"
replace_once(
    visualizer,
    '''function applyRipple(amount){
  if(amount<=.025)return;snapshot();const slices=Math.max(12,Math.min(64,18+Math.floor(amount*55))),sh=height/slices,amp=width*(.004+.035*amount);
  fx.save();fx.globalAlpha=.32+.45*amount;
  for(let i=0;i<slices;i++){const y=i*sh,dx=Math.sin(i*.72+phase*13)*amp*(.35+.65*Math.sin(phase*3+i*.11)**2);fx.drawImage(scratch,0,y,width,sh+1,dx,y,width,sh+1);}
  fx.restore();
}''',
    '''function applyRipple(amount){
  if(amount<=.025)return;
  snapshot();
  const {x:cx,y:cy}=creativeTarget(),maxR=Math.hypot(Math.max(cx,width-cx),Math.max(cy,height-cy));
  const rings=12+Math.floor(amount*10),step=maxR/rings,time=clockSeconds();
  fx.save();fx.globalCompositeOperation='source-over';fx.globalAlpha=.16+.34*amount;
  for(let i=rings-1;i>=0;i--){
    const r0=i*step,r1=(i+1)*step,mid=(r0+r1)*.5,n=mid/Math.max(1,maxR);
    const wave=Math.sin(n*34-time*4.6)*amount*.012*(1-Math.min(1,n));
    if(Math.abs(wave)<.0002)continue;
    fx.save();fx.beginPath();fx.arc(cx,cy,r1,0,Math.PI*2);fx.arc(cx,cy,r0,0,Math.PI*2,true);fx.clip('evenodd');
    const scale=1+wave;fx.translate(cx,cy);fx.scale(scale,scale);fx.translate(-cx,-cy);fx.drawImage(scratch,0,0,width,height);fx.restore();
  }
  fx.restore();
}''',
)
replace_once(
    visualizer,
    '''function applyVortex(amount){
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
}''',
    '''function applyVortex(amount){
  if(amount<=.03)return;
  snapshot();
  const {x:cx,y:cy}=creativeTarget(),maxR=Math.hypot(Math.max(cx,width-cx),Math.max(cy,height-cy));
  const rings=10+Math.floor(amount*8),step=maxR/rings;
  fx.save();fx.globalCompositeOperation='source-over';fx.globalAlpha=.14+.30*amount;
  for(let i=rings-1;i>=0;i--){
    const r0=i*step,r1=(i+1)*step,mid=(r0+r1)*.5,n=mid/Math.max(1,maxR),falloff=1-Math.min(1,n);
    const angle=amount*.24*falloff;if(Math.abs(angle)<.001)continue;
    fx.save();fx.beginPath();fx.arc(cx,cy,r1,0,Math.PI*2);fx.arc(cx,cy,r0,0,Math.PI*2,true);fx.clip('evenodd');
    fx.translate(cx,cy);fx.rotate(angle);fx.translate(-cx,-cy);fx.drawImage(scratch,0,0,width,height);fx.restore();
  }
  fx.restore();
}''',
)
replace_once(
    visualizer,
    "import {createBrowserGpuFinalizer} from '/static/browser_gpu.js?v=0.44.0-previewfix1';",
    "import {createBrowserGpuFinalizer} from '/static/browser_gpu.js?v=0.44.0-previewfix3';",
)

transforms = "src/tubeviz/transforms.py"
for old, new in {
    'ripple = accent("ripple", ripple, .34, .09, retain=.18)': 'ripple = accent("ripple", ripple, .24, .09)',
    'slit_scan = accent("slit scan", slit_scan, .26, .09)': 'slit_scan = accent("slit scan", slit_scan, .18, .09)',
    'frame_echo = accent("frame echo", frame_echo, .32, .10, aliases=("temporal echo",), retain=.10)': 'frame_echo = accent("frame echo", frame_echo, .26, .10, aliases=("temporal echo",), retain=.05)',
    'datamosh = accent("datamosh-like block displacement", datamosh, .24, .10, aliases=("datamosh",))': 'datamosh = accent("datamosh-like block displacement", datamosh, .16, .10, aliases=("datamosh",))',
    'chroma_delay = accent("chroma delay", chroma_delay, .28, .08, aliases=("temporal rgb displacement",), retain=.08)': 'chroma_delay = accent("chroma delay", chroma_delay, .24, .08, aliases=("temporal rgb displacement",), retain=.04)',
    'motion_trails = accent("motion trails", motion_trails, .32, .10, retain=.12)': 'motion_trails = accent("motion trails", motion_trails, .26, .10, retain=.05)',
    '_density_gate(vortex_gate, .22, event_density, preferred="vortex" in preferred)': '_density_gate(vortex_gate, .12, event_density, preferred="vortex" in preferred)',
}.items():
    replace_once(transforms, old, new)

editing = "src/tubeviz/editing.py"
replace_once(
    editing,
    '''                if accent > 0.46 or beat_ord % 2 == 1:
                    add_effect(
                        event.time,
                        "video_edit_ripple",
                        {"amount": min(0.68, intensity * (0.08 + low * 0.38 + accent * 0.10))},
                        cooldown=max(0.34, beat_seconds * 0.72),
                    )''',
    '''                if beat_ord % 2 == 1 or (accent > 0.82 and beat_ord % 4 == 0):
                    add_effect(
                        event.time,
                        "video_edit_ripple",
                        {"amount": min(0.68, intensity * (0.08 + low * 0.38 + accent * 0.10))},
                        cooldown=max(0.48, beat_seconds * 1.25),
                    )''',
)

replace_once(
    "src/tubeviz/static/index.html",
    '<script type="module" src="/static/visualizer.js?v=0.44.0-timeline1"></script>',
    '<script type="module" src="/static/visualizer.js?v=0.44.0-effects1"></script>',
)

test = Path("tests/test_effect_alignment.py")
text = test.read_text()
text += '''


def test_resident_native_gpu_uses_post_composite_radial_spatial_grammar():
    source = Path("src/tubeviz/native_src/src/resident_gpu.cpp").read_text()
    assert "float ring=sin(rr*34.0-phase*4.6)" in source
    assert "float va=vortex*.24*(1.0-smoothstep(.04,.95,vr))" in source
    assert 'set_param(impl_->layer_hook, "ripple", 0.0f)' in source
    assert 'set_param(impl_->layer_hook, "vortex", 0.0f)' in source
    assert 'set_param(impl_->final_hook, "beat_variant"' in source
    assert 'set_param(impl_->final_hook, "beat_phase"' in source
    assert 'set_param(impl_->final_hook, "beat_polarity"' in source
    assert "float wave=flow*.010+ripple*.008" not in source


def test_canvas_fallback_uses_radial_source_over_geometry():
    source = Path("src/tubeviz/static/visualizer.js").read_text()
    ripple = source.split("function applyRipple(amount){", 1)[1].split("function applyTiles", 1)[0]
    vortex = source.split("function applyVortex(amount){", 1)[1].split("function applyMotionTrails", 1)[0]
    assert "fx.clip('evenodd')" in ripple
    assert "globalCompositeOperation='source-over'" in ripple
    assert "n*34-time*4.6" in ripple
    assert "fx.clip('evenodd')" in vortex
    assert "globalCompositeOperation='source-over'" in vortex
    assert "amount*.24*falloff" in vortex


def test_persistent_heavy_effect_defaults_are_sparse():
    source = Path("src/tubeviz/transforms.py").read_text()
    assert 'ripple = accent("ripple", ripple, .24, .09)' in source
    assert 'slit_scan = accent("slit scan", slit_scan, .18, .09)' in source
    assert 'datamosh = accent("datamosh-like block displacement", datamosh, .16, .10' in source
    assert '_density_gate(vortex_gate, .12, event_density' in source
'''
test.write_text(text)
