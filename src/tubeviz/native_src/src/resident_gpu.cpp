// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/resident_gpu.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <string_view>

extern "C" {
#include <libavutil/pixdesc.h>
}

#ifdef TUBEVIZ_HAVE_PLACEBO
#include <libplacebo/gpu.h>
#include <libplacebo/log.h>
#include <libplacebo/renderer.h>
#include <libplacebo/shaders/custom.h>
#define PL_LIBAV_IMPLEMENTATION 0
#include <libplacebo/utils/libav.h>
#include <libplacebo/vulkan.h>
#endif

namespace tubeviz {
namespace {

using Clock = std::chrono::steady_clock;

double elapsed_ms(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

double curve4(const double (&values)[4], double p) {
    p = std::clamp(p, 0.0, 1.0);
    const double q = p * 3.0;
    const int i = std::min(2, static_cast<int>(q));
    const double f = q - i;
    return std::clamp(values[i] * (1.0 - f) + values[i + 1] * f, 0.0, 1.0);
}

double hero_env(const CreativeEffect& c, double p) {
    if (c.hero_kind.empty() || c.hero_amount <= 0.0 || p < c.hero_start || p > c.hero_end) return 0.0;
    const double q = (p - c.hero_start) / std::max(1e-6, c.hero_end - c.hero_start);
    auto smooth = [](double x) {
        x = std::clamp(x, 0.0, 1.0);
        return x * x * (3.0 - 2.0 * x);
    };
    return c.hero_amount * std::min(smooth(q / .16), smooth((1.0 - q) / .22));
}

int composition_id(const std::string& mode) {
    if (mode == "flow") return 1;
    if (mode == "luma") return 2;
    if (mode == "strips") return 3;
    if (mode == "split") return 4;
    if (mode == "mosaic") return 5;
    if (mode == "swap") return 6;
    return 0;
}

int blend_id(const std::string& mode) {
    if (mode == "screen") return 1;
    if (mode == "multiply") return 2;
    if (mode == "add" || mode == "lighter" || mode == "plus") return 3;
    return 0;
}

int vector_id(const std::string& kind) {
    if (kind == "semantic_outline" || kind == "contours") return 1;
    if (kind == "perspective_grid") return 2;
    if (kind == "portal") return 3;
    if (kind == "flow_ribbons" || kind == "flow_particles") return 4;
    if (kind == "voronoi" || kind == "delaunay_fracture") return 5;
    if (kind == "vector_echo") return 6;
    return 0;
}

bool hardware_frame(const AVFrame* frame) {
    if (!frame) return false;
    const auto* desc = av_pix_fmt_desc_get(static_cast<AVPixelFormat>(frame->format));
    return desc && (desc->flags & AV_PIX_FMT_FLAG_HWACCEL);
}

#ifdef TUBEVIZ_HAVE_PLACEBO

constexpr std::string_view kLayerShader = R"SHADER(
//!PARAM opacity
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
1.0
//!PARAM mirror
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM zoom
//!TYPE DYNAMIC float
//!MINIMUM 0.2
//!MAXIMUM 4.0
1.0
//!PARAM pan_x
//!TYPE DYNAMIC float
//!MINIMUM -1.0
//!MAXIMUM 1.0
0.0
//!PARAM pan_y
//!TYPE DYNAMIC float
//!MINIMUM -1.0
//!MAXIMUM 1.0
0.0
//!PARAM rotation
//!TYPE DYNAMIC float
//!MINIMUM -6.4
//!MAXIMUM 6.4
0.0
//!PARAM brightness
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 3.0
1.0
//!PARAM contrast
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 3.0
1.0
//!PARAM saturation
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 3.0
1.0
//!PARAM grayscale
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM hue
//!TYPE DYNAMIC float
//!MINIMUM -0.5
//!MAXIMUM 0.5
0.0
//!PARAM scanlines
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM vignette
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM noise
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM pixelate
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM rgb_split
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM ripple
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM vortex
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM blur
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 4.0
0.0
//!PARAM comp_mode
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 6.0
0.0
//!PARAM layer_index
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 4.0
0.0
//!PARAM layer_count
//!TYPE DYNAMIC float
//!MINIMUM 1.0
//!MAXIMUM 4.0
1.0
//!PARAM comp_progress
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM phase
//!TYPE DYNAMIC float
0.0
//!PARAM blend_mode
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 3.0
0.0

//!HOOK MAIN
//!BIND HOOKED
//!DESC tubeviz resident layer transform

vec3 tv_hue(vec3 c, float a) {
    float y=dot(c,vec3(.299,.587,.114));
    float i=dot(c,vec3(.596,-.274,-.322));
    float q=dot(c,vec3(.211,-.523,.312));
    float cs=cos(a), sn=sin(a);
    float ii=i*cs-q*sn, qq=i*sn+q*cs;
    return vec3(y+.956*ii+.621*qq,y-.272*ii-.647*qq,y-1.106*ii+1.703*qq);
}

float tv_hash(vec2 p) {
    return fract(sin(dot(p,vec2(127.1,311.7))) * 43758.5453);
}

vec4 hook() {
    vec2 uv=HOOKED_pos;
    if (mirror > .5) uv.x=1.0-uv.x;
    vec2 d=uv-vec2(.5);
    float cs=cos(-rotation), sn=sin(-rotation);
    d=mat2(cs,-sn,sn,cs)*d/max(zoom,.2);
    uv=vec2(.5)+d-vec2(pan_x,pan_y);

    if (vortex > .0001) {
        vec2 vd=uv-vec2(.5); float r=length(vd);
        float a=vortex*.11*(1.0-smoothstep(.05,.78,r));
        float vc=cos(a), vs=sin(a); uv=vec2(.5)+mat2(vc,-vs,vs,vc)*vd;
    }
    if (ripple > .0001) {
        vec2 rd=uv-vec2(.5); float r=max(length(rd),.001);
        uv += normalize(rd)*sin(r*42.0-phase*6.0)*ripple*.008*(1.0-r);
    }
    if (pixelate > .0001) {
        float blocks=mix(420.0,32.0,clamp(pixelate,0.0,1.0));
        vec2 grid=max(vec2(8.0),vec2(blocks,blocks*HOOKED_size.y/max(HOOKED_size.x,1.0)));
        uv=(floor(uv*grid)+.5)/grid;
    }
    uv=clamp(uv,vec2(.001),vec2(.999));
    vec4 c=HOOKED_tex(uv);

    float split=rgb_split*.006;
    if (split>.0001) {
        c.r=HOOKED_tex(clamp(uv+vec2(split,0),vec2(.001),vec2(.999))).r;
        c.b=HOOKED_tex(clamp(uv-vec2(split,0),vec2(.001),vec2(.999))).b;
    }
    if (blur>.35) {
        vec2 px=HOOKED_pt*min(3.0,blur);
        vec3 b=HOOKED_tex(clamp(uv+vec2(px.x,0),vec2(.001),vec2(.999))).rgb
              +HOOKED_tex(clamp(uv-vec2(px.x,0),vec2(.001),vec2(.999))).rgb
              +HOOKED_tex(clamp(uv+vec2(0,px.y),vec2(.001),vec2(.999))).rgb
              +HOOKED_tex(clamp(uv-vec2(0,px.y),vec2(.001),vec2(.999))).rgb;
        c.rgb=mix(c.rgb,b*.25,clamp(blur*.12,0.0,.55));
    }

    float y=dot(c.rgb,vec3(.2126,.7152,.0722));
    c.rgb=mix(c.rgb,vec3(y),clamp(grayscale,0.0,1.0));
    c.rgb=vec3(y)+(c.rgb-vec3(y))*saturation;
    c.rgb=tv_hue(c.rgb,hue);
    c.rgb=(c.rgb-vec3(.5))*contrast+vec3(.5);
    c.rgb*=brightness;

    float scan=1.0-scanlines*.12*(.5+.5*sin(HOOKED_pos.y*HOOKED_size.y*3.14159265));
    vec2 q=HOOKED_pos-vec2(.5); float vr=dot(q,q)*2.0;
    float vig=1.0-clamp(vignette,0.0,1.0)*.48*smoothstep(.15,1.0,vr);
    float n=(tv_hash(HOOKED_pos*HOOKED_size+phase)-.5)*noise*.08;
    c.rgb=clamp(c.rgb*scan*vig+n,0.0,1.0);

    if (blend_mode>.5 && blend_mode<1.5) c.rgb=sqrt(max(c.rgb,vec3(0.0)));
    else if (blend_mode>=1.5 && blend_mode<2.5) c.rgb*=c.rgb;
    else if (blend_mode>=2.5) c.rgb=min(vec3(1.0),c.rgb*1.22);

    float mask=1.0;
    if (layer_index>.5) {
        if (comp_mode<.5) mask=0.0;
        else if (comp_mode<1.5) {
            float w=.5+.5*sin(HOOKED_pos.y*17.0+HOOKED_pos.x*6.0+phase*3.0+layer_index*2.1);
            mask=smoothstep(.46,.58,w);
        } else if (comp_mode<2.5) {
            mask=smoothstep(.34,.66,y);
        } else if (comp_mode<3.5) {
            float stripes=mod(floor((HOOKED_pos.y+.03*sin(phase))*12.0),max(2.0,layer_count));
            mask=1.0-step(.45,abs(stripes-layer_index));
        } else if (comp_mode<4.5) {
            float edge=mix(.82,.18,comp_progress);
            mask=layer_index<1.5 ? step(edge,HOOKED_pos.x) : step(HOOKED_pos.x,1.0-edge);
        } else if (comp_mode<5.5) {
            vec2 cell=floor(HOOKED_pos*vec2(4.0,3.0));
            float owner=mod(cell.x+cell.y*4.0,max(1.0,layer_count));
            mask=1.0-step(.45,abs(owner-layer_index));
        } else {
            float owner=mod(floor(comp_progress*8.0+phase*.35),max(1.0,layer_count));
            mask=1.0-step(.45,abs(owner-layer_index));
        }
    }
    c.a=clamp(opacity*mask,0.0,1.0);
    return c;
}
)SHADER";

constexpr std::string_view kFinalShader = R"SHADER(
//!PARAM camera
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM flow
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM depth
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM symmetry
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM bloom
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM streaks
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM palette
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM target_x
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.5
//!PARAM target_y
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.5
//!PARAM drift_x
//!TYPE DYNAMIC float
//!MINIMUM -2.0
//!MAXIMUM 2.0
0.0
//!PARAM drift_y
//!TYPE DYNAMIC float
//!MINIMUM -2.0
//!MAXIMUM 2.0
0.0
//!PARAM progress
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM phase
//!TYPE DYNAMIC float
0.0
//!PARAM hue
//!TYPE DYNAMIC float
//!MINIMUM -0.5
//!MAXIMUM 0.5
0.0
//!PARAM saturation
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 3.0
1.0
//!PARAM contrast
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 3.0
1.0
//!PARAM brightness
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 3.0
1.0
//!PARAM palette_r
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.5
//!PARAM palette_g
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.6
//!PARAM palette_b
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.8
//!PARAM source_fidelity
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.9
//!PARAM beat
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM beat_low
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM beat_mid
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM beat_high
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM beat_mode
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 7.0
4.0
//!PARAM beat_center_x
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.5
//!PARAM beat_center_y
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.5
//!PARAM beat_direction
//!TYPE DYNAMIC float
0.0
//!PARAM beat_frequency
//!TYPE DYNAMIC float
//!MINIMUM 0.5
//!MAXIMUM 3.0
1.0
//!PARAM ripple
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM vortex
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM glitch
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM kaleido
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM tiles
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM tunnel
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM posterize
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM edge
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM strobe
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM shutter
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM slit
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM corridor
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM mask_wipe
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM solarize
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM block
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM chroma
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM vhs
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM slice
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM pixelate
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM rgb_split
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM vector_kind
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 6.0
0.0
//!PARAM vector_amount
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.5
0.0
//!PARAM vector_opacity
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM out_alpha
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
1.0

//!HOOK MAIN
//!BIND HOOKED
//!DESC tubeviz resident final creative/post pass

vec3 tv_hue(vec3 c,float a){float y=dot(c,vec3(.299,.587,.114));float i=dot(c,vec3(.596,-.274,-.322));float q=dot(c,vec3(.211,-.523,.312));float cs=cos(a),sn=sin(a);float ii=i*cs-q*sn,qq=i*sn+q*cs;return vec3(y+.956*ii+.621*qq,y-.272*ii-.647*qq,y-1.106*ii+1.703*qq);}
float tv_hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}

vec4 hook(){
    vec2 p0=HOOKED_pos, uv=p0, center=vec2(target_x,target_y);
    vec2 d=uv-center;
    float zoom=1.0+camera*(.012+.045*(.5-.5*cos(3.14159265*progress)))+beat_low*.012;
    vec2 drift=vec2(sin(progress*5.0+phase*.08)*drift_x*.010,sin(progress*4.0+phase*.07)*drift_y*.008)*camera;
    uv=center+(d-drift)/max(zoom,.2);

    if(beat>.0001){vec2 bc=vec2(beat_center_x,beat_center_y),bp=uv-bc;float br=max(length(bp),.001);vec2 dir=vec2(cos(beat_direction),sin(beat_direction)),nrm=vec2(-dir.y,dir.x);float ba=beat*(.72+.20*beat_low+.13*beat_mid+.08*beat_high);if(beat_mode<1.5)uv-=bp*ba*.065*(1.0-smoothstep(.1,.85,br));else if(beat_mode<3.0)uv+=dir*sin(dot(bp,nrm)*28.0*beat_frequency+phase*8.0)*ba*.034;else if(beat_mode<4.5){float a=ba*.18*(1.0-smoothstep(.1,.8,br));float cs=cos(a),sn=sin(a);uv=bc+mat2(cs,-sn,sn,cs)*bp;}else if(beat_mode<6.0)uv+=vec2(bp.x*bp.y,(bp.x*bp.x-bp.y*bp.y)*.55)*ba*.26;else uv-=bp*ba*.08*(1.0-smoothstep(.05,.72,br));}

    if(vortex>.0001){vec2 vd=uv-center;float r=length(vd);float a=vortex*.075*(1.0-smoothstep(.06,.88,r));float cs=cos(a),sn=sin(a);uv=center+mat2(cs,-sn,sn,cs)*vd;}
    float wave=flow*.010+ripple*.008;uv.x+=sin(uv.y*24.0+phase*3.7+uv.x*5.0)*wave;uv.y+=cos(uv.x*19.0-phase*3.1+uv.y*4.0)*wave*.72;
    vec4 reference=HOOKED_tex(clamp(p0,vec2(.001),vec2(.999)));
    float rl=dot(reference.rgb,vec3(.2126,.7152,.0722));float dep=clamp(.18+.56*(1.0-p0.y)+.06*(1.0-rl),0.0,1.0)-.5;uv+=vec2(drift_x*.018,drift_y*.014)*dep*depth;

    if(kaleido>.04||symmetry>.065){float amt=max(kaleido,symmetry);vec2 kd=uv-center;float r=length(kd),a=atan(kd.y,kd.x);float seg=6.2831853/mix(5.0,9.0,clamp(amt*.5,0.0,1.0));a=abs(mod(a+seg*.5,seg)-seg*.5);uv=mix(uv,center+r*vec2(cos(a),sin(a)),clamp(amt*.58,0.0,.86));}
    if(corridor>.03){vec2 cd=abs(uv-.5);uv=.5+sign(uv-.5)*abs(mod(cd*(1.0+corridor*2.0),.5)-.25)*2.0;}
    if(tunnel>.03){vec2 td=uv-center;float r=max(length(td),.004),a=atan(td.y,td.x);r=fract(r*(1.0+tunnel*1.7)-phase*.03*tunnel);uv=center+clamp(r,0.0,.7)*vec2(cos(a),sin(a));}
    if(tiles>.03){float n=mix(1.0,7.0,clamp(tiles,0.0,1.0));uv=fract(uv*n);}
    if(slit>.03||vhs>.03){float band=floor(uv.y*mix(8.0,44.0,clamp(max(slit,vhs),0.0,1.0)));uv.x+=sin(band*2.7+phase*7.0)*(.004+.018*max(slit,vhs));}
    if(block>.03){vec2 cell=floor(uv*vec2(16.0,10.0));float h=tv_hash(cell+floor(phase*3.0));if(h>.74)uv.x+=(h-.5)*block*.07;}
    if(slice>.03){float band=floor(uv.y*12.0);uv.x+=sin(band*1.9+phase)*slice*.024;}
    if(glitch>.03){float band=floor(uv.y*32.0);float h=tv_hash(vec2(band,floor(phase*6.0)));if(h>.72)uv.x+=(h-.5)*glitch*.055;}
    if(mask_wipe>.03){float m=smoothstep(progress-.18,progress+.18,uv.x+.08*sin(uv.y*10.0+phase));uv.x+=sin(uv.y*18.0+phase)*mask_wipe*.012*(1.0-m);}
    if(pixelate>.03){float cells=mix(420.0,28.0,clamp(pixelate,0.0,1.0));vec2 grid=vec2(cells,cells*HOOKED_size.y/max(HOOKED_size.x,1.0));uv=(floor(uv*grid)+.5)/grid;}
    uv=clamp(uv,vec2(.001),vec2(.999));

    vec4 c=HOOKED_tex(uv);
    float split=clamp(rgb_split*.007+chroma*.009+beat_high*.0035,0.0,.028);if(split>.0001){vec2 dir=normalize(vec2(.82+.15*sin(phase),.34+.18*cos(phase*.7)));c.r=HOOKED_tex(clamp(uv+dir*split,vec2(.001),vec2(.999))).r;c.b=HOOKED_tex(clamp(uv-dir*split,vec2(.001),vec2(.999))).b;}

    float bamt=clamp(bloom*.18,0.0,.38), samt=clamp(streaks*.12+beat_mid*.05,0.0,.25);if(bamt+samt>.006){vec2 px=HOOKED_pt;vec3 b=HOOKED_tex(clamp(uv+vec2(px.x*3.0,0),vec2(.001),vec2(.999))).rgb+HOOKED_tex(clamp(uv-vec2(px.x*3.0,0),vec2(.001),vec2(.999))).rgb+HOOKED_tex(clamp(uv+vec2(0,px.y*3.0),vec2(.001),vec2(.999))).rgb+HOOKED_tex(clamp(uv-vec2(0,px.y*3.0),vec2(.001),vec2(.999))).rgb;b*=.25;vec3 s=HOOKED_tex(clamp(uv+vec2(px.x*10.0,0),vec2(.001),vec2(.999))).rgb+HOOKED_tex(clamp(uv-vec2(px.x*10.0,0),vec2(.001),vec2(.999))).rgb;s*=.5;c.rgb=mix(c.rgb,max(c.rgb,b),bamt);c.rgb=mix(c.rgb,max(c.rgb,s),samt);}

    if(edge>.03||vector_kind>0.5&&vector_kind<1.5){vec2 px=HOOKED_pt*2.0;vec3 gx=HOOKED_tex(clamp(uv+vec2(px.x,0),vec2(.001),vec2(.999))).rgb-HOOKED_tex(clamp(uv-vec2(px.x,0),vec2(.001),vec2(.999))).rgb;vec3 gy=HOOKED_tex(clamp(uv+vec2(0,px.y),vec2(.001),vec2(.999))).rgb-HOOKED_tex(clamp(uv-vec2(0,px.y),vec2(.001),vec2(.999))).rgb;float e=clamp(length(gx)+length(gy),0.0,1.0);float ea=clamp(edge*.7+vector_amount*vector_opacity*.5,0.0,.85);c.rgb=mix(c.rgb,vec3(e),ea);}
    if(vector_kind>1.5&&vector_kind<2.5){float gx=1.0-smoothstep(.0,.018,abs(fract((uv.x-.5)*12.0/max(.2,uv.y+.25))-.5));float gy=1.0-smoothstep(.0,.025,abs(fract(uv.y*12.0)-.5));float g=max(gx,gy)*vector_amount*vector_opacity;c.rgb=mix(c.rgb,max(c.rgb,vec3(.25,.65,1.0)*g),clamp(g,0.0,.7));}
    if(vector_kind>2.5&&vector_kind<3.5){float r=length(uv-center);float ring=1.0-smoothstep(.0,.025,abs(r-(.18+.05*sin(phase))));float a=ring*vector_amount*vector_opacity;c.rgb=mix(c.rgb,max(c.rgb,vec3(.4,.75,1.0)*a),clamp(a,0.0,.8));}
    if(vector_kind>3.5&&vector_kind<4.5){float f=.5+.5*sin(uv.x*23.0+sin(uv.y*9.0+phase)*4.0+phase*2.0);float a=smoothstep(.78,.96,f)*vector_amount*vector_opacity;c.rgb=mix(c.rgb,max(c.rgb,vec3(.35,.8,1.0)*a),clamp(a,0.0,.65));}
    if(vector_kind>4.5&&vector_kind<5.5){vec2 cell=floor(uv*10.0),q=fract(uv*10.0)-.5;float h=tv_hash(cell);float line=1.0-smoothstep(.34,.48,length(q+vec2(h-.5,.5-h)*.35));float a=line*vector_amount*vector_opacity*.65;c.rgb=mix(c.rgb,max(c.rgb,vec3(.75,.55,1.0)*a),clamp(a,0.0,.65));}
    if(vector_kind>5.5){vec2 off=vec2(.006*sin(phase),.004*cos(phase));vec3 echo=HOOKED_tex(clamp(uv+off,vec2(.001),vec2(.999))).rgb;float a=vector_amount*vector_opacity*.32;c.rgb=mix(c.rgb,max(c.rgb,echo),clamp(a,0.0,.5));}

    float y=dot(c.rgb,vec3(.2126,.7152,.0722));c.rgb=vec3(y)+(c.rgb-vec3(y))*saturation;c.rgb=tv_hue(c.rgb,hue);c.rgb=(c.rgb-vec3(.5))*contrast+vec3(.5);c.rgb*=brightness;c.rgb=mix(c.rgb,vec3(palette_r,palette_g,palette_b),clamp(palette*.12,0.0,.16));
    if(posterize>.03){float levels=mix(16.0,3.0,clamp(posterize,0.0,1.0));c.rgb=floor(c.rgb*levels+.5)/levels;}
    if(solarize>.03){vec3 sol=1.0-abs(c.rgb*2.0-1.0);c.rgb=mix(c.rgb,sol,clamp(solarize,0.0,1.0));}
    if(strobe>.03)c.rgb*=mix(1.0,.15+.85*step(.5,fract(phase*3.0)),clamp(strobe,0.0,1.0));
    if(shutter>.03)c.rgb*=mix(1.0,.55+.45*step(.35,fract(phase*1.7)),clamp(shutter,0.0,1.0));

    float yo=dot(c.rgb,vec3(.299,.587,.114)),io=dot(c.rgb,vec3(.596,-.274,-.322)),qo=dot(c.rgb,vec3(.211,-.523,.312));float ir=dot(reference.rgb,vec3(.596,-.274,-.322)),qr=dot(reference.rgb,vec3(.211,-.523,.312));float f=clamp(source_fidelity*.82,0.0,.92);io=mix(io,ir,f);qo=mix(qo,qr,f);c.rgb=vec3(yo+.956*io+.621*qo,yo-.272*io-.647*qo,yo-1.106*io+1.703*qo);
    c.rgb=clamp(c.rgb,0.0,1.0);c.a=out_alpha;return c;
}
)SHADER";

