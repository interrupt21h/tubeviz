// SPDX-License-Identifier: Apache-2.0
// Shared WebGPU compositor used from either the main thread or a dedicated worker.

export const TUBEVIZ_GPU_SHADER = /* wgsl */`
struct Params {
  p0: vec4f, // fidelity, vignette, scanlines, strobe
  p1: vec4f, // time, width, height, warp
  p2: vec4f, // chroma, depth, bloom, palette strength
  p3: vec4f, // palette rgb, feedback
  p4: vec4f, // temporal, flow, target x/y
  p5: vec4f, // hue radians, saturation, contrast, brightness
  p6: vec4f, // streaks, background warp, flow rgb, temporal rgb
  p7: vec4f, // pixel, posterize, solarize, edge
  p8: vec4f, // glitch, block displacement, tracking, ripple
  p9: vec4f, // tempo warp, slit scan, datamosh, motion trails
  p10: vec4f, // frame echo, reserved, reserved, reserved
  p11: vec4f, // beat amount, low, mid, high
  p12: vec4f, // beat center x/y, direction, frequency
  p13: vec4f, // beat mode, local phase, polarity, variant
};
@group(0) @binding(0) var samp: sampler;
@group(0) @binding(1) var effectTex: texture_2d<f32>;
@group(0) @binding(2) var sourceTex: texture_2d<f32>;
@group(0) @binding(3) var historyTex: texture_2d<f32>;
@group(0) @binding(4) var<uniform> params: Params;

struct VSOut {@builtin(position) pos: vec4f,@location(0) uv: vec2f};
@vertex fn vs_main(@builtin(vertex_index) i:u32)->VSOut{
  var p=array<vec2f,3>(vec2f(-1,-1),vec2f(3,-1),vec2f(-1,3));
  var u=array<vec2f,3>(vec2f(0,1),vec2f(2,1),vec2f(0,-1));
  var o:VSOut;o.pos=vec4f(p[i],0,1);o.uv=u[i];return o;
}
fn satUv(uv:vec2f)->vec2f{return clamp(uv,vec2f(0),vec2f(1));}
fn luma(c:vec3f)->f32{return dot(c,vec3f(.2126,.7152,.0722));}
fn hueRotate(c:vec3f,a:f32)->vec3f{
  let y=dot(c,vec3f(.299,.587,.114));
  let ii=dot(c,vec3f(.596,-.274,-.322));
  let q=dot(c,vec3f(.211,-.523,.312));
  let ca=cos(a);let sa=sin(a);let ni=ii*ca-q*sa;let nq=ii*sa+q*ca;
  return vec3f(y+.956*ni+.621*nq,y-.272*ni-.647*nq,y-1.106*ni+1.703*nq);
}
fn radialRippleUv(uv0:vec2f,center0:vec2f,amount0:f32,time:f32)->vec2f{
  let amount=clamp(amount0,0.0,1.0);
  if(amount<=.001){return uv0;}
  let center=clamp(center0,vec2f(.08),vec2f(.92));
  let aspect=max(.35,params.p1.y/max(1.0,params.p1.z));
  var p=uv0-center;p.x*=aspect;
  let r=length(p);let radialDir=p/max(r,.0001);
  let ring=sin(r*34.0-time*4.6);
  let falloff=1.0-smoothstep(.03,1.05,r);
  // Radial UV displacement bends the existing image only. It does not draw
  // dark rings or add/multiply color, so a bass hit reads as a pressure wave.
  p+=radialDir*ring*amount*.0105*falloff;
  p.x/=aspect;
  return satUv(center+p);
}
fn beatWarpUv(uv0:vec2f)->vec2f{
  let amount=clamp(params.p11.x,0.0,1.0);
  if(amount<=.001){return uv0;}
  let center=clamp(params.p12.xy,vec2f(.08),vec2f(.92));
  let direction=params.p12.z;let frequency=max(.5,params.p12.w);
  let mode=params.p13.x;let localPhase=clamp(params.p13.y,0.0,1.0);
  let polarity=select(-1.0,1.0,params.p13.z>=0.0);let variant=params.p13.w;
  let low=clamp(params.p11.y,0.0,1.0);let mid=clamp(params.p11.z,0.0,1.0);let high=clamp(params.p11.w,0.0,1.0);
  var p=uv0-center;var out=uv0;let r=length(p);
  let dir=vec2f(cos(direction),sin(direction));let normal=vec2f(-dir.y,dir.x);
  let spectral=.72+.20*low+.13*mid+.08*high;let a=amount*spectral;
  if(mode<.5){
    out-=p*a*.070*polarity*(.72+.28*(1.0-smoothstep(.15,.82,r)));
  }else if(mode<1.5){
    out+=p*a*.060*polarity*(.72+.28*(1.0-smoothstep(.12,.86,r)));
  }else if(mode<2.5){
    let osc=sin(dot(p,normal)*28.0*frequency+localPhase*10.0+variant*.57);
    out+=dir*osc*a*.035*polarity*(.65+.35*mid);
  }else if(mode<3.5){
    let angle=a*.20*polarity*(1.0-smoothstep(.10,.78,r))*(.65+.35*sin(localPhase*3.14159265));
    let cs=cos(angle);let sn=sin(angle);out=center+mat2x2f(cs,-sn,sn,cs)*p;
  }else if(mode<4.5){
    let osc=sin(dot(p,normal)*24.0*frequency+localPhase*12.0+variant*.83);
    out+=dir*osc*a*.027*polarity;
    out+=normal*cos(dot(p,dir)*17.0*frequency-localPhase*8.0)*a*.011;
  }else if(mode<5.5){
    let saddle=vec2f(p.x*p.y,(p.x*p.x-p.y*p.y)*.58);
    out+=saddle*a*.34*polarity;
  }else if(mode<6.5){
    let lens=(1.0-smoothstep(.04,.72,r));
    out-=p*a*.095*polarity*lens;
  }else{
    var angle=a*.24*polarity*(1.0-smoothstep(.05,.88,r));
    angle+=sin(r*34.0*frequency-localPhase*11.0+variant)*a*.035;
    let cs=cos(angle);let sn=sin(angle);out=center+mat2x2f(cs,-sn,sn,cs)*p;
  }
  return satUv(out);
}
@fragment fn fs_main(in:VSOut)->@location(0) vec4f{
  var uv=satUv(in.uv);let time=params.p1.x;
  let focalTarget=params.p4.zw;let flow=params.p4.y;let warp=params.p1.w;
  let dims=vec2f(max(1.0,params.p1.y),max(1.0,params.p1.z));
  let px=1.0/dims;
  // Pixelation, tracking, glitch and block displacement happen in UV space so
  // they cost one fused GPU pass rather than multiple full-frame Canvas2D copies.
  if(params.p7.x>.001){
    let cell=max(1.0,mix(1.0,24.0,clamp(params.p7.x,0.0,1.0)));
    uv=(floor(uv*dims/cell)+vec2f(.5))*cell/dims;
  }
  if(params.p8.z>.001){
    let band=floor(uv.y*96.0);let drift=sin(band*1.73+time*7.1)*params.p8.z*.006;uv.x+=drift;
  }
  if(params.p8.x>.001){
    let row=floor(uv.y*36.0);let h=fract(sin(row*91.17+floor(time*18.0)*17.13)*43758.5453);
    let gate=step(1.0-clamp(params.p8.x,0.0,1.0)*.28,h);uv.x+=(h-.5)*gate*params.p8.x*.065;
  }
  if(params.p8.y>.001){
    let cell=floor(uv*vec2f(14.0,9.0));let h=fract(sin(dot(cell,vec2f(12.9898,78.233))+floor(time*11.0))*43758.5453);
    let gate=step(1.0-clamp(params.p8.y,0.0,1.0)*.22,h);uv+=vec2f(h-.5,.5-h)*gate*params.p8.y*.035;
  }
  // Continuous scene flow remains separate from beat-local topology. Ripple is
  // radial around the semantic/creative target; it is no longer a pair of
  // perpendicular sine fields that visually collapsed into a dark swirl.
  uv=beatWarpUv(uv);
  uv=radialRippleUv(uv,focalTarget,params.p8.w,time);
  let wave=vec2f(sin(uv.y*13.0+time*1.7),cos(uv.x*11.0-time*1.3));
  let tempo=vec2f(sin((uv.y+time*.08)*18.0),cos((uv.x-time*.06)*16.0))*params.p9.x*.0035;
  // visualizer.js historically folded ripple*0.42 into generic warp. Remove that
  // known contribution here so the new radial displacement is not applied twice.
  let continuousWarp=max(0.0,warp-params.p8.w*.42);
  uv=satUv(uv+wave*(continuousWarp*.010+flow*.006)+tempo);
  if(params.p2.y>.001){
    let src0=textureSample(sourceTex,samp,uv).rgb;let z=(luma(src0)-.5)*params.p2.y*.030;
    uv=satUv(uv+(uv-focalTarget)*z);
  }
  if(params.p6.y>.001){
    let srcBg=textureSample(sourceTex,samp,uv).rgb;let bg=1.0-smoothstep(.34,.72,luma(srcBg));
    uv=satUv(uv+wave*params.p6.y*.008*bg);
  }
  var c=textureSample(effectTex,samp,uv).rgb;
  let chroma=max(params.p2.x,params.p6.z);
  if(chroma>.001){
    let d=vec2f((.0015+.008*chroma)*sin(time*2.1),(.001+.004*chroma)*cos(time*1.7));
    let cr=textureSample(effectTex,samp,satUv(uv+d)).r;
    let cb=textureSample(effectTex,samp,satUv(uv-d)).b;
    c=vec3f(cr,c.g,cb);
  }
  let historyAmount=clamp(params.p3.w+params.p4.x*.55+params.p6.w*.35+params.p9.w*.28+params.p10.x*.32,0.0,.82);
  if(historyAmount>.001){
    let hu=satUv((uv-.5)*(1.0-.006*historyAmount)+.5+vec2f(.0015,-.001)*historyAmount);
    let h=textureSample(historyTex,samp,hu).rgb;c=mix(c,h,historyAmount*.34);
  }
  if(params.p9.y>.001){
    let stripe=floor(uv.y*mix(18.0,54.0,params.p9.y));
    let shift=sin(stripe*.71+time*4.7)*params.p9.y*.025;
    let h=textureSample(historyTex,samp,satUv(uv+vec2f(shift,0))).rgb;
    let gate=.35+.65*step(.5,fract(stripe*.618));c=mix(c,h,params.p9.y*.24*gate);
  }
  if(params.p9.z>.001){
    let cell=floor(uv*vec2f(12.0,8.0));let hsh=fract(sin(dot(cell,vec2f(41.31,17.17))+floor(time*8.0))*951.1357);
    let gate=step(1.0-params.p9.z*.30,hsh);let duv=vec2f(hsh-.5,.5-hsh)*params.p9.z*.050;
    let old=textureSample(historyTex,samp,satUv(uv+duv)).rgb;c=mix(c,max(c,old),gate*params.p9.z*.36);
  }
  let bloom=params.p2.z;
  if(bloom>.001){
    let b=(textureSample(effectTex,samp,satUv(uv+vec2f(px.x*3,0))).rgb+
           textureSample(effectTex,samp,satUv(uv-vec2f(px.x*3,0))).rgb+
           textureSample(effectTex,samp,satUv(uv+vec2f(0,px.y*3))).rgb+
           textureSample(effectTex,samp,satUv(uv-vec2f(0,px.y*3))).rgb)*.25;
    c+=max(b-vec3f(.55),vec3f(0))*bloom*.45;
  }
  if(params.p6.x>.001){
    let streak=textureSample(effectTex,samp,satUv(uv+vec2f(sin(uv.y*31+time)*.012*params.p6.x,0))).rgb;
    c=mix(c,max(c,streak),params.p6.x*.14);
  }
  // Bounded directed color. Most shots pass neutral values.
  c=hueRotate(c,params.p5.x);
  let y=luma(c);c=mix(vec3f(y),c,max(0.0,params.p5.y));
  c=(c-vec3f(.5))*params.p5.z+vec3f(.5);c*=params.p5.w;
  if(params.p2.w>.001){
    let pal=params.p3.xyz;let py=luma(pal);let tinted=clamp(c+(pal-vec3f(py))*.22,vec3f(0),vec3f(1));
    c=mix(c,tinted,params.p2.w*.32);
  }
  if(params.p7.y>.001){
    let levels=max(2.0,mix(16.0,3.0,clamp(params.p7.y,0.0,1.0)));
    let q=floor(c*levels+.5)/levels;c=mix(c,q,clamp(params.p7.y,0.0,1.0));
  }
  if(params.p7.z>.001){
    let gate=smoothstep(.42,.62,luma(c));let solar=mix(c,vec3f(1.0)-c,gate);
    c=mix(c,solar,clamp(params.p7.z,0.0,1.0));
  }
  if(params.p7.w>.001){
    let lx=abs(luma(textureSample(effectTex,samp,satUv(uv+vec2f(px.x*2.0,0))).rgb)-luma(textureSample(effectTex,samp,satUv(uv-vec2f(px.x*2.0,0))).rgb));
    let ly=abs(luma(textureSample(effectTex,samp,satUv(uv+vec2f(0,px.y*2.0))).rgb)-luma(textureSample(effectTex,samp,satUv(uv-vec2f(0,px.y*2.0))).rgb));
    let e=clamp((lx+ly)*3.2,0.0,1.0);c=mix(c,max(c,vec3f(e)),clamp(params.p7.w,0.0,1.0)*e*.62);
  }
  // Final source-chroma contract: retain effected luminance, pull chroma back
  // toward the composed footage after every destructive GPU operation.
  let source=textureSample(sourceTex,samp,uv).rgb;let ey=luma(c);let sy=luma(source);
  let anchored=clamp(source+vec3f(ey-sy),vec3f(0),vec3f(1));
  c=mix(c,anchored,clamp(params.p0.x,0.0,.97));
  if(params.p0.y>.001){let d=distance(in.uv,vec2f(.5));c*=1.0-smoothstep(.30,.74,d)*params.p0.y*.52;}
  if(params.p0.z>.001){let line=.5+.5*sin(in.uv.y*params.p1.z*3.14159265);c*=1.0-line*params.p0.z*.10;}
  if(params.p0.w>.001){let pulse=.5+.5*sin(time*48.0);c=mix(c,vec3f(1),pulse*params.p0.w*.16);}
  return vec4f(clamp(c,vec3f(0),vec3f(1)),1);
}`;


