// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/gpu.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string_view>

#ifdef TUBEVIZ_HAVE_PLACEBO
#include <libplacebo/gpu.h>
#include <libplacebo/log.h>
#include <libplacebo/renderer.h>
#include <libplacebo/shaders/custom.h>
#include <libplacebo/vulkan.h>
#endif

namespace tubeviz {
namespace {

double curve4(const double (&v)[4], double p) {
    p = std::clamp(p, 0.0, 1.0);
    const double q = p * 3.0;
    const int i = std::min(2, static_cast<int>(q));
    const double f = q - i;
    return std::clamp(v[i] * (1.0 - f) + v[i + 1] * f, 0.0, 1.0);
}

double hero_env(const CreativeEffect& c, double p) {
    if (c.hero_kind.empty() || c.hero_amount <= 0.0 || p < c.hero_start || p > c.hero_end) return 0.0;
    const double q = (p - c.hero_start) / std::max(1e-6, c.hero_end - c.hero_start);
    auto smooth = [](double x) { x = std::clamp(x, 0.0, 1.0); return x * x * (3.0 - 2.0 * x); };
    return c.hero_amount * std::min(smooth(q / .16), smooth((1.0 - q) / .22));
}

#ifdef TUBEVIZ_HAVE_PLACEBO

// One libplacebo hook intentionally fuses the operations that were previously
// separate full-frame CPU passes. Parameters are DYNAMIC so changing them per
// frame does not force a new shader compilation.
constexpr std::string_view kShader = R"SHADER(
//!PARAM camera
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM flow
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM depth
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM symmetry
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM bloom
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM streaks
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
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
//!PARAM phase
//!TYPE DYNAMIC float
-0.0
//!PARAM progress
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM hue
//!TYPE DYNAMIC float
//!MINIMUM -0.5
//!MAXIMUM 0.5
0.0
//!PARAM saturation
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
1.0
//!PARAM contrast
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
1.0
//!PARAM brightness
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
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
//!PARAM beat_warp
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
//!PARAM ripple
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM chroma
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM vortex
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM reactive_bloom
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM harmonic
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.0
//!PARAM source_fidelity
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.9

//!HOOK MAIN
//!BIND HOOKED
//!DESC tubeviz fused creative GPU pass

vec3 tv_hue(vec3 c, float a) {
    float y = dot(c, vec3(0.299, 0.587, 0.114));
    float i = dot(c, vec3(0.596, -0.274, -0.322));
    float q = dot(c, vec3(0.211, -0.523, 0.312));
    float cs = cos(a), sn = sin(a);
    float ii = i*cs - q*sn, qq = i*sn + q*cs;
    return vec3(y + 0.956*ii + 0.621*qq,
                y - 0.272*ii - 0.647*qq,
                y - 1.106*ii + 1.703*qq);
}

vec4 hook() {
    vec2 p0 = HOOKED_pos;
    vec4 ref = HOOKED_tex(p0);
    vec2 uv = p0;
    vec2 center = vec2(target_x, target_y);

    // Virtual camera: coherent, cheap and borderless.
    float ease = 0.5 - 0.5*cos(3.14159265*progress);
    float zoom = 1.0 + camera*(0.012 + 0.045*ease) + beat_low*0.012;
    vec2 drift = vec2(sin(progress*5.0 + phase*.08)*drift_x*.010,
                      sin(progress*4.0 + phase*.07)*drift_y*.008) * camera;
    uv = center + (uv - center - drift) / max(zoom, 0.2);

    // Flow/harmonic warp. Unlike the old beat warp this has no radial/circle edge.
    // Reactive vortex is a subtle full-frame rotation around the semantic focal
    // point, not a circular mask/ring.
    float va = vortex * .018;
    if (abs(va) > .00001) {
        vec2 vv = uv - center;
        float vcs = cos(va), vsn = sin(va);
        uv = center + mat2(vcs, -vsn, vsn, vcs) * vv;
    }
    float wave = flow*.010 + ripple*.006 + harmonic*.005 + beat_warp*.004;
    uv.x += sin(uv.y*24.0 + phase*3.7 + uv.x*5.0) * wave;
    uv.y += cos(uv.x*19.0 - phase*3.1 + uv.y*4.0) * wave*.72;

    // Pseudo depth from source luminance + vertical perspective. Sampling the
    // unmodified reference keeps the field stable even under stronger effects.
    float rl = dot(ref.rgb, vec3(.2126,.7152,.0722));
    float d = clamp(.18 + .56*(1.0-p0.y) + .06*(1.0-rl), 0.0, 1.0) - .5;
    uv += vec2(drift_x*.018, drift_y*.014) * d * depth;

    // Rare local symmetry. It is intentionally gated by the planner and uses an
    // off-center target so it cannot devolve into a permanent centered portal.
    if (symmetry > .065) {
        vec2 dv = uv-center;
        float r = length(dv);
        float a = atan(dv.y,dv.x);
        float seg = 6.2831853 / 5.0;
        float folded = abs(mod(a + seg*.5, seg) - seg*.5);
        vec2 suv = center + r*vec2(cos(folded), sin(folded));
        uv = mix(uv, suv, clamp(symmetry*.55,0.0,.72));
    }

    vec4 c = HOOKED_tex(clamp(uv, vec2(0.001), vec2(0.999)));

    // True channel displacement, preserving source channel values rather than
    // hue-rotating copies into a magenta screen blend.
    float split = clamp(chroma*.006 + beat_high*.0035, 0.0, .018);
    if (split > .0001) {
        vec2 dir = normalize(vec2(.82 + .15*sin(phase), .34 + .18*cos(phase*.7)));
        c.r = HOOKED_tex(clamp(uv + dir*split, vec2(.001), vec2(.999))).r;
        c.b = HOOKED_tex(clamp(uv - dir*split, vec2(.001), vec2(.999))).b;
    }

    // Approximate source-derived bloom/streaks with a handful of samples in the
    // same dispatch instead of dedicated CPU scratch passes.
    float bamt = clamp(bloom*.18 + reactive_bloom*.20, 0.0, .34);
    float samt = clamp(streaks*.12 + beat_mid*.05, 0.0, .22);
    if (bamt+samt > .006) {
        vec2 px = HOOKED_pt;
        vec3 blur = HOOKED_tex(clamp(uv+vec2(px.x*3.0,0),vec2(.001),vec2(.999))).rgb
                  + HOOKED_tex(clamp(uv-vec2(px.x*3.0,0),vec2(.001),vec2(.999))).rgb
                  + HOOKED_tex(clamp(uv+vec2(0,px.y*3.0),vec2(.001),vec2(.999))).rgb
                  + HOOKED_tex(clamp(uv-vec2(0,px.y*3.0),vec2(.001),vec2(.999))).rgb;
        blur *= .25;
        vec3 streak = HOOKED_tex(clamp(uv+vec2(px.x*10.0,0),vec2(.001),vec2(.999))).rgb
                    + HOOKED_tex(clamp(uv-vec2(px.x*10.0,0),vec2(.001),vec2(.999))).rgb;
        streak *= .5;
        c.rgb = mix(c.rgb, max(c.rgb, blur), bamt);
        c.rgb = mix(c.rgb, max(c.rgb, streak), samt);
    }

    // Restrained directed grade.
    float y = dot(c.rgb, vec3(.2126,.7152,.0722));
    c.rgb = vec3(y) + (c.rgb-vec3(y))*saturation;
    c.rgb = tv_hue(c.rgb, hue);
    c.rgb = (c.rgb-vec3(.5))*contrast + vec3(.5);
    c.rgb *= brightness;
    c.rgb = mix(c.rgb, vec3(palette_r,palette_g,palette_b), clamp(palette*.12,0.0,.15));

    // Final chroma contract in the same shader. Preserve effect luminance but
    // pull I/Q toward the true source frame for ordinary shots.
    float yo = dot(c.rgb, vec3(.299,.587,.114));
    float io = dot(c.rgb, vec3(.596,-.274,-.322));
    float qo = dot(c.rgb, vec3(.211,-.523,.312));
    float ir = dot(ref.rgb, vec3(.596,-.274,-.322));
    float qr = dot(ref.rgb, vec3(.211,-.523,.312));
    float fa = clamp((source_fidelity-.55)/.45,0.0,1.0)*.78;
    float ii = mix(io,ir,fa), qq = mix(qo,qr,fa);
    c.rgb = vec3(yo + .956*ii + .621*qq,
                 yo - .272*ii - .647*qq,
                 yo - 1.106*ii + 1.703*qq);
    return clamp(c,0.0,1.0);
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

#endif

} // namespace

struct GpuPostProcessor::Impl {
    int width{0};
    int height{0};
#ifdef TUBEVIZ_HAVE_PLACEBO
    pl_log log{nullptr};
    pl_vulkan vk{nullptr};
    pl_gpu gpu{nullptr};
    pl_renderer renderer{nullptr};
    pl_tex input{nullptr};
    pl_tex output{nullptr};
    const pl_hook* hook{nullptr};
    int components{4};
    std::vector<std::uint8_t> rgb_out;
    std::vector<std::uint8_t> rgba_in;
    std::vector<std::uint8_t> rgba_out;
#endif
};

GpuPostProcessor::GpuPostProcessor(int width, int height, std::string mode)
    : impl_(std::make_unique<Impl>()) {
    impl_->width = width;
    impl_->height = height;
    if (mode == "off" || mode == "none" || mode == "cpu") return;
#ifdef TUBEVIZ_HAVE_PLACEBO
    // libplacebo's convenience *_params(...) macros expand to C compound
    // literals. They are valid in C but not in tubeviz's strict -std=c++20
    // build, so construct the public parameter structs directly. Vulkan NULL
    // parameters are explicitly documented to use pl_vulkan_default_params,
    // whose defaults already enable async transfer/compute with one queue.
    struct pl_log_params log_params{};
    log_params.log_cb = pl_log_simple;
    log_params.log_level = PL_LOG_WARN;
    impl_->log = pl_log_create(PL_API_VER, &log_params);
    impl_->vk = pl_vulkan_create(impl_->log, nullptr);
    if (!impl_->vk) {
        if (mode != "auto") std::cerr << "WARN\tGPU requested but Vulkan/libplacebo context creation failed\n";
        return;
    }
    impl_->gpu = impl_->vk->gpu;
    impl_->renderer = pl_renderer_create(impl_->log, impl_->gpu);
    if (!impl_->renderer) return;

    const auto caps = static_cast<pl_fmt_caps>(
        PL_FMT_CAP_SAMPLEABLE | PL_FMT_CAP_LINEAR | PL_FMT_CAP_RENDERABLE | PL_FMT_CAP_HOST_READABLE
    );
    // Prefer a native RGB8 render target so the existing RGB24 renderer buffer
    // can be uploaded/downloaded directly. Some Vulkan devices do not expose a
    // renderable 3-component UNORM format, so fall back to RGBA8 and use the
    // conversion staging buffers only on those devices.
    pl_fmt fmt = pl_find_fmt(impl_->gpu, PL_FMT_UNORM, 3, 8, 8, caps);
    if (fmt) {
        impl_->components = 3;
    } else {
        fmt = pl_find_fmt(impl_->gpu, PL_FMT_UNORM, 4, 8, 8, caps);
        if (!fmt) fmt = pl_find_named_fmt(impl_->gpu, "rgba8");
        if (!fmt) return;
        impl_->components = 4;
    }

    pl_tex_params in{};
    in.w = width; in.h = height; in.format = fmt;
    in.sampleable = true; in.host_writable = true;
    pl_tex_params out{};
    out.w = width; out.h = height; out.format = fmt;
    out.renderable = true; out.host_readable = true; out.storable = (fmt->caps & PL_FMT_CAP_STORABLE) != 0;
    if (!pl_tex_recreate(impl_->gpu, &impl_->input, &in) ||
        !pl_tex_recreate(impl_->gpu, &impl_->output, &out)) return;

    impl_->hook = pl_mpv_user_shader_parse(impl_->gpu, kShader.data(), kShader.size());
    if (!impl_->hook) return;
    if (impl_->components == 3) {
        // Keep a dedicated download buffer so a failed GPU transfer cannot
        // partially overwrite the CPU frame that the renderer needs for its
        // automatic fallback path.  On success we swap buffers, avoiding a
        // second 1080p RGB24 copy.
        impl_->rgb_out.resize(static_cast<std::size_t>(width) * height * 3);
    } else {
        impl_->rgba_in.resize(static_cast<std::size_t>(width) * height * 4);
        impl_->rgba_out.resize(static_cast<std::size_t>(width) * height * 4);
    }
    backend_ = "vulkan/libplacebo";
#else
    (void)mode;
#endif
}

GpuPostProcessor::~GpuPostProcessor() {
#ifdef TUBEVIZ_HAVE_PLACEBO
    if (impl_) {
        if (impl_->hook) pl_mpv_user_shader_destroy(&impl_->hook);
        if (impl_->gpu) {
            pl_tex_destroy(impl_->gpu, &impl_->input);
            pl_tex_destroy(impl_->gpu, &impl_->output);
        }
        if (impl_->renderer) pl_renderer_destroy(&impl_->renderer);
        if (impl_->vk) pl_vulkan_destroy(&impl_->vk);
        if (impl_->log) pl_log_destroy(&impl_->log);
    }
#endif
}

bool GpuPostProcessor::available() const noexcept { return backend_ != "off"; }
const std::string& GpuPostProcessor::backend() const noexcept { return backend_; }

bool GpuPostProcessor::apply_spatial(
    std::vector<std::uint8_t>& rgb,
    const CreativeEffect& c,
    const ReactiveState& r,
    double progress,
    double phase
) {
#ifdef TUBEVIZ_HAVE_PLACEBO
    if (!available() || rgb.size() != static_cast<std::size_t>(impl_->width) * impl_->height * 3) return false;

    const double hero = hero_env(c, progress);
    const double camera = c.camera_energy * curve4(c.camera_envelope, progress);
    const double flow = c.flow_warp * curve4(c.flow_warp_envelope, progress) + .24*hero*(c.hero_kind=="time_prism");
    const double depth = std::max(c.depth_parallax * curve4(c.depth_envelope, progress),
                                  c.background_warp * curve4(c.background_envelope, progress) * .55)
                       + .92*hero*(c.hero_kind=="depth_burst");
    const double symmetry = c.local_symmetry * curve4(c.symmetry_envelope, progress)
                          + .78*hero*(c.hero_kind=="recursive_portal");
    const double bloom = c.texture_bloom * curve4(c.bloom_envelope, progress)
                       + .42*hero*(c.hero_kind=="recursive_portal");
    const double streaks = c.texture_streaks * curve4(c.streaks_envelope, progress)
                         + .26*hero*(c.hero_kind=="recursive_portal");
    const double palette = c.palette_strength * curve4(c.palette_envelope, progress);
    const double fidelity = std::clamp(c.source_fidelity - .16*hero, .58, 1.0);

    set_param(impl_->hook, "camera", static_cast<float>(camera));
    set_param(impl_->hook, "flow", static_cast<float>(flow));
    set_param(impl_->hook, "depth", static_cast<float>(depth));
    set_param(impl_->hook, "symmetry", static_cast<float>(symmetry));
    set_param(impl_->hook, "bloom", static_cast<float>(bloom));
    set_param(impl_->hook, "streaks", static_cast<float>(streaks));
    set_param(impl_->hook, "palette", static_cast<float>(palette));
    set_param(impl_->hook, "target_x", static_cast<float>(c.target_x));
    set_param(impl_->hook, "target_y", static_cast<float>(c.target_y));
    set_param(impl_->hook, "drift_x", static_cast<float>(c.drift_x));
    set_param(impl_->hook, "drift_y", static_cast<float>(c.drift_y));
    set_param(impl_->hook, "phase", static_cast<float>(phase));
    set_param(impl_->hook, "progress", static_cast<float>(progress));
    set_param(impl_->hook, "hue", static_cast<float>(std::clamp(c.color_hue_shift, -14.0, 14.0) * 3.14159265358979323846 / 180.0));
    set_param(impl_->hook, "saturation", static_cast<float>(std::clamp(c.color_saturation, .65, 1.35)));
    set_param(impl_->hook, "contrast", static_cast<float>(std::clamp(c.color_contrast, .75, 1.35)));
    set_param(impl_->hook, "brightness", static_cast<float>(std::clamp(c.color_brightness, .72, 1.28)));
    set_param(impl_->hook, "palette_r", c.palette_r / 255.0f);
    set_param(impl_->hook, "palette_g", c.palette_g / 255.0f);
    set_param(impl_->hook, "palette_b", c.palette_b / 255.0f);
    set_param(impl_->hook, "beat_warp", static_cast<float>(r.beat_warp));
    set_param(impl_->hook, "beat_low", static_cast<float>(r.beat_low));
    set_param(impl_->hook, "beat_mid", static_cast<float>(r.beat_mid));
    set_param(impl_->hook, "beat_high", static_cast<float>(r.beat_high));
    set_param(impl_->hook, "ripple", static_cast<float>(r.ripple));
    set_param(impl_->hook, "chroma", static_cast<float>(r.chroma));
    set_param(impl_->hook, "vortex", static_cast<float>(r.vortex));
    set_param(impl_->hook, "reactive_bloom", static_cast<float>(r.bloom));
    set_param(impl_->hook, "harmonic", static_cast<float>(r.harmonic));
    set_param(impl_->hook, "source_fidelity", static_cast<float>(fidelity));

    void* upload_ptr = rgb.data();
    std::size_t upload_pitch = static_cast<std::size_t>(impl_->width) * 3;
    if (impl_->components == 4) {
        for (std::size_t i = 0, p = 0; i < rgb.size(); i += 3, p += 4) {
            impl_->rgba_in[p] = rgb[i];
            impl_->rgba_in[p+1] = rgb[i+1];
            impl_->rgba_in[p+2] = rgb[i+2];
            impl_->rgba_in[p+3] = 255;
        }
        upload_ptr = impl_->rgba_in.data();
        upload_pitch = static_cast<std::size_t>(impl_->width) * 4;
    }
    pl_tex_transfer_params upload{};
    upload.tex = impl_->input; upload.ptr = upload_ptr; upload.row_pitch = upload_pitch;
    upload.no_import = impl_->gpu->limits.host_ptr_slow;
    auto disable_gpu = [&](const char* stage) {
        std::cerr << "WARN\tGPU post-processing failed at " << stage
                  << "; disabling Vulkan/libplacebo for the remainder of this render\n";
        backend_ = "off";
        return false;
    };
    if (!pl_tex_upload(impl_->gpu, &upload)) return disable_gpu("texture upload");

    pl_frame src{};
    src.num_planes = 1;
    src.planes[0].texture = impl_->input;
    src.planes[0].components = impl_->components;
    src.planes[0].component_mapping[0] = 0; src.planes[0].component_mapping[1] = 1;
    src.planes[0].component_mapping[2] = 2;
    if (impl_->components == 4) src.planes[0].component_mapping[3] = 3;
    src.crop = {0.0f, 0.0f, static_cast<float>(impl_->width), static_cast<float>(impl_->height)};

    pl_frame dst{};
    dst.num_planes = 1;
    dst.planes[0].texture = impl_->output;
    dst.planes[0].components = impl_->components;
    dst.planes[0].component_mapping[0] = 0; dst.planes[0].component_mapping[1] = 1;
    dst.planes[0].component_mapping[2] = 2;
    if (impl_->components == 4) dst.planes[0].component_mapping[3] = 3;
    dst.crop = src.crop;

    const pl_hook* hooks[] = {impl_->hook};
    pl_render_params params = pl_render_fast_params;
    params.hooks = hooks;
    params.num_hooks = 1;
    // Hook parameters are explicitly declared DYNAMIC in the shader. Keep
    // libplacebo's global dynamic-constant mode disabled; enabling it prevents
    // otherwise useful specialization and is documented as a performance cost.
    params.dynamic_constants = false;
    if (!pl_render_image(impl_->renderer, &src, &dst, &params)) return disable_gpu("shader/render");

    void* download_ptr = impl_->rgb_out.data();
    std::size_t download_pitch = static_cast<std::size_t>(impl_->width) * 3;
    if (impl_->components == 4) {
        download_ptr = impl_->rgba_out.data();
        download_pitch = static_cast<std::size_t>(impl_->width) * 4;
    }
    pl_tex_transfer_params download{};
    download.tex = impl_->output; download.ptr = download_ptr; download.row_pitch = download_pitch;
    download.no_import = impl_->gpu->limits.host_ptr_slow;
    if (!pl_tex_download(impl_->gpu, &download)) return disable_gpu("texture download");
    if (impl_->components == 4) {
        for (std::size_t i = 0, p = 0; i < rgb.size(); i += 3, p += 4) {
            rgb[i] = impl_->rgba_out[p];
            rgb[i+1] = impl_->rgba_out[p+1];
            rgb[i+2] = impl_->rgba_out[p+2];
        }
    } else {
        rgb.swap(impl_->rgb_out);
    }
    return true;
#else
    (void)rgb; (void)c; (void)r; (void)progress; (void)phase;
    return false;
#endif
}

} // namespace tubeviz
