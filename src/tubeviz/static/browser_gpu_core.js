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
  // Full-frame wave/flow/ripple/tempo deformation: no hard circular boundaries.
  let wave=vec2f(sin(uv.y*13.0+time*1.7),cos(uv.x*11.0-time*1.3));
  let ripple=vec2f(sin(uv.y*24.0-time*3.1),cos(uv.x*21.0+time*2.4))*params.p8.w*.0045;
  let tempo=vec2f(sin((uv.y+time*.08)*18.0),cos((uv.x-time*.06)*16.0))*params.p9.x*.0035;
  uv=satUv(uv+wave*(warp*.010+flow*.006)+ripple+tempo);
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
  ]);
}

export class BrowserGpuRendererCore{
  constructor(canvas,device,context,format,pipeline){
    this.canvas=canvas;this.device=device;this.context=context;this.format=format;this.pipeline=pipeline;this.width=0;this.height=0;this.failed=false;this.failureReason='';this.historyReady=false;this.onDeviceLost=null;
    this.sampler=device.createSampler({magFilter:'linear',minFilter:'linear',addressModeU:'clamp-to-edge',addressModeV:'clamp-to-edge'});
    this.uniformBuffer=device.createBuffer({size:176,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
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
    for(const t of [this.effectTexture,this.sourceTexture,this.historyTexture])t?.destroy();
    const srcUsage=GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT;
    this.effectTexture=this.device.createTexture({label:'tubeviz-effect-source',size:[width,height],format:'rgba8unorm',usage:srcUsage});
    this.sourceTexture=this.device.createTexture({label:'tubeviz-source-color',size:[width,height],format:'rgba8unorm',usage:srcUsage});
    this.historyTexture=this.device.createTexture({label:'tubeviz-history',size:[width,height],format:this.format,usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST});
    this.bindGroup=this.device.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[
      {binding:0,resource:this.sampler},{binding:1,resource:this.effectTexture.createView()},{binding:2,resource:this.sourceTexture.createView()},{binding:3,resource:this.historyTexture.createView()},{binding:4,resource:{buffer:this.uniformBuffer}},
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

export async function createGpuRendererCore(canvas,{powerPreference='high-performance'}={}){
  if(!globalThis.navigator?.gpu)throw new Error('navigator.gpu unavailable');
  const adapter=await navigator.gpu.requestAdapter({powerPreference});if(!adapter)throw new Error('no WebGPU adapter');
  const device=await adapter.requestDevice();const context=canvas.getContext('webgpu');if(!context)throw new Error('WebGPU canvas context unavailable');
  const format=navigator.gpu.getPreferredCanvasFormat();
  const pipeline=await createGpuPipeline(device,format);
  context.configure({device,format,alphaMode:'opaque',usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.COPY_SRC});
  return new BrowserGpuRendererCore(canvas,device,context,format,pipeline);
}