export const TUBEVIZ_GPU_LAYER_SHADER = /* wgsl */`
struct LayerUniforms {
  g0: vec4f, // mode, time, progress, count
  g1: vec4f, // transition mix, target aspect, focus layer, reserved
  l0a: vec4f, l0b: vec4f, l0c: vec4f, l0d: vec4f,
  l1a: vec4f, l1b: vec4f, l1c: vec4f, l1d: vec4f,
  l2a: vec4f, l2b: vec4f, l2c: vec4f, l2d: vec4f,
  l3a: vec4f, l3b: vec4f, l3c: vec4f, l3d: vec4f,
  g2: vec4f, // semantic target x/y, subject radius, subject preserve
};
@group(0) @binding(0) var video0: texture_external;
@group(0) @binding(1) var video1: texture_external;
@group(0) @binding(2) var video2: texture_external;
@group(0) @binding(3) var video3: texture_external;
@group(0) @binding(4) var layerSampler: sampler;
@group(0) @binding(5) var<uniform> layers: LayerUniforms;

struct LayerVSOut {@builtin(position) pos: vec4f,@location(0) uv: vec2f};
@vertex fn layer_vs(@builtin(vertex_index) i:u32)->LayerVSOut{
  var p=array<vec2f,3>(vec2f(-1,-1),vec2f(3,-1),vec2f(-1,3));
  var u=array<vec2f,3>(vec2f(0,1),vec2f(2,1),vec2f(0,-1));
  var o:LayerVSOut;o.pos=vec4f(p[i],0,1);o.uv=u[i];return o;
}
fn layerSatUv(uv:vec2f)->vec2f{return clamp(uv,vec2f(0),vec2f(1));}
fn layerLuma(c:vec3f)->f32{return dot(c,vec3f(.2126,.7152,.0722));}
fn layerHueRotate(c:vec3f,a:f32)->vec3f{
  let y=dot(c,vec3f(.299,.587,.114));let ii=dot(c,vec3f(.596,-.274,-.322));let q=dot(c,vec3f(.211,-.523,.312));
  let ca=cos(a);let sa=sin(a);let ni=ii*ca-q*sa;let nq=ii*sa+q*ca;
  return vec3f(y+.956*ni+.621*nq,y-.272*ni-.647*nq,y-1.106*ni+1.703*nq);
}
fn layerUv(uv0:vec2f,b:vec4f,c:vec4f,d:vec4f)->vec2f{
  var uv=uv0-.5;let sourceAspect=max(.01,d.x);let targetAspect=max(.01,layers.g1.y);
  var aspectScale=vec2f(1.0);
  if(sourceAspect>targetAspect){aspectScale.x=targetAspect/sourceAspect;}else{aspectScale.y=sourceAspect/targetAspect;}
  let zoom=max(.35,b.y);uv*=aspectScale/zoom;
  if(c.y>.5){uv.x=-uv.x;}
  let cs=cos(-c.x);let sn=sin(-c.x);uv=mat2x2f(cs,-sn,sn,cs)*uv;
  uv-=b.zw;return layerSatUv(uv+.5);
}
fn layerGrade(c0:vec4f,a:vec4f,b:vec4f)->vec4f{
  var c=layerHueRotate(c0.rgb,b.x);let y=layerLuma(c);c=mix(vec3f(y),c,max(0.0,a.w));
  c=(c-vec3f(.5))*a.z+vec3f(.5);c*=a.y;return vec4f(clamp(c,vec3f(0),vec3f(1)),clamp(a.x,0.0,1.0));
}
fn sample0(uv:vec2f)->vec4f{return layerGrade(textureSampleBaseClampToEdge(video0,layerSampler,layerUv(uv,layers.l0b,layers.l0c,layers.l0d)),layers.l0a,layers.l0b);}
fn sample1(uv:vec2f)->vec4f{return layerGrade(textureSampleBaseClampToEdge(video1,layerSampler,layerUv(uv,layers.l1b,layers.l1c,layers.l1d)),layers.l1a,layers.l1b);}
fn sample2(uv:vec2f)->vec4f{return layerGrade(textureSampleBaseClampToEdge(video2,layerSampler,layerUv(uv,layers.l2b,layers.l2c,layers.l2d)),layers.l2a,layers.l2b);}
fn sample3(uv:vec2f)->vec4f{return layerGrade(textureSampleBaseClampToEdge(video3,layerSampler,layerUv(uv,layers.l3b,layers.l3c,layers.l3d)),layers.l3a,layers.l3b);}
fn sampleLayer(i:i32,uv:vec2f)->vec4f{if(i==1){return sample1(uv);}if(i==2){return sample2(uv);}if(i==3){return sample3(uv);}return sample0(uv);}
fn layerBlend(base:vec3f,over:vec3f,alpha:f32,mode:f32)->vec3f{
  var mixed=over;
  if(mode>.5&&mode<1.5){mixed=1.0-(1.0-base)*(1.0-over);}
  else if(mode>=1.5&&mode<2.5){mixed=base*over;}
  else if(mode>=2.5&&mode<3.5){mixed=select(2.0*base*over,1.0-2.0*(1.0-base)*(1.0-over),base>vec3f(.5));}
  else if(mode>=3.5){mixed=max(base,over);}
  return mix(base,mixed,clamp(alpha,0.0,1.0));
}
fn addLayer(base:vec3f,s:vec4f,mode:f32)->vec3f{return layerBlend(base,s.rgb,s.a,mode);}
fn blendMode(i:i32)->f32{if(i==1){return layers.l1c.z;}if(i==2){return layers.l2c.z;}if(i==3){return layers.l3c.z;}return layers.l0c.z;}
fn organicFlowMask(uv:vec2f,fi:f32,time:f32)->f32{
  let target=clamp(layers.g2.xy,vec2f(.08),vec2f(.92));
  let subjectRadius=clamp(layers.g2.z,.12,.44);let preserve=clamp(layers.g2.w,0.0,1.0);
  let orbit=vec2f(.15+.025*fi,.13+.018*fi)*(1.0-.42*preserve);
  let center=clamp(target+vec2f(sin(time*.40+fi*1.71),cos(time*.34-fi*1.19))*orbit,vec2f(.06),vec2f(.94));
  let radii=vec2f(.24+.030*fi,.27+.026*fi);let p=(uv-center)/radii;
  let angle=atan2(p.y,p.x);let r=length(p);
  // Multi-lobed, breathing boundary: the GPU path now follows the same organic
  // grammar as the Canvas fallback rather than reducing flow to a soft ellipse.
  let boundary=.90+.14*sin(angle*3.0+time*.37+fi)+.09*sin(angle*5.0-time*.29+fi*1.7)+.055*sin(angle*2.0+time*.61);
  var mask=1.0-smoothstep(boundary*.80,boundary*1.10,r);
  let subjectP=(uv-target)/vec2(subjectRadius,subjectRadius*1.18);
  let subject=1.0-smoothstep(.72,1.14,length(subjectP));
  mask*=1.0-subject*preserve*.80;
  return clamp(mask,0.0,1.0);
}
@fragment fn layer_fs(in:LayerVSOut)->@location(0) vec4f{
  let uv=layerSatUv(in.uv);let mode=i32(round(layers.g0.x));let time=layers.g0.y;let progress=clamp(layers.g0.z,0.0,1.0);let count=max(1,i32(round(layers.g0.w)));
  if(mode==7&&count>1){let a=sample0(uv);let b=sample1(uv);return vec4f(mix(a.rgb,b.rgb,clamp(layers.g1.x,0.0,1.0)),1);}
  if(mode==3&&count>1){
    let cell=floor(uv*vec2f(3,2));let shift=i32(floor(time*.22));let idx=(i32(cell.x)+i32(cell.y)*3+shift)%count;let s=sampleLayer(idx,uv);return vec4f(s.rgb,1);
  }
  if(mode==4&&count>1){let idx=i32(floor(progress*4.0+time*.06))%count;let s=sampleLayer(idx,uv);return vec4f(s.rgb,1);}
  if(mode==5&&count>1){let idx=(i32(floor(uv.x*10.0))+i32(round(layers.g1.z)))%count;let s=sampleLayer(idx,uv);return vec4f(s.rgb,1);}
  var base=sample0(uv).rgb;
  if(mode==2&&count>1){let boundary=.18+.64*progress+sin(time*.45)*.08+(uv.y-.5)*.22;let s=sample1(uv);base=layerBlend(base,s.rgb,s.a*select(0.0,1.0,uv.x<boundary),blendMode(1));return vec4f(base,1);}
  if(mode==1&&count>1){
    for(var i=1;i<4;i++){
      if(i>=count){break;}let fi=f32(i);let mask=organicFlowMask(uv,fi,time);
      let s=sampleLayer(i,uv);base=layerBlend(base,s.rgb,s.a*mask*(.58+.12*sin(time+fi)),blendMode(i));
    }
    return vec4f(base,1);
  }
  if(mode==6&&count>1){
    for(var i=1;i<4;i++){if(i>=count){break;}let s=sampleLayer(i,uv);let gate=clamp(.18+.66*layerLuma(s.rgb),0.0,1.0);base=layerBlend(base,s.rgb,s.a*gate,blendMode(i));}
    return vec4f(base,1);
  }
  for(var i=1;i<4;i++){if(i>=count){break;}let s=sampleLayer(i,uv);base=addLayer(base,s,blendMode(i));}
  return vec4f(base,1);
}`;