void set_param(const pl_hook* hook, const char* name, float value) {
    if (!hook) return;
    for (int i = 0; i < hook->num_parameters; ++i) {
        const auto& p = hook->parameters[i];
        if (p.name && std::strcmp(p.name, name) == 0 && p.data) {
            p.data->f = value;
            return;
        }
    }
}

pl_frame texture_frame(pl_tex tex, int components, int width, int height) {
    pl_frame frame{};
    frame.num_planes = 1;
    frame.planes[0].texture = tex;
    frame.planes[0].components = components;
    for (int i = 0; i < components; ++i) frame.planes[0].component_mapping[i] = i;
    frame.crop = {0.0f, 0.0f, static_cast<float>(width), static_cast<float>(height)};
    if (components == 4) frame.repr.alpha = PL_ALPHA_INDEPENDENT;
    return frame;
}

void preserve_target(pl_render_params& params, bool preserve) {
#if PL_API_VER >= 346
    if (preserve) params.background = params.border = PL_CLEAR_SKIP;
#else
    params.skip_target_clearing = preserve;
#endif
}

#endif

} // namespace

struct ResidentGpuPipeline::Impl {
    int width{0};
    int height{0};
#ifdef TUBEVIZ_HAVE_PLACEBO
    pl_log log{nullptr};
    pl_vulkan vk{nullptr};
    pl_gpu gpu{nullptr};
    pl_renderer renderer{nullptr};
    pl_tex compose{nullptr};
    pl_tex final_tex{nullptr};
    pl_tex history{nullptr};
    pl_tex output{nullptr};
    pl_tex mapped_tex[4][PL_MAX_PLANES]{};
    const pl_hook* layer_hook{nullptr};
    const pl_hook* final_hook{nullptr};
    int output_components{3};
    bool has_history{false};
    std::vector<std::uint8_t> rgba_out;
#endif
};