function gpuParams(params,width,height){
  const palette=params.palette??[0,0,0];
  return new Float32Array([
    Number(params.fidelity||0),Number(params.vignette||0),Number(params.scanlines||0),Number(params.strobe||0),
    Number(params.time||0),width,height,Number(params.warp||0),
    Number(params.chroma||0),Number(params.depth||0),Number(params.bloom||0),Number(params.paletteStrength||0),
    Number(palette[0]||0),Number(palette[1]||0),Number(palette[2]||0),Number(params.feedback||0),
    Number(params.temporal||0),Number(params.flow||0),Number(params.targetX??.5),Number(params.targetY??.5),
    Number(params.hueRadians||0),Number(params.saturation??1),Number(params.contrast??1),Number(params.brightness??1),
    Number(params.streaks||0),Number(params.backgroundWarp||0),Number(params.flowRgb||0),Number(params.temporalRgb||0),
    Number(params.pixel||0),Number(params.posterize||0),Number(params.solarize||0),Number(params.edge||0),
    Number(params.glitch||0),Number(params.blockDisplace||0),Number(params.tracking||0),Number(params.ripple||0),
    Number(params.tempoWarp||0),Number(params.slitScan||0),Number(params.datamosh||0),Number(params.motionTrails||0),
    Number(params.frameEcho||0),0,0,0,
    Number(params.beatAmount||0),Number(params.beatLow||0),Number(params.beatMid||0),Number(params.beatHigh||0),
    Number(params.beatCenterX??.5),Number(params.beatCenterY??.5),Number(params.beatDirection||0),Number(params.beatFrequency||1),
    Number(params.beatMode??4),Number(params.beatPhase||0),Number(params.beatPolarity??1),Number(params.beatVariant||0),
  ]);
}


function layerBlendMode(value){
  const mode=String(value||'normal').toLowerCase();
  return mode==='screen'?1:mode==='multiply'?2:mode==='overlay'?3:mode==='lighten'?4:0;
}
function layerUniforms(layerList,composition,width,height){
  const out=new Float32Array(76);const count=Math.max(1,Math.min(4,Number(composition.count??layerList.length)));
  out.set([Number(composition.mode??0),Number(composition.time??0),Number(composition.progress??0),count,Number(composition.transition??0),width/Math.max(1,height),Number(composition.focus??0),0],0);
  const first=layerList[0]||{};
  for(let i=0;i<4;i++){
    const item=layerList[i]||first,source=item.source;const base=8+i*16;
    const sw=Number(item.sourceWidth||source?.displayWidth||source?.codedWidth||source?.videoWidth||source?.width||width);
    const sh=Number(item.sourceHeight||source?.displayHeight||source?.codedHeight||source?.videoHeight||source?.height||height);
    out.set([Number(item.opacity??(i<count?1:0)),Number(item.brightness??1),Number(item.contrast??1),Number(item.saturation??1)],base);
    out.set([Number(item.hueRadians||0),Number(item.zoom??1),Number(item.panX||0),Number(item.panY||0)],base+4);
    out.set([Number(item.rotationRadians||0),item.mirror?1:0,layerBlendMode(item.blendMode),i<count?1:0],base+8);
    out.set([sw/Math.max(1,sh),0,0,0],base+12);
  }
  out.set([Number(composition.targetX??.5),Number(composition.targetY??.5),Number(composition.subjectRadius??.28),Number(composition.subjectPreserve??0)],72);
  return out;
}