ResidentGpuPipeline::ResidentGpuPipeline(int width, int height, std::string mode)
    : impl_(std::make_unique<Impl>()) {
    impl_->width = width;
    impl_->height = height;
    if (mode == "off" || mode == "none" || mode == "cpu") return;
#ifdef TUBEVIZ_HAVE_PLACEBO
    pl_log_params log_params{};
    log_params.log_cb = pl_log_simple;
    log_params.log_level = PL_LOG_WARN;
    impl_->log = pl_log_create(PL_API_VER, &log_params);
    if (!impl_->log) return;
    impl_->vk = pl_vulkan_create(impl_->log, nullptr);
    if (!impl_->vk) {
        if (mode != "auto") std::cerr << "WARN\tresident Vulkan/libplacebo context creation failed\n";
        return;
    }
    impl_->gpu = impl_->vk->gpu;
    impl_->renderer = pl_renderer_create(impl_->log, impl_->gpu);
    if (!impl_->renderer) return;

    const auto rgba_caps = static_cast<pl_fmt_caps>(
        PL_FMT_CAP_SAMPLEABLE | PL_FMT_CAP_LINEAR | PL_FMT_CAP_RENDERABLE |
        PL_FMT_CAP_BLENDABLE | PL_FMT_CAP_BLITTABLE
    );
    pl_fmt rgba = pl_find_fmt(impl_->gpu, PL_FMT_UNORM, 4, 8, 8, rgba_caps);
    if (!rgba) rgba = pl_find_named_fmt(impl_->gpu, "rgba8");
    if (!rgba || !(rgba->caps & PL_FMT_CAP_RENDERABLE) || !(rgba->caps & PL_FMT_CAP_BLENDABLE)) return;

    pl_tex_params work{};
    work.w = width; work.h = height; work.format = rgba;
    work.sampleable = true; work.renderable = true; work.blit_src = true; work.blit_dst = true;
    if (!pl_tex_recreate(impl_->gpu, &impl_->compose, &work) ||
        !pl_tex_recreate(impl_->gpu, &impl_->final_tex, &work) ||
        !pl_tex_recreate(impl_->gpu, &impl_->history, &work)) return;

    const auto rgb_caps = static_cast<pl_fmt_caps>(
        PL_FMT_CAP_RENDERABLE | PL_FMT_CAP_HOST_READABLE
    );
    pl_fmt rgb = pl_find_fmt(impl_->gpu, PL_FMT_UNORM, 3, 8, 8, rgb_caps);
    if (rgb) {
        impl_->output_components = 3;
    } else {
        rgb = rgba;
        impl_->output_components = 4;
        impl_->rgba_out.resize(static_cast<std::size_t>(width) * height * 4);
    }
    pl_tex_params out{};
    out.w = width; out.h = height; out.format = rgb;
    out.renderable = true; out.host_readable = true;
    if (!pl_tex_recreate(impl_->gpu, &impl_->output, &out)) return;

    impl_->layer_hook = pl_mpv_user_shader_parse(impl_->gpu, kLayerShader.data(), kLayerShader.size());
    impl_->final_hook = pl_mpv_user_shader_parse(impl_->gpu, kFinalShader.data(), kFinalShader.size());
    if (!impl_->layer_hook || !impl_->final_hook) return;

    backend_ = "vulkan-resident";
#else
    (void)mode;
#endif
}