function externalTextureSourceUsable(source){
  if(!source)return false;
  if(typeof source.readyState==='number')return source.readyState>=2&&!source.seeking&&Number(source.videoWidth)>0&&Number(source.videoHeight)>0;
  const width=Number(source.displayWidth||source.codedWidth||source.width||0),height=Number(source.displayHeight||source.codedHeight||source.height||0);
  return width>0&&height>0;
}

export class BrowserGpuRendererCore{
  constructor(canvas,device,context,format,pipeline,layerPipeline){
    this.canvas=canvas;this.device=device;this.context=context;this.format=format;this.pipeline=pipeline;this.layerPipeline=layerPipeline;this.width=0;this.height=0;this.failed=false;this.failureReason='';this.historyReady=false;this.onDeviceLost=null;
    this.sampler=device.createSampler({magFilter:'linear',minFilter:'linear',addressModeU:'clamp-to-edge',addressModeV:'clamp-to-edge'});
    this.uniformBuffer=device.createBuffer({size:224,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
    this.layerUniformBuffer=device.createBuffer({size:304,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
    // Device loss is asynchronous. Surface it to the facade so live preview can
    // immediately restore the Canvas2D compositor instead of freezing on the last
    // successfully submitted GPU frame.
    device.lost.then(info=>{
      this.failed=true;this.failureReason=`WebGPU device lost: ${info?.message||info?.reason||'unknown reason'}`;
      console.warn(this.failureReason);try{this.onDeviceLost?.(this.failureReason);}catch(_){}
    }).catch(()=>{});
    device.addEventListener?.('uncapturederror',event=>{
      const detail=event?.error?.message||event?.error||'unknown validation error';
      this.failed=true;this.failureReason=`WebGPU uncaptured error: ${detail}`;
      console.warn(this.failureReason);
    });
  }
  resize(width,height){
    width=Math.max(1,Math.floor(width));height=Math.max(1,Math.floor(height));if(width===this.width&&height===this.height)return;
    this.width=width;this.height=height;this.canvas.width=width;this.canvas.height=height;
    for(const t of [this.effectTexture,this.sourceTexture,this.compositionTexture,this.historyTexture])t?.destroy();
    const srcUsage=GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT;
    this.effectTexture=this.device.createTexture({label:'tubeviz-effect-source',size:[width,height],format:'rgba8unorm',usage:srcUsage});
    this.sourceTexture=this.device.createTexture({label:'tubeviz-source-color',size:[width,height],format:'rgba8unorm',usage:srcUsage});
    this.compositionTexture=this.device.createTexture({label:'tubeviz-direct-composition',size:[width,height],format:'rgba8unorm',usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.RENDER_ATTACHMENT});
    this.historyTexture=this.device.createTexture({label:'tubeviz-history',size:[width,height],format:this.format,usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST});
    this.bindGroup=this.device.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[
      {binding:0,resource:this.sampler},{binding:1,resource:this.effectTexture.createView()},{binding:2,resource:this.sourceTexture.createView()},{binding:3,resource:this.historyTexture.createView()},{binding:4,resource:{buffer:this.uniformBuffer}},
    ]});
    this.compositionBindGroup=this.device.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[
      {binding:0,resource:this.sampler},{binding:1,resource:this.compositionTexture.createView()},{binding:2,resource:this.compositionTexture.createView()},{binding:3,resource:this.historyTexture.createView()},{binding:4,resource:{buffer:this.uniformBuffer}},
    ]});this.historyReady=false;
  }
  render(effectSource,sourceColorSource,params={}){
    if(this.failed)return false;
    try{
      this.resize(effectSource.displayWidth||effectSource.width||this.canvas.width,effectSource.displayHeight||effectSource.height||this.canvas.height);
      this.device.queue.copyExternalImageToTexture({source:effectSource},{texture:this.effectTexture},[this.width,this.height]);
      this.device.queue.copyExternalImageToTexture({source:sourceColorSource},{texture:this.sourceTexture},[this.width,this.height]);
      const adjusted={...params};if(!this.historyReady){adjusted.feedback=0;adjusted.temporal=0;adjusted.temporalRgb=0;}
      this.device.queue.writeBuffer(this.uniformBuffer,0,gpuParams(adjusted,this.width,this.height));
      const encoder=this.device.createCommandEncoder({label:'tubeviz-frame'});const swapTexture=this.context.getCurrentTexture();
      const pass=encoder.beginRenderPass({label:'tubeviz-compositor-pass',colorAttachments:[{view:swapTexture.createView(),clearValue:{r:0,g:0,b:0,a:1},loadOp:'clear',storeOp:'store'}]});
      pass.setPipeline(this.pipeline);pass.setBindGroup(0,this.bindGroup);pass.draw(3);pass.end();
      encoder.copyTextureToTexture({texture:swapTexture},{texture:this.historyTexture},[this.width,this.height]);
      this.device.queue.submit([encoder.finish()]);this.historyReady=true;return true;
    }catch(error){this.failed=true;this.failureReason=String(error?.message||error);console.warn('tubeviz WebGPU compositor failed',error);return false;}
  }
  renderLayers(layerList,params={},composition={}){
    if(this.failed||!this.layerPipeline||!Array.isArray(layerList)||!layerList.length)return false;
    try{
      const usable=layerList.filter(item=>item?.source&&externalTextureSourceUsable(item.source)).slice(0,4);if(!usable.length)return false;
      const source0=usable[0].source,actualCount=usable.length;
      const width=Math.max(1,Math.floor(Number(composition.width||this.canvas.width||source0.displayWidth||source0.videoWidth||source0.width||1)));
      const height=Math.max(1,Math.floor(Number(composition.height||this.canvas.height||source0.displayHeight||source0.videoHeight||source0.height||1)));
      this.resize(width,height);
      while(usable.length<4)usable.push(usable[0]);
      const external=usable.map(item=>this.device.importExternalTexture({source:item.source}));
      this.device.queue.writeBuffer(this.layerUniformBuffer,0,layerUniforms(usable,{...composition,count:actualCount},width,height));
      const layerBindGroup=this.device.createBindGroup({layout:this.layerPipeline.getBindGroupLayout(0),entries:[
        {binding:0,resource:external[0]},{binding:1,resource:external[1]},{binding:2,resource:external[2]},{binding:3,resource:external[3]},{binding:4,resource:this.sampler},{binding:5,resource:{buffer:this.layerUniformBuffer}},
      ]});
      const adjusted={...params};if(!this.historyReady){adjusted.feedback=0;adjusted.temporal=0;adjusted.temporalRgb=0;}
      this.device.queue.writeBuffer(this.uniformBuffer,0,gpuParams(adjusted,width,height));
      const encoder=this.device.createCommandEncoder({label:'tubeviz-direct-preview-frame'});
      const compose=encoder.beginRenderPass({label:'tubeviz-direct-layer-pass',colorAttachments:[{view:this.compositionTexture.createView(),clearValue:{r:0,g:0,b:0,a:1},loadOp:'clear',storeOp:'store'}]});
      compose.setPipeline(this.layerPipeline);compose.setBindGroup(0,layerBindGroup);compose.draw(3);compose.end();
      const swapTexture=this.context.getCurrentTexture();
      const post=encoder.beginRenderPass({label:'tubeviz-direct-post-pass',colorAttachments:[{view:swapTexture.createView(),clearValue:{r:0,g:0,b:0,a:1},loadOp:'clear',storeOp:'store'}]});
      post.setPipeline(this.pipeline);post.setBindGroup(0,this.compositionBindGroup);post.draw(3);post.end();
      encoder.copyTextureToTexture({texture:swapTexture},{texture:this.historyTexture},[width,height]);
      this.device.queue.submit([encoder.finish()]);this.historyReady=true;return true;
    }catch(error){
      this.failed=true;this.failureReason=String(error?.message||error);console.warn('tubeviz direct WebGPU preview failed',error);return false;
    }
  }
  resetHistory(){this.historyReady=false;}
  async sync(){try{await this.device.queue.onSubmittedWorkDone();return !this.failed;}catch(error){this.failed=true;this.failureReason=String(error?.message||error);return false;}}
}

function compilationErrorText(info){
  const errors=Array.from(info?.messages||[]).filter(message=>message.type==='error');
  if(!errors.length)return '';
  return errors.map(message=>{
    const where=message.lineNum?`:${message.lineNum}:${message.linePos||1}`:'';
    return `${where} ${message.message}`.trim();
  }).join('; ');
}

async function createGpuPipeline(device,format){
  const shader=device.createShaderModule({label:'tubeviz-compositor-wgsl',code:TUBEVIZ_GPU_SHADER});
  if(typeof shader.getCompilationInfo==='function'){
    const info=await shader.getCompilationInfo();
    const errorText=compilationErrorText(info);
    if(errorText)throw new Error(`tubeviz WGSL compilation failed: ${errorText}`);
  }
  const descriptor={
    label:'tubeviz-compositor-pipeline',
    layout:'auto',
    vertex:{module:shader,entryPoint:'vs_main'},
    fragment:{module:shader,entryPoint:'fs_main',targets:[{format}]},
    primitive:{topology:'triangle-list'},
  };
  if(typeof device.createRenderPipelineAsync==='function')return await device.createRenderPipelineAsync(descriptor);
  device.pushErrorScope('validation');
  const pipeline=device.createRenderPipeline(descriptor);
  const validationError=await device.popErrorScope();
  if(validationError)throw new Error(`tubeviz WebGPU pipeline validation failed: ${validationError.message}`);
  return pipeline;
}