ResidentGpuPipeline::~ResidentGpuPipeline() {
#ifdef TUBEVIZ_HAVE_PLACEBO
    if (impl_) {
        if (impl_->gpu) {
            for (auto& layer : impl_->mapped_tex) for (auto& tex : layer) pl_tex_destroy(impl_->gpu, &tex);
            pl_tex_destroy(impl_->gpu, &impl_->output);
            pl_tex_destroy(impl_->gpu, &impl_->history);
            pl_tex_destroy(impl_->gpu, &impl_->final_tex);
            pl_tex_destroy(impl_->gpu, &impl_->compose);
        }
        if (impl_->layer_hook) pl_mpv_user_shader_destroy(&impl_->layer_hook);
        if (impl_->final_hook) pl_mpv_user_shader_destroy(&impl_->final_hook);
        if (impl_->renderer) pl_renderer_destroy(&impl_->renderer);
        if (impl_->vk) pl_vulkan_destroy(&impl_->vk);
        if (impl_->log) pl_log_destroy(&impl_->log);
    }
#endif
}

bool ResidentGpuPipeline::available() const noexcept { return backend_ != "off"; }
const std::string& ResidentGpuPipeline::backend() const noexcept { return backend_; }
bool ResidentGpuPipeline::last_hardware_map_failed() const noexcept { return last_hardware_map_failed_; }

void ResidentGpuPipeline::reset_history() {
#ifdef TUBEVIZ_HAVE_PLACEBO
    if (impl_) impl_->has_history = false;
#endif
}

bool ResidentGpuPipeline::render(
    const std::vector<ResidentLayerFrame>& layers,
    const std::string& composition_mode,
    const CreativeEffect& creative,
    const ReactiveState& reactive,
    const Transform& post,
    const std::vector<VectorEffect>& vector_effects,
    double progress,
    double phase,
    bool allow_history,
    double crossfade_history,
    std::vector<std::uint8_t>& rgb,
    ResidentGpuTiming* timing
) {
    last_hardware_map_failed_ = false;
    if (timing) *timing = {};
    if (!available() || layers.empty()) return false;
#ifndef TUBEVIZ_HAVE_PLACEBO
    (void)composition_mode; (void)creative; (void)reactive; (void)post; (void)vector_effects;
    (void)progress; (void)phase; (void)allow_history; (void)crossfade_history; (void)rgb;
    return false;
#else
    const int count = std::min<int>(4, layers.size());
    std::array<pl_frame, 4> mapped{};
    std::array<bool, 4> is_mapped{};
    auto cleanup = [&]() {
        for (int i = 0; i < count; ++i) if (is_mapped[i]) pl_unmap_avframe(impl_->gpu, &mapped[i]);
    };

    auto map_start = Clock::now();
    for (int i = 0; i < count; ++i) {
        if (!layers[i].frame || !layers[i].transform) { cleanup(); return false; }
        if (hardware_frame(layers[i].frame) && timing) timing->hardware_input = true;
        pl_avframe_params params{};
        params.frame = const_cast<AVFrame*>(layers[i].frame);
        params.tex = impl_->mapped_tex[i];
        params.map_dovi = false;
        if (!pl_map_avframe_ex(impl_->gpu, &mapped[i], &params)) {
            if (hardware_frame(layers[i].frame)) last_hardware_map_failed_ = true;
            cleanup();
            return false;
        }
        is_mapped[i] = true;
        mapped[i].repr.alpha = PL_ALPHA_INDEPENDENT;
    }
    if (timing) timing->map_ms = elapsed_ms(map_start);

    auto compose_start = Clock::now();
    pl_frame target = texture_frame(impl_->compose, 4, impl_->width, impl_->height);
    const pl_hook* layer_hooks[] = {impl_->layer_hook};
    for (int i = 0; i < count; ++i) {
        const Transform& t = *layers[i].transform;
        set_param(impl_->layer_hook, "opacity", static_cast<float>(std::clamp(layers[i].opacity, 0.0, 1.0)));
        set_param(impl_->layer_hook, "mirror", t.mirror ? 1.0f : 0.0f);
        set_param(impl_->layer_hook, "zoom", static_cast<float>(std::max(.2, t.zoom)));
        set_param(impl_->layer_hook, "pan_x", static_cast<float>(t.pan_x));
        set_param(impl_->layer_hook, "pan_y", static_cast<float>(t.pan_y));
        set_param(impl_->layer_hook, "rotation", static_cast<float>(t.rotation_degrees * 3.14159265358979323846 / 180.0));
        set_param(impl_->layer_hook, "brightness", static_cast<float>(t.brightness));
        set_param(impl_->layer_hook, "contrast", static_cast<float>(t.contrast));
        set_param(impl_->layer_hook, "saturation", static_cast<float>(t.saturation));
        set_param(impl_->layer_hook, "grayscale", static_cast<float>(t.grayscale));
        set_param(impl_->layer_hook, "hue", static_cast<float>(std::clamp(t.hue_degrees, -12.0, 12.0) * 3.14159265358979323846 / 180.0));
        set_param(impl_->layer_hook, "scanlines", static_cast<float>(t.scanlines));
        set_param(impl_->layer_hook, "vignette", static_cast<float>(t.vignette));
        set_param(impl_->layer_hook, "noise", static_cast<float>(t.noise));
        set_param(impl_->layer_hook, "pixelate", static_cast<float>(t.pixelate));
        set_param(impl_->layer_hook, "rgb_split", static_cast<float>(t.rgb_split));
        set_param(impl_->layer_hook, "ripple", static_cast<float>(t.ripple));
        set_param(impl_->layer_hook, "vortex", static_cast<float>(t.vortex));
        set_param(impl_->layer_hook, "blur", static_cast<float>(t.blur_px));
        set_param(impl_->layer_hook, "comp_mode", static_cast<float>(composition_id(composition_mode)));
        set_param(impl_->layer_hook, "layer_index", static_cast<float>(i));
        set_param(impl_->layer_hook, "layer_count", static_cast<float>(count));
        set_param(impl_->layer_hook, "comp_progress", static_cast<float>(progress));
        set_param(impl_->layer_hook, "phase", static_cast<float>(phase));
        set_param(impl_->layer_hook, "blend_mode", static_cast<float>(blend_id(layers[i].blend_mode)));

        pl_render_params params = pl_render_fast_params;
        params.hooks = layer_hooks;
        params.num_hooks = 1;
        params.dynamic_constants = false;
        params.blend_params = i == 0 ? nullptr : &pl_alpha_overlay;
        preserve_target(params, i != 0);
        if (!pl_render_image(impl_->renderer, &mapped[i], &target, &params)) {
            cleanup();
            return false;
        }
    }
    cleanup();
    if (timing) timing->compose_ms = elapsed_ms(compose_start);

    auto effects_start = Clock::now();
    const double hero = hero_env(creative, progress);
    const double camera = creative.camera_energy * curve4(creative.camera_envelope, progress) + hero * .28;
    const double flow = (creative.flow_warp + creative.background_warp * .42) * curve4(creative.flow_warp_envelope, progress) + hero * .18;
    const double depth = creative.depth_parallax * curve4(creative.depth_envelope, progress) + hero * .20;
    const double symmetry = creative.local_symmetry * curve4(creative.symmetry_envelope, progress) + (creative.hero_kind == "time_prism" ? hero * .7 : 0.0);
    const double bloom = creative.texture_bloom * curve4(creative.bloom_envelope, progress) + reactive.bloom * .85;
    const double streaks = creative.texture_streaks * curve4(creative.streaks_envelope, progress);
    const double palette = creative.palette_strength * curve4(creative.palette_envelope, progress);

    int vid = 0;
    double vamount = 0.0, vopacity = 0.0;
    for (const auto& effect : vector_effects) {
        if (!effect.visible) continue;
        const int id = vector_id(effect.kind);
        if (!id) continue;
        const double q = std::clamp(progress * 3.0, 0.0, 3.0);
        const int a = std::min(2, static_cast<int>(q));
        const double f = q - a;
        const double sample = effect.amount_samples[a] * (1.0 - f) + effect.amount_samples[a + 1] * f;
        const double score = std::max(effect.amount, sample) * effect.opacity;
        if (score > vamount * vopacity) {
            vid = id; vamount = std::max(effect.amount, sample); vopacity = effect.opacity;
        }
    }

    set_param(impl_->final_hook, "camera", static_cast<float>(camera));
    set_param(impl_->final_hook, "flow", static_cast<float>(flow));
    set_param(impl_->final_hook, "depth", static_cast<float>(depth));
    set_param(impl_->final_hook, "symmetry", static_cast<float>(symmetry));
    set_param(impl_->final_hook, "bloom", static_cast<float>(bloom));
    set_param(impl_->final_hook, "streaks", static_cast<float>(streaks));
    set_param(impl_->final_hook, "palette", static_cast<float>(palette));
    set_param(impl_->final_hook, "target_x", static_cast<float>(creative.target_x));
    set_param(impl_->final_hook, "target_y", static_cast<float>(creative.target_y));
    set_param(impl_->final_hook, "drift_x", static_cast<float>(creative.drift_x));
    set_param(impl_->final_hook, "drift_y", static_cast<float>(creative.drift_y));
    set_param(impl_->final_hook, "progress", static_cast<float>(progress));
    set_param(impl_->final_hook, "phase", static_cast<float>(phase));
    set_param(impl_->final_hook, "hue", static_cast<float>(creative.color_hue_shift * 3.14159265358979323846 / 180.0));
    set_param(impl_->final_hook, "saturation", static_cast<float>(creative.color_saturation));
    set_param(impl_->final_hook, "contrast", static_cast<float>(creative.color_contrast));
    set_param(impl_->final_hook, "brightness", static_cast<float>(creative.color_brightness));
    set_param(impl_->final_hook, "palette_r", creative.palette_r / 255.0f);
    set_param(impl_->final_hook, "palette_g", creative.palette_g / 255.0f);
    set_param(impl_->final_hook, "palette_b", creative.palette_b / 255.0f);
    set_param(impl_->final_hook, "source_fidelity", static_cast<float>(creative.source_fidelity));
    set_param(impl_->final_hook, "beat", static_cast<float>(reactive.beat_amount()));
    set_param(impl_->final_hook, "beat_low", static_cast<float>(reactive.beat_low));
    set_param(impl_->final_hook, "beat_mid", static_cast<float>(reactive.beat_mid));
    set_param(impl_->final_hook, "beat_high", static_cast<float>(reactive.beat_high));
    set_param(impl_->final_hook, "beat_mode", static_cast<float>(reactive.beat_mode));
    set_param(impl_->final_hook, "beat_center_x", static_cast<float>(reactive.beat_center_x));
    set_param(impl_->final_hook, "beat_center_y", static_cast<float>(reactive.beat_center_y));
    set_param(impl_->final_hook, "beat_direction", static_cast<float>(reactive.beat_direction));
    set_param(impl_->final_hook, "beat_frequency", static_cast<float>(reactive.beat_frequency));
    set_param(impl_->final_hook, "ripple", static_cast<float>(post.ripple + reactive.ripple * .7 + reactive.tempo_warp * .55));
    set_param(impl_->final_hook, "vortex", static_cast<float>(post.vortex + reactive.vortex));
    set_param(impl_->final_hook, "glitch", static_cast<float>(post.glitch));
    set_param(impl_->final_hook, "kaleido", static_cast<float>(std::max(post.kaleidoscope, reactive.kaleidoscope)));
    set_param(impl_->final_hook, "tiles", static_cast<float>(post.tiles));
    set_param(impl_->final_hook, "tunnel", static_cast<float>(std::max(post.tunnel, reactive.tunnel)));
    set_param(impl_->final_hook, "posterize", static_cast<float>(post.posterize));
    set_param(impl_->final_hook, "edge", static_cast<float>(std::max(post.edge, reactive.edge)));
    set_param(impl_->final_hook, "strobe", static_cast<float>(std::max(post.strobe, reactive.strobe)));
    set_param(impl_->final_hook, "shutter", static_cast<float>(std::max(post.shutter, reactive.freeze)));
    set_param(impl_->final_hook, "slit", static_cast<float>(std::max(post.slit_scan, reactive.slit_scan)));
    set_param(impl_->final_hook, "corridor", static_cast<float>(std::max(post.mirror_corridor, reactive.corridor)));
    set_param(impl_->final_hook, "mask_wipe", static_cast<float>(std::max(post.mask_wipe, reactive.mask)));
    set_param(impl_->final_hook, "solarize", static_cast<float>(std::max(post.solarize, reactive.solarize)));
    set_param(impl_->final_hook, "block", static_cast<float>(post.block_displace));
    set_param(impl_->final_hook, "chroma", static_cast<float>(post.chroma_delay + reactive.chroma));
    set_param(impl_->final_hook, "vhs", static_cast<float>(post.vhs_tracking));
    set_param(impl_->final_hook, "slice", static_cast<float>(std::max(post.slice_recursion, reactive.slice_recursion)));
    set_param(impl_->final_hook, "pixelate", static_cast<float>(post.pixelate));
    set_param(impl_->final_hook, "rgb_split", static_cast<float>(post.rgb_split + creative.flow_rgb * curve4(creative.flow_rgb_envelope, progress)));
    set_param(impl_->final_hook, "vector_kind", static_cast<float>(vid));
    set_param(impl_->final_hook, "vector_amount", static_cast<float>(vamount));
    set_param(impl_->final_hook, "vector_opacity", static_cast<float>(vopacity));

    double history_mix = 0.0;
    if (allow_history && impl_->has_history) {
        history_mix = std::max({
            creative.temporal_echo * curve4(creative.temporal_echo_envelope, progress) * .34,
            creative.temporal_smear * curve4(creative.temporal_smear_envelope, progress) * .26,
            creative.feedback * curve4(creative.feedback_envelope, progress) * .30,
            creative.flow_trails * curve4(creative.flow_trails_envelope, progress) * .22,
            post.motion_trails * .34,
            post.frame_echo * .34,
            post.feedback * .30,
            post.datamosh * .42,
            reactive.echo * .32,
            reactive.motion_trails * .32,
            reactive.datamosh * .40
        });
    }
    history_mix = std::clamp(std::max(history_mix, crossfade_history), 0.0, 1.0);

    pl_frame compose_frame = texture_frame(impl_->compose, 4, impl_->width, impl_->height);
    pl_frame final_frame = texture_frame(impl_->final_tex, 4, impl_->width, impl_->height);
    if (history_mix > 1e-5 && impl_->has_history) {
        pl_frame hist_frame = texture_frame(impl_->history, 4, impl_->width, impl_->height);
        pl_render_params history_params = pl_render_fast_params;
        if (!pl_render_image(impl_->renderer, &hist_frame, &final_frame, &history_params)) return false;
    }

    set_param(impl_->final_hook, "out_alpha", static_cast<float>(1.0 - history_mix));
    const pl_hook* final_hooks[] = {impl_->final_hook};
    pl_render_params final_params = pl_render_fast_params;
    final_params.hooks = final_hooks;
    final_params.num_hooks = 1;
    final_params.dynamic_constants = false;
    if (history_mix > 1e-5 && impl_->has_history) {
        final_params.blend_params = &pl_alpha_overlay;
        preserve_target(final_params, true);
    }
    if (!pl_render_image(impl_->renderer, &compose_frame, &final_frame, &final_params)) return false;

    pl_frame output_frame = texture_frame(impl_->output, impl_->output_components, impl_->width, impl_->height);
    pl_render_params copy_params = pl_render_fast_params;
    if (!pl_render_image(impl_->renderer, &final_frame, &output_frame, &copy_params)) return false;

    pl_tex_blit_params blit{};
    blit.src = impl_->final_tex;
    blit.dst = impl_->history;
    blit.sample_mode = PL_TEX_SAMPLE_NEAREST;
    pl_tex_blit(impl_->gpu, &blit);
    impl_->has_history = true;
    if (timing) timing->effects_ms = elapsed_ms(effects_start);

    auto download_start = Clock::now();
    const std::size_t pixels = static_cast<std::size_t>(impl_->width) * impl_->height;
    rgb.resize(pixels * 3);
    void* ptr = rgb.data();
    std::size_t pitch = static_cast<std::size_t>(impl_->width) * 3;
    if (impl_->output_components == 4) {
        ptr = impl_->rgba_out.data();
        pitch = static_cast<std::size_t>(impl_->width) * 4;
    }
    pl_tex_transfer_params download{};
    download.tex = impl_->output;
    download.ptr = ptr;
    download.row_pitch = pitch;
#if defined(PL_API_VER) && PL_API_VER >= 360
    download.no_import = impl_->gpu->limits.host_ptr_slow;
#elif defined(PL_API_VER) && PL_API_VER >= 349
    download.no_import = false;
#endif
    if (!pl_tex_download(impl_->gpu, &download)) return false;
    if (impl_->output_components == 4) {
        for (std::size_t i = 0, p = 0; i < rgb.size(); i += 3, p += 4) {
            rgb[i] = impl_->rgba_out[p];
            rgb[i + 1] = impl_->rgba_out[p + 1];
            rgb[i + 2] = impl_->rgba_out[p + 2];
        }
    }
    if (timing) timing->download_ms = elapsed_ms(download_start);
    return true;
#endif
}

} // namespace tubeviz