async function createLayerPipeline(device){
  const shader=device.createShaderModule({label:'tubeviz-layer-compositor-wgsl',code:TUBEVIZ_GPU_LAYER_SHADER});
  if(typeof shader.getCompilationInfo==='function'){
    const info=await shader.getCompilationInfo();const errorText=compilationErrorText(info);
    if(errorText)throw new Error(`tubeviz layer WGSL compilation failed: ${errorText}`);
  }
  const descriptor={label:'tubeviz-layer-compositor-pipeline',layout:'auto',vertex:{module:shader,entryPoint:'layer_vs'},fragment:{module:shader,entryPoint:'layer_fs',targets:[{format:'rgba8unorm'}]},primitive:{topology:'triangle-list'}};
  if(typeof device.createRenderPipelineAsync==='function')return await device.createRenderPipelineAsync(descriptor);
  return device.createRenderPipeline(descriptor);
}

export async function createGpuRendererCore(canvas,{powerPreference='high-performance',enableExternalLayers=true}={}){
  if(!globalThis.navigator?.gpu)throw new Error('navigator.gpu unavailable');
  const adapter=await navigator.gpu.requestAdapter({powerPreference});if(!adapter)throw new Error('no WebGPU adapter');
  const device=await adapter.requestDevice();const context=canvas.getContext('webgpu');if(!context)throw new Error('WebGPU canvas context unavailable');
  const format=navigator.gpu.getPreferredCanvasFormat();
  const pipeline=await createGpuPipeline(device,format);
  const layerPipeline=enableExternalLayers?await createLayerPipeline(device):null;
  context.configure({device,format,alphaMode:'opaque',usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.COPY_SRC});
  return new BrowserGpuRendererCore(canvas,device,context,format,pipeline,layerPipeline);
}
