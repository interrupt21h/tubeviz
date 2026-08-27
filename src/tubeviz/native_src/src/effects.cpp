// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/effects.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>

#ifdef TUBEVIZ_HAVE_OPENMP
#include <omp.h>
#endif

namespace tubeviz {
namespace {

inline std::uint8_t clamp8(double value) {
    return static_cast<std::uint8_t>(std::clamp(value, 0.0, 255.0));
}

inline double decay_for(double base, double fps) {
    return std::pow(base, 60.0 / std::max(1.0, fps));
}

inline double hash_noise(std::uint64_t x) {
    x ^= x >> 33;
    x *= 0xff51afd7ed558ccdULL;
    x ^= x >> 33;
    x *= 0xc4ceb9fe1a85ec53ULL;
    x ^= x >> 33;
    return (static_cast<double>(x & 0xffffu) / 32767.5) - 1.0;
}

} // namespace

void ReactiveState::decay(double fps) {
    beat_elapsed += 1.0 / std::max(1.0, fps);
    ripple *= decay_for(0.90, fps);
    chroma *= decay_for(0.90, fps);
    vortex *= decay_for(0.91, fps);
    bloom *= decay_for(0.92, fps);
    harmonic *= decay_for(0.94, fps);
    tempo_warp *= decay_for(0.93, fps); punch *= decay_for(0.82, fps);
    strobe *= decay_for(0.78, fps); tunnel *= decay_for(0.91, fps); kaleidoscope *= decay_for(0.90, fps);
    edge *= decay_for(0.88, fps); slit_scan *= decay_for(0.90, fps); echo *= decay_for(0.91, fps);
    corridor *= decay_for(0.91, fps); mask *= decay_for(0.90, fps); solarize *= decay_for(0.86, fps);
    datamosh *= decay_for(0.89, fps); motion_trails *= decay_for(0.91, fps); slice_recursion *= decay_for(0.89, fps);
    freeze *= decay_for(0.72, fps); switcher *= decay_for(0.70, fps);
}

void ReactiveState::apply(const Cue& cue) {
    if (cue.action == "beat_warp" || cue.action == "video_edit_beat_warp") {
        // A beat is an event, not another contribution to one permanently
        // decaying scalar. Retrigger the local envelope and replace the spatial
        // descriptor so successive hits can change topology.
        beat_warp = std::clamp(cue.amount, 0.0, 1.0);
        beat_low = std::clamp(cue.low, 0.0, 1.0);
        beat_mid = std::clamp(cue.mid, 0.0, 1.0);
        beat_high = std::clamp(cue.high, 0.0, 1.0);
        beat_mode = std::clamp(cue.warp_mode, 0, 7);
        beat_variant = std::max(0, cue.warp_variant);
        beat_center_x = std::clamp(cue.center_x, 0.08, 0.92);
        beat_center_y = std::clamp(cue.center_y, 0.08, 0.92);
        beat_direction = cue.direction;
        beat_frequency = std::clamp(cue.frequency, 0.5, 3.0);
        beat_polarity = cue.polarity >= 0.0 ? 1.0 : -1.0;
        beat_duration = std::clamp(cue.duration, 0.04, 0.60);
        beat_attack = std::clamp(cue.attack, 0.02, 0.20);
        beat_overshoot = std::clamp(cue.overshoot, 0.0, 0.40);
        beat_elapsed = 0.0;
    } else if (cue.action == "video_edit_ripple") {
        ripple = std::max(ripple, cue.amount);
    } else if (cue.action == "video_edit_chroma_delay") {
        chroma = std::max(chroma, cue.amount);
    } else if (cue.action == "video_edit_vortex") {
        vortex = std::max(vortex, cue.amount);
    } else if (cue.action == "energy_bloom") {
        bloom = std::max(bloom, cue.amount);
    } else if (cue.action == "harmonic_warp") {
        harmonic = std::max(harmonic, cue.amount);
    } else if (cue.action == "video_edit_tempo_warp" || cue.action == "tempo_shift") {
        tempo_warp = std::max(tempo_warp, cue.amount);
    } else if (cue.action == "video_edit_punch") punch = std::max(punch, cue.amount);
    else if (cue.action == "video_edit_strobe") strobe = std::max(strobe, cue.amount);
    else if (cue.action == "video_edit_tunnel") tunnel = std::max(tunnel, cue.amount);
    else if (cue.action == "video_edit_kaleidoscope") kaleidoscope = std::max(kaleidoscope, cue.amount);
    else if (cue.action == "video_edit_edge") edge = std::max(edge, cue.amount);
    else if (cue.action == "video_edit_slitscan") slit_scan = std::max(slit_scan, cue.amount);
    else if (cue.action == "video_edit_echo") echo = std::max(echo, cue.amount);
    else if (cue.action == "video_edit_corridor") corridor = std::max(corridor, cue.amount);
    else if (cue.action == "video_edit_mask") mask = std::max(mask, cue.amount);
    else if (cue.action == "video_edit_solarize") solarize = std::max(solarize, cue.amount);
    else if (cue.action == "video_edit_datamosh") datamosh = std::max(datamosh, cue.amount);
    else if (cue.action == "video_edit_motion_trails") motion_trails = std::max(motion_trails, cue.amount);
    else if (cue.action == "video_edit_slice_recursion" || cue.action == "video_edit_slice") slice_recursion = std::max(slice_recursion, cue.amount);
    else if (cue.action == "video_edit_freeze") freeze = std::max(freeze, cue.amount > 0.0 ? cue.amount : 0.65);
    else if (cue.action == "video_edit_switch") switcher = std::max(switcher, cue.amount > 0.0 ? cue.amount : 0.65);
}

double ReactiveState::beat_phase() const {
    if (beat_duration <= 1e-6) return 1.0;
    return std::clamp(beat_elapsed / beat_duration, 0.0, 1.0);
}

double ReactiveState::beat_envelope() const {
    if (beat_warp <= 1e-6 || beat_elapsed < 0.0 || beat_elapsed > beat_duration * 1.15) return 0.0;
    const double q = beat_phase();
    if (q < beat_attack) {
        const double x = q / std::max(1e-6, beat_attack);
        return x * x * (3.0 - 2.0 * x);
    }
    const double x = (q - beat_attack) / std::max(1e-6, 1.0 - beat_attack);
    const double rebound = 1.0 + beat_overshoot * std::sin(x * 6.28318530717958647692) * std::exp(-2.2 * x);
    return std::max(0.0, std::exp(-3.35 * x) * rebound);
}

double ReactiveState::beat_amount() const {
    return std::clamp(beat_warp * beat_envelope(), 0.0, 1.0);
}

void apply_transform(
    std::vector<std::uint8_t>& rgb,
    int width,
    int height,
    const Transform& t,
    std::uint64_t frame_index
) {
    if (rgb.empty()) return;
    // Fuse shot-local color, noise, scanlines and vignette into one traversal.
    // At 1080p this removes up to two additional ~6 MiB read/write passes per
    // source layer compared with the original Phase-1 implementation.
    const double hue_degrees = std::clamp(t.hue_degrees, -6.0, 6.0);
    const bool color = std::abs(t.brightness - 1.0) > 1e-4 ||
                       std::abs(t.contrast - 1.0) > 1e-4 ||
                       std::abs(t.saturation - 1.0) > 1e-4 ||
                       std::abs(hue_degrees) > 1e-4 ||
                       t.grayscale > 1e-4 || t.noise > 1e-4;
    const bool scanlines = t.scanlines > 1e-4;
    const bool vignette = t.vignette > 1e-4;
    if (color || scanlines || vignette) {
        const double gray = std::clamp(t.grayscale, 0.0, 1.0);
        const double noise_amount = 28.0 * std::clamp(t.noise, 0.0, 1.0);
        const double hue = hue_degrees * 3.14159265358979323846 / 180.0;
        const double hc = std::cos(hue), hs = std::sin(hue);
        const double scan_gain = 1.0 - 0.32 * std::clamp(t.scanlines, 0.0, 1.0);
        const double vignette_amount = std::clamp(t.vignette, 0.0, 1.0);
        const double cx = (width - 1) * 0.5, cy = (height - 1) * 0.5;
        const double inv_r2 = 1.0 / std::max(1.0, cx * cx + cy * cy);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            std::size_t i = static_cast<std::size_t>(y) * width * 3;
            const double scan = scanlines && (y & 1) ? scan_gain : 1.0;
            for (int x = 0; x < width; ++x, i += 3) {
                double r = rgb[i], g = rgb[i + 1], b = rgb[i + 2];
                if (color) {
                    const double luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
                    r = luma + (r - luma) * t.saturation;
                    g = luma + (g - luma) * t.saturation;
                    b = luma + (b - luma) * t.saturation;
                    if (std::abs(hue_degrees) > 1e-4) {
                        const double yiq_y = 0.299*r + 0.587*g + 0.114*b;
                        const double ii = 0.596*r - 0.274*g - 0.322*b;
                        const double qq = 0.211*r - 0.523*g + 0.312*b;
                        const double ir = ii*hc - qq*hs;
                        const double qr = ii*hs + qq*hc;
                        r = yiq_y + 0.956*ir + 0.621*qr;
                        g = yiq_y - 0.272*ir - 0.647*qr;
                        b = yiq_y - 1.106*ir + 1.703*qr;
                    }
                    r = r * (1.0 - gray) + luma * gray;
                    g = g * (1.0 - gray) + luma * gray;
                    b = b * (1.0 - gray) + luma * gray;
                    r = (r - 127.5) * t.contrast + 127.5;
                    g = (g - 127.5) * t.contrast + 127.5;
                    b = (b - 127.5) * t.contrast + 127.5;
                    r *= t.brightness; g *= t.brightness; b *= t.brightness;
                    if (noise_amount > 1e-4) {
                        const std::uint64_t key =
                            frame_index * 0x9e3779b97f4a7c15ULL +
                            static_cast<std::uint64_t>(y) * width +
                            static_cast<std::uint64_t>(x);
                        const double n = hash_noise(key) * noise_amount;
                        r += n; g += n; b += n;
                    }
                }
                double gain = scan;
                if (vignette) {
                    const double dx = x - cx, dy = y - cy;
                    const double r2 = std::min(1.0, (dx * dx + dy * dy) * inv_r2);
                    const double shaped = r2 * (0.68 + 0.32 * r2);
                    gain *= 1.0 - vignette_amount * 0.58 * shaped;
                }
                rgb[i] = clamp8(r * gain);
                rgb[i + 1] = clamp8(g * gain);
                rgb[i + 2] = clamp8(b * gain);
            }
        }
    }

    // Match browser shot-local geometry before mirror.  The old native path
    // serialized none of these fields, so native output could look noticeably
    // flatter even when the timeline contained push/pan/rotation choreography.
    const bool geometry = std::abs(t.zoom - 1.0) > 1e-4 || std::abs(t.pan_x) > 1e-4 ||
                          std::abs(t.pan_y) > 1e-4 || std::abs(t.rotation_degrees) > 1e-4;
    if (geometry) {
        const auto src = rgb;
        const double zoom = std::max(0.25, t.zoom);
        const double angle = -t.rotation_degrees * 3.14159265358979323846 / 180.0;
        const double ca = std::cos(angle), sa = std::sin(angle);
        const double cx = (width - 1) * 0.5, cy = (height - 1) * 0.5;
        const double px = t.pan_x * width, py = t.pan_y * height;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const double dx = (x - cx - px) / zoom;
                const double dy = (y - cy - py) / zoom;
                const int sx = std::clamp(static_cast<int>(std::lround(cx + dx * ca - dy * sa)), 0, width - 1);
                const int sy = std::clamp(static_cast<int>(std::lround(cy + dx * sa + dy * ca)), 0, height - 1);
                const auto di = static_cast<std::size_t>((y * width + x) * 3);
                const auto si = static_cast<std::size_t>((sy * width + sx) * 3);
                rgb[di] = src[si]; rgb[di+1] = src[si+1]; rgb[di+2] = src[si+2];
            }
        }
    }

    if (t.blur_px > 0.35) {
        const auto src = rgb;
        const int radius = std::clamp(static_cast<int>(std::lround(t.blur_px)), 1, 3);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
            int sum[3]{0,0,0}, count = 0;
            for (int yy = std::max(0, y-radius); yy <= std::min(height-1, y+radius); ++yy)
                for (int xx = std::max(0, x-radius); xx <= std::min(width-1, x+radius); ++xx) {
                    const auto si = static_cast<std::size_t>((yy*width+xx)*3);
                    sum[0]+=src[si]; sum[1]+=src[si+1]; sum[2]+=src[si+2]; ++count;
                }
            const auto di = static_cast<std::size_t>((y*width+x)*3);
            rgb[di]=static_cast<std::uint8_t>(sum[0]/count);
            rgb[di+1]=static_cast<std::uint8_t>(sum[1]/count);
            rgb[di+2]=static_cast<std::uint8_t>(sum[2]/count);
        }
    }

    if (t.mirror) {
        const int stride = width * 3;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            auto* row = rgb.data() + static_cast<std::size_t>(y) * stride;
            for (int x = 0; x < width / 2; ++x) {
                const int a = x * 3;
                const int b = (width - 1 - x) * 3;
                std::swap(row[a], row[b]);
                std::swap(row[a + 1], row[b + 1]);
                std::swap(row[a + 2], row[b + 2]);
            }
        }
    }
}

void apply_reactive_effects(
    std::vector<std::uint8_t>& rgb,
    int width,
    int height,
    const ReactiveState& state,
    double phase
) {
    if (rgb.empty()) return;
    const double beat = state.beat_amount();
    const double beat_phase = state.beat_phase();
    const double ripple = std::clamp(state.ripple + beat * state.beat_mid * 0.22, 0.0, 1.0);
    const double vortex = std::clamp(state.vortex, 0.0, 1.0);
    if (beat > 0.015 || ripple > 0.015 || vortex > 0.015) {
        const auto src = rgb;
        const double cx = std::clamp(state.beat_center_x, 0.08, 0.92);
        const double cy = std::clamp(state.beat_center_y, 0.08, 0.92);
        const double direction = state.beat_direction;
        const double dir_x = std::cos(direction), dir_y = std::sin(direction);
        const double nrm_x = -dir_y, nrm_y = dir_x;
        const double frequency = std::clamp(state.beat_frequency, 0.5, 3.0);
        const double polarity = state.beat_polarity >= 0.0 ? 1.0 : -1.0;
        const double spectral = 0.72 + 0.20 * state.beat_low + 0.13 * state.beat_mid + 0.08 * state.beat_high;
        const double amount = beat * spectral;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                double u = static_cast<double>(x) / std::max(1, width - 1);
                double v = static_cast<double>(y) / std::max(1, height - 1);
                double px = u - cx, py = v - cy;
                const double radius = std::sqrt(px * px + py * py);
                auto smooth = [](double a, double b, double value) {
                    const double q = std::clamp((value - a) / std::max(1e-9, b - a), 0.0, 1.0);
                    return q * q * (3.0 - 2.0 * q);
                };
                if (amount > 1e-6) {
                    switch (state.beat_mode) {
                        case 0: {
                            const double gain = amount * .070 * polarity * (.72 + .28 * (1.0 - smooth(.15, .82, radius)));
                            u -= px * gain; v -= py * gain; break;
                        }
                        case 1: {
                            const double gain = amount * .060 * polarity * (.72 + .28 * (1.0 - smooth(.12, .86, radius)));
                            u += px * gain; v += py * gain; break;
                        }
                        case 2: {
                            const double osc = std::sin((px * nrm_x + py * nrm_y) * 28.0 * frequency + beat_phase * 10.0 + state.beat_variant * .57);
                            const double disp = osc * amount * .035 * polarity * (.65 + .35 * state.beat_mid);
                            u += dir_x * disp; v += dir_y * disp; break;
                        }
                        case 3: {
                            const double angle = amount * .20 * polarity * (1.0 - smooth(.10, .78, radius)) * (.65 + .35 * std::sin(beat_phase * 3.141592653589793));
                            const double cs = std::cos(angle), sn = std::sin(angle);
                            u = cx + cs * px - sn * py; v = cy + sn * px + cs * py; break;
                        }
                        case 4: {
                            const double osc = std::sin((px * nrm_x + py * nrm_y) * 24.0 * frequency + beat_phase * 12.0 + state.beat_variant * .83);
                            const double osc2 = std::cos((px * dir_x + py * dir_y) * 17.0 * frequency - beat_phase * 8.0);
                            u += dir_x * osc * amount * .027 * polarity + nrm_x * osc2 * amount * .011;
                            v += dir_y * osc * amount * .027 * polarity + nrm_y * osc2 * amount * .011;
                            break;
                        }
                        case 5: {
                            u += px * py * amount * .34 * polarity;
                            v += (px * px - py * py) * .58 * amount * .34 * polarity;
                            break;
                        }
                        case 6: {
                            const double lens = 1.0 - smooth(.04, .72, radius);
                            u -= px * amount * .095 * polarity * lens;
                            v -= py * amount * .095 * polarity * lens;
                            break;
                        }
                        default: {
                            double angle = amount * .24 * polarity * (1.0 - smooth(.05, .88, radius));
                            angle += std::sin(radius * 34.0 * frequency - beat_phase * 11.0 + state.beat_variant) * amount * .035;
                            const double cs = std::cos(angle), sn = std::sin(angle);
                            u = cx + cs * px - sn * py; v = cy + sn * px + cs * py; break;
                        }
                    }
                }
                if (vortex > .015) {
                    px = u - cx; py = v - cy;
                    const double angle = vortex * .018;
                    const double cs = std::cos(angle), sn = std::sin(angle);
                    u = cx + cs * px - sn * py; v = cy + sn * px + cs * py;
                }
                if (ripple > .015) {
                    u += std::sin(v * 24.0 + phase * 3.7 + u * 5.0) * ripple * .006;
                    v += std::cos(u * 19.0 - phase * 3.1 + v * 4.0) * ripple * .0043;
                }
                u = std::clamp(u, 0.0, 1.0); v = std::clamp(v, 0.0, 1.0);
                const int ix = std::clamp(static_cast<int>(u * (width - 1) + 0.5), 0, width - 1);
                const int iy = std::clamp(static_cast<int>(v * (height - 1) + 0.5), 0, height - 1);
                const auto di = static_cast<std::size_t>((y * width + x) * 3);
                const auto si = static_cast<std::size_t>((iy * width + ix) * 3);
                rgb[di] = src[si]; rgb[di + 1] = src[si + 1]; rgb[di + 2] = src[si + 2];
            }
        }
    }

    const double chroma = std::clamp(
        state.chroma + beat * state.beat_high * 0.55, 0.0, 1.0
    );
    if (chroma > 0.015) {
        const auto src = rgb;
        const int offset = std::max(
            1, static_cast<int>(width * 0.012 * chroma + 0.5)
        );
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const auto i = static_cast<std::size_t>((y * width + x) * 3);
                const int xr = std::min(width - 1, x + offset);
                const int xb = std::max(0, x - offset);
                rgb[i] = src[static_cast<std::size_t>((y * width + xr) * 3)];
                rgb[i + 2] =
                    src[static_cast<std::size_t>((y * width + xb) * 3 + 2)];
            }
        }
    }

    if (state.bloom > 0.02 || state.harmonic > 0.02) {
        const double gain =
            1.0 + 0.24 * std::clamp(state.bloom, 0.0, 1.0)
            + 0.10 * state.harmonic;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (std::int64_t i = 0; i < static_cast<std::int64_t>(rgb.size()); ++i) {
            rgb[static_cast<std::size_t>(i)] =
                clamp8(rgb[static_cast<std::size_t>(i)] * gain);
        }
    }
}


void apply_post_transform_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const Transform& t,
    double progress,
    double phase
) {
    if (rgb.empty() || width <= 0 || height <= 0) return;
    auto amount = [](double v) { return std::clamp(v, 0.0, 1.0); };
    const double ripple = amount(t.ripple), vortex = amount(t.vortex), tunnel = amount(t.tunnel);
    const double kaleido = amount(t.kaleidoscope), tiles = amount(t.tiles), corridor = amount(t.mirror_corridor);
    const double glitch = amount(t.glitch), block = amount(t.block_displace), vhs = amount(t.vhs_tracking);
    const double recursion = amount(t.slice_recursion), pix = amount(t.pixelate);
    const double split = amount(std::max(t.rgb_split, t.chroma_delay));
    const bool spatial = ripple>.01 || vortex>.01 || tunnel>.01 || kaleido>.01 || tiles>.01 || corridor>.01 ||
                         glitch>.01 || block>.01 || vhs>.01 || recursion>.01 || pix>.01 || split>.01;
    if (spatial) {
        const auto src = rgb;
        const double cx=(width-1)*.5, cy=(height-1)*.5;
        const int block_h=std::max(8, height/18), block_w=std::max(12, width/16);
        const int pxstep = pix>.01 ? std::max(1, static_cast<int>(1 + pix*24)) : 1;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for(int y=0;y<height;++y) for(int x=0;x<width;++x){
            double sx=x, sy=y;
            double nx=(x-cx)/std::max(1.0,cx), ny=(y-cy)/std::max(1.0,cy);
            double r=std::hypot(nx,ny), a=std::atan2(ny,nx);
            if(vortex>.01){ const double q=vortex*.42*(1.0-std::min(1.0,r)); a-=q; sx=cx+std::cos(a)*r*cx; sy=cy+std::sin(a)*r*cy; }
            if(tunnel>.01){ const double z=1.0 + tunnel*.16*std::sin(phase*2.1+r*12.0); sx=cx+(sx-cx)/z; sy=cy+(sy-cy)/z; }
            if(ripple>.01){ sx += std::sin((sy/height)*26.0+phase*3.4)*width*.010*ripple; sy += std::cos((sx/width)*21.0-phase*2.9)*height*.007*ripple; }
            if(kaleido>.01){
                const int seg=3+static_cast<int>(kaleido*7.0); const double sector=6.28318530717958647692/seg;
                double aa=std::fmod(a+6.28318530717958647692,sector); if(aa>sector*.5) aa=sector-aa;
                const double rr=r*(.96+.04*std::sin(phase)); sx=cx+std::cos(aa)*rr*cx; sy=cy+std::sin(aa)*rr*cy;
            }
            if(tiles>.01){
                // Legacy "tiles" are organic local lenses rather than boxed copies.
                const double gx=std::fmod((sx/width)*3.0+3.0,1.0)-.5, gy=std::fmod((sy/height)*2.0+2.0,1.0)-.5;
                const double rr=std::hypot(gx,gy), lens=std::max(0.0,1.0-rr*2.0)*tiles;
                sx += gx*width*.075*lens; sy += gy*height*.075*lens;
            }
            if(corridor>.01){ const double span=std::max(24.0,width*(.28-.12*corridor)); double q=std::fmod(sx+phase*width*.03,span*2.0); if(q>span)q=2*span-q; sx=q/span*(width-1); }
            if(glitch>.01){ const int band=y/block_h; if(((band*37+static_cast<int>(phase*19))%7)<3) sx += std::sin(band*4.7+phase*9.0)*width*.055*glitch; }
            if(block>.01){ const int bx=x/block_w, by=y/block_h; const double h=hash_noise(static_cast<std::uint64_t>(bx*131+by*977+static_cast<int>(phase*17))); sx += h*width*.08*block; sy += hash_noise(static_cast<std::uint64_t>(bx*733+by*199+3))*height*.035*block; }
            if(vhs>.01){ sx += std::sin(y*.047+phase*11.0)*width*.018*vhs; if(((y+static_cast<int>(phase*91))%97)<3) sx += width*.10*vhs; }
            if(recursion>.01){ const int band=std::max(1,height/10); if(((y/band)+static_cast<int>(phase*4))%3==1) sx=cx+(sx-cx)*(.82+.10*(1.0-recursion)); }
            int ix=std::clamp(static_cast<int>(std::lround(sx)),0,width-1), iy=std::clamp(static_cast<int>(std::lround(sy)),0,height-1);
            if(pxstep>1){ ix=(ix/pxstep)*pxstep; iy=(iy/pxstep)*pxstep; }
            const auto di=static_cast<std::size_t>((y*width+x)*3), si=static_cast<std::size_t>((iy*width+ix)*3);
            rgb[di]=src[si]; rgb[di+1]=src[si+1]; rgb[di+2]=src[si+2];
            if(split>.01){
                const int off=std::max(1,static_cast<int>(width*.018*split));
                const int xr=std::clamp(ix+off,0,width-1), xb=std::clamp(ix-off,0,width-1);
                rgb[di]=src[static_cast<std::size_t>((iy*width+xr)*3)];
                rgb[di+2]=src[static_cast<std::size_t>((iy*width+xb)*3+2)];
            }
        }
    }

    if(t.posterize>.01 || t.solarize>.01 || t.edge>.01){
        const auto src=rgb; const double post=amount(t.posterize), sol=amount(t.solarize), edge=amount(t.edge);
        const int levels=std::max(2,static_cast<int>(10-7*post)); const double step=255.0/(levels-1);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for(int y=0;y<height;++y) for(int x=0;x<width;++x){
            const auto i=static_cast<std::size_t>((y*width+x)*3);
            for(int c=0;c<3;++c){ double v=src[i+c]; if(post>.01)v=std::round(v/step)*step; if(sol>.01 && v>128.0-sol*36.0)v=v*(1.0-sol)+ (255.0-v)*sol; rgb[i+c]=clamp8(v); }
            if(edge>.01){
                const int xr=std::min(width-1,x+1), yd=std::min(height-1,y+1);
                const auto ir=static_cast<std::size_t>((y*width+xr)*3), id=static_cast<std::size_t>((yd*width+x)*3);
                const double e=std::min(255.0,std::abs(src[i]-src[ir])+std::abs(src[i]-src[id]) + std::abs(src[i+1]-src[ir+1])*.5);
                for(int c=0;c<3;++c) rgb[i+c]=clamp8(rgb[i+c]*(1.0-edge*.62)+e*edge*.92);
            }
        }
    }

    if(previous && previous->size()==rgb.size()){
        const auto current=rgb;
        const double echo=amount(std::max({t.feedback,t.frame_echo,t.motion_trails}));
        const double slit=amount(t.slit_scan), mosh=amount(t.datamosh), wipe=amount(t.mask_wipe);
        const bool shutter=t.shutter>.01 && std::fmod(phase*12.0,1.0)<amount(t.shutter)*.42;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for(int y=0;y<height;++y) for(int x=0;x<width;++x){
            const auto i=static_cast<std::size_t>((y*width+x)*3); double hist=echo;
            if(slit>.01 && ((y/std::max(4,height/22)+static_cast<int>(phase*5))%4==1)) hist=std::max(hist,.20+.55*slit);
            if(mosh>.01 && (((x/std::max(8,width/14))+(y/std::max(8,height/10))+static_cast<int>(phase*7))%7)<2) hist=std::max(hist,.18+.60*mosh);
            if(wipe>.01){ const double boundary=(.15+.85*progress)*width; if(x < boundary + std::sin(y*.018)*width*.08) hist=std::max(hist,.45*wipe); }
            if(shutter) hist=std::max(hist,.78*amount(t.shutter));
            hist=std::clamp(hist,0.0,.88);
            if(hist>.001) for(int c=0;c<3;++c) rgb[i+c]=clamp8(current[i+c]*(1.0-hist)+(*previous)[i+c]*hist);
        }
    }

    if(t.strobe>.01){
        const double st=amount(t.strobe); const double pulse=std::max(0.0,std::sin(phase*31.4159265359)); const double gain=1.0+st*.85*pulse;
        for(auto& v:rgb)v=clamp8(v*gain);
    }
}


namespace {

inline std::uint64_t mix64(std::uint64_t x) {
    x ^= x >> 30; x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27; x *= 0x94d049bb133111ebULL;
    x ^= x >> 31; return x;
}

inline double unit_rand(std::uint64_t seed, std::uint64_t index) {
    return static_cast<double>(mix64(seed + index * 0x9e3779b97f4a7c15ULL) & 0xffffffULL) / 16777216.0;
}

inline double effect_amount(const VectorEffect& e, double p) {
    p = std::clamp(p, 0.0, 1.0);
    const double q = p * 3.0;
    const int i = std::min(2, static_cast<int>(q));
    const double f = q - i;
    return std::clamp(e.amount_samples[i] * (1.0 - f) + e.amount_samples[i + 1] * f, 0.0, 1.0);
}

inline void blend_pixel(std::vector<std::uint8_t>& rgb, int width, int height, int x, int y,
                        double r, double g, double b, double alpha) {
    if (x < 0 || x >= width || y < 0 || y >= height) return;
    const auto i = static_cast<std::size_t>((y * width + x) * 3);
    const double a = std::clamp(alpha, 0.0, 1.0);
    rgb[i] = clamp8(rgb[i] * (1.0 - a) + r * a);
    rgb[i + 1] = clamp8(rgb[i + 1] * (1.0 - a) + g * a);
    rgb[i + 2] = clamp8(rgb[i + 2] * (1.0 - a) + b * a);
}

void draw_line(std::vector<std::uint8_t>& rgb, int width, int height,
               int x0, int y0, int x1, int y1,
               double r, double g, double b, double alpha, int thickness = 1) {
    const int dx = std::abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
    const int dy = -std::abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    while (true) {
        for (int oy = -thickness/2; oy <= thickness/2; ++oy)
            for (int ox = -thickness/2; ox <= thickness/2; ++ox)
                blend_pixel(rgb, width, height, x0 + ox, y0 + oy, r, g, b, alpha);
        if (x0 == x1 && y0 == y1) break;
        const int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

inline double luminance(const std::vector<std::uint8_t>& rgb, int width, int x, int y) {
    const auto i = static_cast<std::size_t>((y * width + x) * 3);
    return .2126*rgb[i] + .7152*rgb[i+1] + .0722*rgb[i+2];
}

void draw_native_contours(std::vector<std::uint8_t>& rgb, int width, int height,
                          const VectorEffect& e, double amount, bool semantic) {
    if (amount <= .01) return;
    const auto src = rgb;
    const int step = std::max(3, std::min(width, height) / 210);
    const int gw = std::max(3, width / step), gh = std::max(3, height / step);
    std::vector<double> mags(static_cast<std::size_t>(gw) * gh, 0.0);
    std::vector<std::uint8_t> edge(mags.size(), 0), visited(mags.size(), 0);
    const double threshold = semantic ? 150.0 : 115.0;
    auto sample = [&](int gx, int gy) {
        return luminance(src, width, std::clamp(gx * step, 0, width - 1), std::clamp(gy * step, 0, height - 1));
    };
    for (int gy = 1; gy < gh - 1; ++gy) {
        for (int gx = 1; gx < gw - 1; ++gx) {
            const double sx = -sample(gx-1,gy-1)-2*sample(gx-1,gy)-sample(gx-1,gy+1)
                              +sample(gx+1,gy-1)+2*sample(gx+1,gy)+sample(gx+1,gy+1);
            const double sy = -sample(gx-1,gy-1)-2*sample(gx,gy-1)-sample(gx+1,gy-1)
                              +sample(gx-1,gy+1)+2*sample(gx,gy+1)+sample(gx+1,gy+1);
            const auto i = static_cast<std::size_t>(gy * gw + gx);
            mags[i] = std::hypot(sx, sy);
            if (mags[i] >= threshold) edge[i] = 1;
        }
    }

    struct Component { std::vector<int> cells; double score{0.0}; };
    std::vector<Component> components;
    constexpr int dx8[8] = {-1,0,1,-1,1,-1,0,1};
    constexpr int dy8[8] = {-1,-1,-1,0,0,1,1,1};
    for (int gy = 1; gy < gh - 1; ++gy) for (int gx = 1; gx < gw - 1; ++gx) {
        const int start = gy * gw + gx;
        if (!edge[start] || visited[start]) continue;
        Component c; std::vector<int> stack{start}; visited[start] = 1;
        while (!stack.empty()) {
            const int cur = stack.back(); stack.pop_back(); c.cells.push_back(cur); c.score += mags[cur];
            const int x = cur % gw, y = cur / gw;
            for (int k = 0; k < 8; ++k) {
                const int nx=x+dx8[k], ny=y+dy8[k];
                if(nx<=0||nx>=gw-1||ny<=0||ny>=gh-1) continue;
                const int n=ny*gw+nx;
                if(edge[n]&&!visited[n]){visited[n]=1;stack.push_back(n);}
            }
        }
        if (c.cells.size() >= 7) {
            c.score *= std::sqrt(static_cast<double>(c.cells.size()));
            components.push_back(std::move(c));
        }
    }
    std::sort(components.begin(), components.end(), [](const Component& a,const Component& b){return a.score>b.score;});
    const int max_paths = std::min<int>(semantic ? 5 : 9, std::min<int>(e.count, components.size()));
    for (int ci=0; ci<max_paths; ++ci) {
        const auto& comp=components[ci];
        std::vector<std::uint8_t> remaining(mags.size(),0);
        for(int cell:comp.cells) remaining[cell]=1;
        auto degree=[&](int cell){int d=0,x=cell%gw,y=cell/gw;for(int k=0;k<8;k++){int nx=x+dx8[k],ny=y+dy8[k];if(nx>0&&nx<gw-1&&ny>0&&ny<gh-1&&remaining[ny*gw+nx])++d;}return d;};
        int cur=comp.cells.front();
        for(int cell:comp.cells) if(degree(cell)<=1){cur=cell;break;}
        double last_angle=0.0; bool have_angle=false; std::vector<std::pair<int,int>> path;
        while(cur>=0&&remaining[cur]){
            remaining[cur]=0;const int x=cur%gw,y=cur/gw;path.emplace_back(x*step,y*step);
            int best=-1;double best_score=1e9,best_angle=last_angle;
            for(int k=0;k<8;k++){const int nx=x+dx8[k],ny=y+dy8[k];if(nx<=0||nx>=gw-1||ny<=0||ny>=gh-1)continue;const int n=ny*gw+nx;if(!remaining[n])continue;const double a=std::atan2(static_cast<double>(ny-y),static_cast<double>(nx-x));const double turn=have_angle?std::abs(std::atan2(std::sin(a-last_angle),std::cos(a-last_angle))):0.0;const double score=turn-.0007*mags[n];if(score<best_score){best_score=score;best=n;best_angle=a;}}
            if (best < 0) break;
            cur = best;
            last_angle = best_angle;
            have_angle = true;
        }
        if(path.size()<5)continue;
        const double hue=std::fmod(185.0+ci*17.0+70.0*amount,360.0),rr=128+127*std::sin(hue*.0174533),gg=128+127*std::sin((hue+120)*.0174533),bb=128+127*std::sin((hue+240)*.0174533);
        for(std::size_t i=1;i<path.size();++i){
            draw_line(rgb,width,height,path[i-1].first,path[i-1].second,path[i].first,path[i].second,rr,gg,bb,e.opacity*amount*(semantic?.40:.34),std::max(1,static_cast<int>(e.line_width)));
        }
    }
}

void draw_native_flow(std::vector<std::uint8_t>& rgb, int width, int height,
                      const VectorEffect& e, double amount, double phase, bool particles) {
    const auto src=rgb;
    struct Seed { int x; int y; double mag; };
    std::vector<Seed> seeds;
    const int step=std::max(8,std::min(width,height)/90);
    for(int y=step;y<height-step;y+=step)for(int x=step;x<width-step;x+=step){
        const double gx=luminance(src,width,x+step/2,y)-luminance(src,width,x-step/2,y);
        const double gy=luminance(src,width,x,y+step/2)-luminance(src,width,x,y-step/2);
        const double mag=std::hypot(gx,gy);if(mag>18)seeds.push_back({x,y,mag});
    }
    std::sort(seeds.begin(),seeds.end(),[](const Seed&a,const Seed&b){return a.mag>b.mag;});
    const int count=std::min<int>(particles?24:12,std::min<int>(e.count,seeds.size()));
    const double base=std::atan2(e.motion_y,e.motion_x==0?1e-6:e.motion_x);
    for(int i=0;i<count;i++){
        const auto& seed=seeds[i];double x=seed.x,y=seed.y,angle=base+std::sin(phase*.7+i*.61)*(.12+.28*amount);const int segments=particles?2:7;
        const double ds=(particles?8.0:18.0)*(0.55+amount);
        const double hue=190+i*8,rr=128+110*std::sin(hue*.0174533),gg=150+90*std::sin((hue+120)*.0174533),bb=240;
        for(int seg=0;seg<segments;seg++){
            const double bend=std::sin(phase*.55+i*.43+seg*.7)*(.05+.14*amount);angle+=bend;
            const int nx=static_cast<int>(x+std::cos(angle)*ds),ny=static_cast<int>(y+std::sin(angle)*ds);
            draw_line(rgb,width,height,static_cast<int>(x),static_cast<int>(y),nx,ny,rr,gg,bb,e.opacity*amount*(particles?.32:.46),std::max(1,static_cast<int>(e.line_width)));
            x=nx;y=ny;if(x<0||x>=width||y<0||y>=height)break;
        }
    }
}

void draw_native_grid(std::vector<std::uint8_t>& rgb,int width,int height,const VectorEffect& e,double amount,double phase){
    const int vx=static_cast<int>(width*(.5+.22*e.motion_x+.04*std::sin(phase*.4)));
    const int vy=static_cast<int>(height*(.38+.16*e.motion_y));
    const int count=std::max(6,std::min(40,e.count));
    for(int i=0;i<=count;i++){
        const int x=static_cast<int>(static_cast<double>(i)/count*width);
        draw_line(rgb,width,height,vx,vy,x,height,80,210,255,e.opacity*amount,std::max(1,static_cast<int>(e.line_width)));
    }
    for(int j=1;j<=10;j++){
        const double q=static_cast<double>(j)/10.0, z=q*q*q;
        const int y=static_cast<int>(vy+(height-vy)*z), spread=static_cast<int>(width*(.12+.88*z));
        draw_line(rgb,width,height,vx-spread/2,y,vx+spread/2,y,120,180,255,e.opacity*amount*.8,std::max(1,static_cast<int>(e.line_width)));
    }
}

void draw_native_fracture(std::vector<std::uint8_t>& rgb,int width,int height,const VectorEffect& e,double amount,bool voronoi){
    const int n=std::max(8,std::min(64,e.count));
    std::vector<std::pair<int,int>> pts;pts.reserve(n);
    for(int i=0;i<n;i++)pts.emplace_back(static_cast<int>(unit_rand(e.seed,i*2)*width),static_cast<int>(unit_rand(e.seed,i*2+1)*height));
    if(voronoi){
        const int step=std::max(4,std::min(width,height)/180);
        for(int y=step;y<height-step;y+=step)for(int x=step;x<width-step;x+=step){
            int a=-1,b=-1;double da=1e30,db=1e30;
            for(int i=0;i<n;i++){const double dx=x-pts[i].first,dy=y-pts[i].second,d=dx*dx+dy*dy;if(d<da){db=da;b=a;da=d;a=i;}else if(d<db){db=d;b=i;}}
            if(a>=0&&b>=0&&std::abs(std::sqrt(db)-std::sqrt(da))<step*1.6)
                blend_pixel(rgb,width,height,x,y,210,100+120*unit_rand(e.seed,a),255,e.opacity*amount);
        }
    }else{
        const int cx=width/2,cy=height/2;
        std::sort(pts.begin(),pts.end(),[&](auto&a,auto&b){return std::atan2(a.second-cy,a.first-cx)<std::atan2(b.second-cy,b.first-cx);});
        for(int i=0;i<n;i++){
            auto a=pts[i],b=pts[(i+1)%n];
            draw_line(rgb,width,height,cx,cy,a.first,a.second,255,100+100*unit_rand(e.seed,i),180,e.opacity*amount,std::max(1,static_cast<int>(e.line_width)));
            draw_line(rgb,width,height,a.first,a.second,b.first,b.second,120,200,255,e.opacity*amount*.8,std::max(1,static_cast<int>(e.line_width)));
        }
    }
}

void draw_native_glyph(std::vector<std::uint8_t>& rgb,int width,int height,const VectorEffect& e,double amount,double phase){
    const int arms=std::max(3,std::min(12,e.count)),cx=width/2,cy=height/2;
    const double radius=std::min(width,height)*(.05+.09*amount);
    for(int a=0;a<arms;a++){
        double angle=static_cast<double>(a)/arms*6.28318530718+phase*.08;
        int px=cx,py=cy;
        for(int n=1;n<=6;n++){
            angle+=std::sin(e.seed*.001+n*1.7)*.18;
            const double r=radius*n/6.0;
            const int x=cx+static_cast<int>(std::cos(angle)*r),y=cy+static_cast<int>(std::sin(angle)*r);
            draw_line(rgb,width,height,px,py,x,y,170,100+120*unit_rand(e.seed,n+a*7),255,e.opacity*amount,std::max(1,static_cast<int>(e.line_width)));
            px=x;py=y;
        }
    }
}

void apply_native_displacement(std::vector<std::uint8_t>& rgb,int width,int height,const VectorEffect& e,double amount,double phase){
    const auto src=rgb;const int strips=std::max(6,std::min(36,e.count));const int sh=std::max(1,height/strips);
    for(int s=0;s<strips;s++){
        const int y0=s*sh,y1=std::min(height,y0+sh);
        const int dx=static_cast<int>(std::sin(phase*(1.4+amount*2)+s*.73+e.seed*.0001)*width*.026*amount);
        const int dy=static_cast<int>(std::cos(phase*1.31+s*.37)*height*.008*amount);
        for(int y=y0;y<y1;y++)for(int x=0;x<width;x++){
            const int sx=std::clamp(x-dx,0,width-1),sy=std::clamp(y-dy,0,height-1);
            const auto di=static_cast<std::size_t>((y*width+x)*3),si=static_cast<std::size_t>((sy*width+sx)*3);
            rgb[di]=clamp8(src[di]*(1-.32*amount)+src[si]*.32*amount);
            rgb[di+1]=clamp8(src[di+1]*(1-.32*amount)+src[si+1]*.32*amount);
            rgb[di+2]=clamp8(src[di+2]*(1-.32*amount)+src[si+2]*.32*amount);
        }
    }
}

void apply_native_portal(std::vector<std::uint8_t>& rgb,const std::vector<std::uint8_t>* companion,
                         int width,int height,const VectorEffect& e,double amount,double phase){
    if(!companion||companion->size()!=rgb.size())return;
    const double radius=std::min(width,height)*(e.radius>0?e.radius:(.12+.18*amount));
    const double cx=width*(.42+.22*std::sin(phase*.7+e.seed*.001)),cy=height*(.48+.18*std::cos(phase*.55+e.seed*.002));
    const int variant=static_cast<int>(e.seed % 4u);
    for(int y=0;y<height;y++)for(int x=0;x<width;x++){
        const double dx=x-cx,dy=y-cy;
        double q=0.0;
        if(variant==0){const double rx=radius*1.25,ry=radius*.76;q=std::sqrt((dx*dx)/(rx*rx)+(dy*dy)/(ry*ry));}
        else if(variant==1){q=std::abs(dx)/(radius*1.18)+std::abs(dy)/(radius*.86);}
        else if(variant==2){q=std::max(std::abs(dx)/(radius*1.30),std::abs(dy)/(radius*.62));}
        else{const double rr=std::hypot(dx,dy),a=std::atan2(dy,dx);q=rr/(radius*(1+.12*std::sin(a*5+phase*1.7)));}
        if(q>1.0)continue;
        const double edge=std::clamp((1.0-q)/.18,0.0,1.0);
        const double a=e.opacity*amount*edge;
        const auto i=static_cast<std::size_t>((y*width+x)*3);
        rgb[i]=clamp8(rgb[i]*(1-a)+(*companion)[i]*a);
        rgb[i+1]=clamp8(rgb[i+1]*(1-a)+(*companion)[i+1]*a);
        rgb[i+2]=clamp8(rgb[i+2]*(1-a)+(*companion)[i+2]*a);
    }
}


inline double creative_envelope(const double (&values)[4], double p) {
    p = std::clamp(p, 0.0, 1.0);
    const double q = p * 3.0;
    const int i = std::min(2, static_cast<int>(q));
    const double f = q - i;
    return std::clamp(values[i] * (1.0 - f) + values[i + 1] * f, 0.0, 1.0);
}

inline double hero_envelope(const CreativeEffect& c, double p) {
    if (c.hero_kind.empty() || c.hero_amount <= .0 || p < c.hero_start || p > c.hero_end) return 0.0;
    const double q = (p - c.hero_start) / std::max(1e-6, c.hero_end - c.hero_start);
    auto smooth = [](double x) { x = std::clamp(x, 0.0, 1.0); return x * x * (3.0 - 2.0 * x); };
    return c.hero_amount * std::min(smooth(q / .16), smooth((1.0 - q) / .22));
}

inline void copy_pixel(const std::vector<std::uint8_t>& src, std::vector<std::uint8_t>& dst,
                       int width, int height, int dx, int dy, int sx, int sy, double alpha = 1.0) {
    if (dx < 0 || dx >= width || dy < 0 || dy >= height || sx < 0 || sx >= width || sy < 0 || sy >= height) return;
    const auto di = static_cast<std::size_t>((dy * width + dx) * 3);
    const auto si = static_cast<std::size_t>((sy * width + sx) * 3);
    const double a = std::clamp(alpha, 0.0, 1.0);
    for (int c = 0; c < 3; ++c) dst[di + c] = clamp8(dst[di + c] * (1.0 - a) + src[si + c] * a);
}

double creative_legacy_gate(const CreativeEffect& c, std::uint64_t salt) {
    const auto key = static_cast<std::uint64_t>(std::llround(c.target_x*100000.0))*0x9e3779b97f4a7c15ULL
        ^ static_cast<std::uint64_t>(std::llround(c.target_y*100000.0))*0xc2b2ae3d27d4eb4fULL
        ^ static_cast<std::uint64_t>(c.symmetry_segments+17)*0x165667b19e3779f9ULL ^ salt;
    return .5*(hash_noise(key)+1.0);
}

void native_directed_color(std::vector<std::uint8_t>& rgb, int width, int height,
                           const CreativeEffect& c, double fidelity) {
    if(c.style_version<2 && creative_legacy_gate(c,31)<.70) return;
    const double room = std::clamp(1.0 - fidelity, 0.0, 1.0);
    if (room <= .005) return;
    const double hue_deg = std::clamp(c.color_hue_shift, -14.0, 14.0);
    const double sat = std::clamp(c.color_saturation, .5, 1.6);
    const double contrast = std::clamp(c.color_contrast, .6, 1.6);
    const double brightness = std::clamp(c.color_brightness, .65, 1.4);
    const double color_delta = std::min(
        1.0,
        std::abs(hue_deg) / 14.0 +
        .55 * std::abs(sat - 1.0) +
        .35 * std::abs(contrast - 1.0) +
        .25 * std::abs(brightness - 1.0)
    );
    const double alpha = std::min(.24, .015 + room * (.34 + .26 * color_delta));
    if (alpha <= .005) return;
    const auto src = rgb;
    const double hue = hue_deg * 3.14159265358979323846 / 180.0;
    const double hc = std::cos(hue), hs = std::sin(hue);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const auto i = static_cast<std::size_t>((y * width + x) * 3);
            double r = src[i], g = src[i + 1], b = src[i + 2];
            const double luma = .2126*r + .7152*g + .0722*b;
            r = luma + (r-luma)*sat; g = luma + (g-luma)*sat; b = luma + (b-luma)*sat;
            if (std::abs(hue_deg) > 1e-4) {
                const double yy=.299*r+.587*g+.114*b;
                const double ii=.596*r-.274*g-.322*b;
                const double qq=.211*r-.523*g+.312*b;
                const double ir=ii*hc-qq*hs, qr=ii*hs+qq*hc;
                r=yy+.956*ir+.621*qr; g=yy-.272*ir-.647*qr; b=yy-1.106*ir+1.703*qr;
            }
            r=(r-127.5)*contrast+127.5;g=(g-127.5)*contrast+127.5;b=(b-127.5)*contrast+127.5;
            r*=brightness;g*=brightness;b*=brightness;
            rgb[i]=clamp8(src[i]*(1-alpha)+r*alpha);
            rgb[i+1]=clamp8(src[i+1]*(1-alpha)+g*alpha);
            rgb[i+2]=clamp8(src[i+2]*(1-alpha)+b*alpha);
        }
    }
}

void native_virtual_camera(std::vector<std::uint8_t>& rgb, int width, int height,
                           const CreativeEffect& c, double amount, double progress, double phase) {
    if (amount <= .015) return;
    const auto src = rgb;
    const double ease = .5 - .5 * std::cos(3.141592653589793 * std::clamp(progress, 0.0, 1.0));
    const double zoom = 1.0 + amount * (.012 + .045 * ease);
    const double cx = c.target_x * width, cy = c.target_y * height;
    const double drift_x = std::sin(progress * 5.0 + phase * .08) * c.drift_x * width * .010 * amount;
    const double drift_y = std::sin(progress * 4.0 + phase * .07) * c.drift_y * height * .008 * amount;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const double sx_f = cx + (x - cx - drift_x) / zoom;
            const double sy_f = cy + (y - cy - drift_y) / zoom;
            const int sx = std::clamp(static_cast<int>(std::llround(sx_f)), 0, width - 1);
            const int sy = std::clamp(static_cast<int>(std::llround(sy_f)), 0, height - 1);
            const auto di = static_cast<std::size_t>((y * width + x) * 3);
            const auto si = static_cast<std::size_t>((sy * width + sx) * 3);
            rgb[di] = src[si]; rgb[di + 1] = src[si + 1]; rgb[di + 2] = src[si + 2];
        }
    }
}

void native_depth_parallax(std::vector<std::uint8_t>& rgb, int width, int height,
                           const CreativeEffect& c, double amount, double phase) {
    if (amount <= .015) return;
    const auto src = rgb;
    constexpr int cols = 16, rows = 9;
    std::array<double, cols * rows> depth_map{};
    const double target_x = c.target_x, target_y = c.target_y;
    const double subject_r = std::max(.08, c.subject_radius);
    for (int gy = 0; gy < rows; ++gy) {
        for (int gx = 0; gx < cols; ++gx) {
            const int sx = std::clamp(static_cast<int>((gx + .5) / cols * width), 0, width - 1);
            const int sy = std::clamp(static_cast<int>((gy + .5) / rows * height), 0, height - 1);
            const auto i = static_cast<std::size_t>((sy * width + sx) * 3);
            const double r = src[i] / 255.0, g = src[i+1] / 255.0, b = src[i+2] / 255.0;
            const double mx = std::max({r,g,b}), mn = std::min({r,g,b});
            const double sat = mx - mn;
            const double lum = .2126*r + .7152*g + .0722*b;
            const double nx = (gx + .5) / cols, ny = (gy + .5) / rows;
            const double radial = std::hypot(nx-target_x, ny-target_y);
            double depth = .18 + .56*(1.0-ny) + .10*(1.0-sat) + .06*(1.0-lum);
            const double protect = std::max(0.0, 1.0-radial/subject_r);
            depth -= .42 * protect * c.subject_preserve;
            depth_map[static_cast<std::size_t>(gy*cols+gx)] = std::clamp(depth, 0.0, 1.0);
        }
    }
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        const int gy = std::min(rows-1, y * rows / std::max(1,height));
        for (int x = 0; x < width; ++x) {
            const int gx = std::min(cols-1, x * cols / std::max(1,width));
            const double depth = depth_map[static_cast<std::size_t>(gy*cols+gx)];
            const double d = (depth - .50) * amount;
            const int dx = static_cast<int>((c.drift_x * .74 + std::sin(phase*.30 + gy*.51 + gx*.13)*.26) * width * .032 * d);
            const int dy = static_cast<int>((c.drift_y * .64 + std::cos(phase*.27 + gx*.37)*.18) * height * .022 * d);
            const int sx = std::clamp(x - dx, 0, width - 1), sy = std::clamp(y - dy, 0, height - 1);
            const auto di = static_cast<std::size_t>((y * width + x) * 3), si = static_cast<std::size_t>((sy * width + sx) * 3);
            for (int ch = 0; ch < 3; ++ch) rgb[di + ch] = clamp8(src[di + ch] * .72 + src[si + ch] * .28);
        }
    }
    if (c.depth_fog * amount > .02) {
        const double fog = c.depth_fog * amount;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height / 2; ++y) {
            const double a = fog * .11 * (1.0 - static_cast<double>(y) / std::max(1, height / 2));
            for (int x = 0; x < width; ++x) {
                const auto i = static_cast<std::size_t>((y * width + x) * 3);
                rgb[i] = clamp8(rgb[i] * (1-a) + 205 * a);
                rgb[i+1] = clamp8(rgb[i+1] * (1-a) + 225 * a);
                rgb[i+2] = clamp8(rgb[i+2] * (1-a) + 255 * a);
            }
        }
    }
}

void native_flow_warp(std::vector<std::uint8_t>& rgb, const std::vector<std::uint8_t>* previous,
                      int width, int height, const CreativeEffect& c, double amount) {
    if (!previous || previous->size() != rgb.size() || amount <= .015) return;
    const auto src = rgb;
    const int step = std::max(24, std::min(width, height) / 22);
    const int radius = std::max(4, step / 3);
    const double cx = c.target_x * width, cy = c.target_y * height;
    const double subject_r = c.subject_radius * std::min(width, height);
    for (int y = step; y < height - step; y += step) {
        for (int x = step; x < width - step; x += step) {
            const double cur = luminance(src, width, x, y), prev = luminance(*previous, width, x, y);
            const double dt = (cur - prev) / 255.0;
            const double gx = (luminance(src, width, x + radius, y) - luminance(src, width, x - radius, y)) / 255.0;
            const double gy = (luminance(src, width, x, y + radius) - luminance(src, width, x, y - radius)) / 255.0;
            const double grad = std::hypot(gx, gy);
            if (std::abs(dt) < .018 || grad < .015) continue;
            const double protect = std::hypot(x - cx, y - cy) < subject_r ? 1.0 - c.subject_preserve * .75 : 1.0;
            if (protect < .12) continue;
            const double strength = std::clamp((std::abs(dt) * 2.2 + grad * .8) * amount * protect, 0.0, 1.0);
            const int dx = static_cast<int>(-std::copysign(1.0, dt) * gx / std::max(.01, grad) * width * .024 * strength);
            const int dy = static_cast<int>(-std::copysign(1.0, dt) * gy / std::max(.01, grad) * height * .030 * strength);
            const int half = step / 2;
            for (int py = -half; py <= half; ++py) for (int px = -half; px <= half; ++px) {
                const int tx = x + px, ty = y + py;
                copy_pixel(src, rgb, width, height, tx, ty, tx - dx, ty - dy, .18 + .28 * strength);
            }
        }
    }
}

void native_temporal(std::vector<std::uint8_t>& rgb, const std::vector<std::uint8_t>* previous,
                     int width, int height, [[maybe_unused]] const CreativeEffect& c, double echo, double rgb_delay, double smear, double flow_trails) {
    if (!previous || previous->size() != rgb.size()) return;
    if (echo > .015 || flow_trails > .015) {
        const double a = std::clamp(.06 + .20 * std::max(echo, flow_trails), 0.0, .28);
        blend_layer(rgb, *previous, a, flow_trails > echo ? "screen" : "normal");
    }
    if (rgb_delay > .015) {
        const auto src = rgb;
        const int shift = std::max(1, static_cast<int>(width * .008 * rgb_delay));
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
            const auto i = static_cast<std::size_t>((y * width + x) * 3);
            const int xr = std::clamp(x + shift, 0, width - 1), xb = std::clamp(x - shift, 0, width - 1);
            rgb[i] = (*previous)[static_cast<std::size_t>((y * width + xr) * 3)];
            rgb[i+2] = (*previous)[static_cast<std::size_t>((y * width + xb) * 3 + 2)];
            rgb[i+1] = clamp8(.82 * src[i+1] + .18 * (*previous)[i+1]);
        }
    }
    if (smear > .015) {
        const auto src = rgb;
        const int bands = 18 + static_cast<int>(smear * 22), sh = std::max(1, height / bands);
        for (int b = 0; b < bands; ++b) {
            const int dx = static_cast<int>(std::sin(b * .71) * width * .020 * smear);
            if (b % 3) continue;
            for (int y = b * sh; y < std::min(height, (b + 1) * sh); ++y) for (int x = 0; x < width; ++x)
                copy_pixel(*previous, rgb, width, height, x, y, std::clamp(x - dx, 0, width-1), y, .10 + .22 * smear);
        }
    }
}

void native_feedback(std::vector<std::uint8_t>& rgb, const std::vector<std::uint8_t>* previous,
                     int width, int height, const CreativeEffect& c, double amount) {
    if (!previous || previous->size() != rgb.size() || amount <= .015) return;
    const auto src = rgb;
    const double cx = c.target_x * width, cy = c.target_y * height;
    const double scale = 1.0 + c.feedback_scale * (.35 + .9 * amount);
    const double angle = c.feedback_rotation * 3.141592653589793 / 180.0 * amount;
    const double cs = std::cos(-angle), sn = std::sin(-angle);
    const double alpha = .025 + .12 * amount;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
        const double rx = (x - cx) / scale, ry = (y - cy) / scale;
        const int sx = std::clamp(static_cast<int>(cx + rx * cs - ry * sn), 0, width-1);
        const int sy = std::clamp(static_cast<int>(cy + rx * sn + ry * cs), 0, height-1);
        const auto di = static_cast<std::size_t>((y*width+x)*3), si = static_cast<std::size_t>((sy*width+sx)*3);
        for(int ch=0;ch<3;++ch){const double screen=255.0-(255.0-src[di+ch])*(255.0-(*previous)[si+ch])/255.0;rgb[di+ch]=clamp8(src[di+ch]*(1-alpha)+screen*alpha);}
    }
}

void native_local_symmetry(std::vector<std::uint8_t>& rgb, int width, int height,
                           const CreativeEffect& c, double amount, double phase) {
    if (amount <= .02) return;
    const auto src = rgb;
    const double cx = c.target_x * width, cy = c.target_y * height;
    const double radius = std::min(width,height) * (.10 + .14 * amount);
    const int segments = std::max(2, std::min(12, c.symmetry_segments));
    const double wedge = 2.0 * 3.141592653589793 / segments;
    const double alpha = .025 + .08 * amount;
    const int variant=(segments+static_cast<int>(std::round(c.target_x*17)))%3;
    const int x0 = std::max(0, static_cast<int>(cx-radius*1.4)), x1 = std::min(width-1, static_cast<int>(cx+radius*1.4));
    const int y0 = std::max(0, static_cast<int>(cy-radius)), y1 = std::min(height-1, static_cast<int>(cy+radius));
    for(int y=y0;y<=y1;++y)for(int x=x0;x<=x1;++x){
        const double dx=x-cx,dy=y-cy,r=std::hypot(dx,dy);
        const double shape=(variant==0)?std::sqrt((dx*dx)/(radius*radius*1.55)+(dy*dy)/(radius*radius*.62)):(variant==1)?(std::abs(dx)/(radius*1.2)+std::abs(dy)/(radius*.82)):std::max(std::abs(dx)/(radius*1.35),std::abs(dy)/(radius*.58));
        if(shape>1.0)continue;
        double a=std::atan2(dy,dx)+phase*.012*amount;a=std::fmod(a+20*wedge,wedge);if(a>wedge*.5)a=wedge-a;
        const int sx=std::clamp(static_cast<int>(cx+std::cos(a)*r),0,width-1),sy=std::clamp(static_cast<int>(cy+std::sin(a)*r),0,height-1);
        const auto di=static_cast<std::size_t>((y*width+x)*3),si=static_cast<std::size_t>((sy*width+sx)*3);
        for(int ch=0;ch<3;++ch){const double screen=255.0-(255.0-src[di+ch])*(255.0-src[si+ch])/255.0;rgb[di+ch]=clamp8(src[di+ch]*(1-alpha)+screen*alpha);}
    }
}

void native_source_texture(std::vector<std::uint8_t>& rgb, int width, int height,
                           [[maybe_unused]] const CreativeEffect& c, double bloom, double streaks) {
    if (bloom <= .015 && streaks <= .015) return;
    const auto src = rgb;
    if (bloom > .015) {
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y=0;y<height;++y) for(int x=0;x<width;++x){const auto i=static_cast<std::size_t>((y*width+x)*3);const double l=.2126*src[i]+.7152*src[i+1]+.0722*src[i+2];if(l<155)continue;const double a=(l-155)/100.0*(.05+.18*bloom);rgb[i]=clamp8(rgb[i]*(1-a)+std::min(255.0,src[i]*1.35)*a);rgb[i+1]=clamp8(rgb[i+1]*(1-a)+std::min(255.0,src[i+1]*1.35)*a);rgb[i+2]=clamp8(rgb[i+2]*(1-a)+std::min(255.0,src[i+2]*1.35)*a);}
    }
    if (streaks > .015) {
        const int strips=14, sw=std::max(1,width/strips);
        for(int s=0;s<strips;++s){const int sx=std::clamp(s*sw,0,width-1);double peak=0;for(int y=0;y<height;y+=std::max(1,height/48))peak=std::max(peak,luminance(src,width,sx,y));if(peak<175)continue;const int dx=static_cast<int>(std::sin(s*1.7)*width*.008*streaks);for(int y=0;y<height;++y)for(int x=s*sw;x<std::min(width,(s+1)*sw);++x)copy_pixel(src,rgb,width,height,x,y,std::clamp(x-dx,0,width-1),y,.025+.08*streaks);}
    }
}

void native_palette(std::vector<std::uint8_t>& rgb, int width, int height, const CreativeEffect& c, double amount) {
    if (amount <= .015) return;
    const double alpha=.02+.10*amount;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for(int y=0;y<height;++y)for(int x=0;x<width;++x){const auto i=static_cast<std::size_t>((y*width+x)*3);const double q=.35+.65*(static_cast<double>(x)/std::max(1,width-1));rgb[i]=clamp8(rgb[i]*(1-alpha)+c.palette_r*q*alpha);rgb[i+1]=clamp8(rgb[i+1]*(1-alpha)+c.palette_g*q*alpha);rgb[i+2]=clamp8(rgb[i+2]*(1-alpha)+c.palette_b*q*alpha);}
}

void restore_subject(std::vector<std::uint8_t>& rgb, const std::vector<std::uint8_t>& original,
                     int width, int height, const CreativeEffect& c, double amount) {
    if (c.subject_preserve * amount <= .02) return;
    const double cx=c.target_x*width,cy=c.target_y*height,r=c.subject_radius*std::min(width,height);
    const int center_x=std::clamp(static_cast<int>(cx),0,width-1),center_y=std::clamp(static_cast<int>(cy),0,height-1);
    const auto ci=static_cast<std::size_t>((center_y*width+center_x)*3);
    const double cr=original[ci],cg=original[ci+1],cb=original[ci+2];
    const int x0=std::max(0,static_cast<int>(cx-r*1.15)),x1=std::min(width-1,static_cast<int>(cx+r*1.15));
    const int y0=std::max(0,static_cast<int>(cy-r*1.35)),y1=std::min(height-1,static_cast<int>(cy+r*1.35));
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for(int y=y0;y<=y1;++y)for(int x=x0;x<=x1;++x){
        const double d=std::sqrt(std::pow((x-cx)/std::max(1.0,r),2)+std::pow((y-cy)/std::max(1.0,r*1.2),2));if(d>1.15)continue;
        const auto i=static_cast<std::size_t>((y*width+x)*3);
        const double color=std::sqrt(std::pow(original[i]-cr,2)+std::pow(original[i+1]-cg,2)+std::pow(original[i+2]-cb,2))/441.673;
        const double proximity=std::clamp(1.0-d/1.15,0.0,1.0);
        const double continuity=.32+.68*std::clamp(1.0-color*1.25,0.0,1.0);
        const double mask=proximity*continuity;
        const double edge=std::clamp((1-d)/.30,0.0,1.0);
        const double a=c.subject_preserve*amount*(.08+.42*mask+.14*edge);
        for(int ch=0;ch<3;++ch)rgb[i+ch]=clamp8(rgb[i+ch]*(1-a)+original[i+ch]*a);
    }
}

} // namespace

void apply_creative_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const CreativeEffect& c,
    double progress,
    double phase
) {
    if (rgb.empty()) return;
    const auto original = rgb;
    const double common_env = creative_envelope(c.envelope, progress);
    const double hero = hero_envelope(c, progress);
    const double fidelity = std::clamp(c.source_fidelity - .16 * hero, .58, 1.0);
    native_directed_color(rgb, width, height, c, fidelity);

    const double camera = c.camera_energy * creative_envelope(c.camera_envelope, progress);
    const double palette = c.palette_strength * creative_envelope(c.palette_envelope, progress) * (c.style_version<2 && creative_legacy_gate(c,89)<.70 ? 0.0 : 1.0);
    const double bloom = c.texture_bloom * creative_envelope(c.bloom_envelope, progress);
    const double streaks = c.texture_streaks * creative_envelope(c.streaks_envelope, progress);
    const double depth = std::max(
        c.depth_parallax * creative_envelope(c.depth_envelope, progress),
        c.background_warp * creative_envelope(c.background_envelope, progress) * .55
    );
    const double flow = c.flow_warp * creative_envelope(c.flow_warp_envelope, progress);
    const double echo = c.temporal_echo * creative_envelope(c.temporal_echo_envelope, progress);
    const double rgb_delay = std::max(
        c.temporal_rgb * creative_envelope(c.temporal_rgb_envelope, progress),
        c.flow_rgb * creative_envelope(c.flow_rgb_envelope, progress) * .65
    );
    const double smear = c.temporal_smear * creative_envelope(c.temporal_smear_envelope, progress);
    const double trails = c.flow_trails * creative_envelope(c.flow_trails_envelope, progress);
    const double symmetry = c.local_symmetry * creative_envelope(c.symmetry_envelope, progress) * (c.style_version<2 && creative_legacy_gate(c,83)<.90 ? 0.0 : 1.0);
    const double feedback = c.feedback * creative_envelope(c.feedback_envelope, progress);

    // The native path is CPU-heavy, so insignificant curve tails are skipped.
    // This retains the visible trajectory while avoiding several full-frame passes
    // during the deliberately restrained parts of a phrase.
    if (camera > .035) native_virtual_camera(rgb, width, height, c, camera, progress, phase);
    if (palette > .045) native_palette(rgb, width, height, c, palette);
    if (std::max(bloom, streaks) > .050) native_source_texture(rgb, width, height, c, bloom, streaks);
    if (depth > .050) native_depth_parallax(rgb, width, height, c, depth, phase);
    if (flow > .055) native_flow_warp(rgb, previous, width, height, c, flow);
    if (std::max({echo, rgb_delay, smear, trails}) > .045)
        native_temporal(rgb, previous, width, height, c, echo, rgb_delay, smear, trails);
    if (symmetry > .065) native_local_symmetry(rgb, width, height, c, symmetry, phase);
    if (feedback > .045) native_feedback(rgb, previous, width, height, c, feedback);

    if (hero > .015) {
        if (c.hero_kind == "flow_melt") {
            native_flow_warp(rgb, previous, width, height, c, .92 * hero);
            native_temporal(rgb, previous, width, height, c, .0, .28*hero, .55*hero, .35*hero);
        } else if (c.hero_kind == "depth_burst") {
            native_depth_parallax(rgb, width, height, c, .92*hero, phase);
            native_feedback(rgb, previous, width, height, c, .58*hero);
        } else if (c.hero_kind == "recursive_portal") {
            native_local_symmetry(rgb, width, height, c, .78*hero, phase);
            native_feedback(rgb, previous, width, height, c, .82*hero);
            native_source_texture(rgb, width, height, c, .42*hero, .26*hero);
        } else if (c.hero_kind == "subject_echo") {
            native_temporal(rgb, previous, width, height, c, .55*hero, .36*hero, .42*hero, .40*hero);
        } else if (c.hero_kind == "time_prism") {
            native_temporal(rgb, previous, width, height, c, .28*hero, .62*hero, .44*hero, .20*hero);
            native_flow_warp(rgb, previous, width, height, c, .24*hero);
        }
    }
    restore_subject(rgb, original, width, height, c, std::max(common_env, hero));
}


void apply_creative_temporal_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const CreativeEffect& c,
    double progress,
    double phase
) {
    if (rgb.empty() || !previous || previous->size() != rgb.size()) return;
    const double hero = hero_envelope(c, progress);
    const double echo = c.temporal_echo * creative_envelope(c.temporal_echo_envelope, progress);
    const double rgb_delay = std::max(
        c.temporal_rgb * creative_envelope(c.temporal_rgb_envelope, progress),
        c.flow_rgb * creative_envelope(c.flow_rgb_envelope, progress) * .65
    );
    const double smear = c.temporal_smear * creative_envelope(c.temporal_smear_envelope, progress);
    const double trails = c.flow_trails * creative_envelope(c.flow_trails_envelope, progress);
    const double feedback = c.feedback * creative_envelope(c.feedback_envelope, progress);

    if (std::max({echo, rgb_delay, smear, trails}) > .045)
        native_temporal(rgb, previous, width, height, c, echo, rgb_delay, smear, trails);
    if (feedback > .045) native_feedback(rgb, previous, width, height, c, feedback);

    // Spatial hero work is performed in the fused GPU shader. Keep only the
    // previous-frame parts here.
    if (hero > .015) {
        if (c.hero_kind == "flow_melt") {
            native_temporal(rgb, previous, width, height, c, .0, .28*hero, .55*hero, .35*hero);
        } else if (c.hero_kind == "depth_burst") {
            native_feedback(rgb, previous, width, height, c, .58*hero);
        } else if (c.hero_kind == "recursive_portal") {
            native_feedback(rgb, previous, width, height, c, .82*hero);
        } else if (c.hero_kind == "subject_echo") {
            native_temporal(rgb, previous, width, height, c, .55*hero, .36*hero, .42*hero, .40*hero);
        } else if (c.hero_kind == "time_prism") {
            native_temporal(rgb, previous, width, height, c, .28*hero, .62*hero, .44*hero, .20*hero);
        }
    }
    (void)phase;
}

void apply_source_color_fidelity(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>& reference,
    int width,
    int height,
    const CreativeEffect& c,
    double progress
) {
    if (rgb.size() != reference.size() || rgb.empty()) return;
    const double hero = hero_envelope(c, progress);
    const double fidelity = std::clamp(c.source_fidelity - .16 * hero, .58, 1.0);
    if (fidelity <= .60) return;

    const double hue_intent = std::clamp(std::abs(c.color_hue_shift) / 14.0, 0.0, 1.0);
    const double palette_intent = std::clamp(c.palette_strength, 0.0, 1.0);
    const double intentional = std::clamp(.48*hue_intent + .35*palette_intent + .42*hero, 0.0, 1.0);
    const double base = std::clamp((fidelity - .60) / .40, 0.0, 1.0);
    const double alpha = std::clamp(base * (.94 - .48*intentional), 0.0, .94);
    if (alpha <= .025) return;

#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const auto i = static_cast<std::size_t>((y * width + x) * 3);
            const double r = rgb[i], g = rgb[i+1], b = rgb[i+2];
            const double rr = reference[i], rg = reference[i+1], rb = reference[i+2];

            // YIQ is convenient here because Y is perceptual luminance while I/Q
            // carry chroma. Keep the effected frame's Y, but interpolate I/Q back
            // toward the actual source frame. Spatial effects remain intact while
            // a runaway additive color cast cannot dominate the whole shot.
            const double y_out = .299*r + .587*g + .114*b;
            const double i_out = .596*r - .274*g - .322*b;
            const double q_out = .211*r - .523*g + .312*b;
            const double i_ref = .596*rr - .274*rg - .322*rb;
            const double q_ref = .211*rr - .523*rg + .312*rb;
            const double ii = i_out*(1.0-alpha) + i_ref*alpha;
            const double qq = q_out*(1.0-alpha) + q_ref*alpha;

            rgb[i]   = clamp8(y_out + .956*ii + .621*qq);
            rgb[i+1] = clamp8(y_out - .272*ii - .647*qq);
            rgb[i+2] = clamp8(y_out - 1.106*ii + 1.703*qq);
        }
    }
}

void apply_vector_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* companion,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const std::vector<VectorEffect>& effects,
    double progress,
    double phase
) {
    for(const auto& e:effects){
        const double amount=effect_amount(e,progress);
        if(amount<=.012)continue;
        if(e.kind=="contours") draw_native_contours(rgb,width,height,e,amount,false);
        else if(e.kind=="semantic_outline") draw_native_contours(rgb,width,height,e,amount,true);
        else if(e.kind=="flow_ribbons") draw_native_flow(rgb,width,height,e,amount,phase,false);
        else if(e.kind=="flow_particles") draw_native_flow(rgb,width,height,e,amount,phase,true);
        else if(e.kind=="vector_echo"){
            draw_native_contours(rgb,width,height,e,amount*.5,false);
            if(previous&&previous->size()==rgb.size()) blend_layer(rgb,*previous,e.opacity*amount*.16,"screen");
        }
        else if(e.kind=="perspective_grid") draw_native_grid(rgb,width,height,e,amount,phase);
        else if(e.kind=="delaunay_fracture"){ if(e.displace)apply_native_displacement(rgb,width,height,e,amount*e.explode,phase); if(e.visible)draw_native_fracture(rgb,width,height,e,amount,false); }
        else if(e.kind=="voronoi"){ if(e.displace)apply_native_displacement(rgb,width,height,e,amount*.35,phase); if(e.visible)draw_native_fracture(rgb,width,height,e,amount,true); }
        else if(e.kind=="portal") apply_native_portal(rgb,companion,width,height,e,amount,phase);
        else if(e.kind=="motif_glyph") draw_native_glyph(rgb,width,height,e,amount,phase);
        else if(e.kind=="vector_displacement") apply_native_displacement(rgb,width,height,e,amount,phase);
    }
}

void compose_layers(
    std::vector<std::uint8_t>& dst,
    const std::vector<std::vector<std::uint8_t>>& companions,
    const std::vector<double>& opacities,
    const std::vector<std::string>& blend_modes,
    const std::string& mode,
    int width,
    int height,
    double progress,
    double phase
) {
    if(companions.empty()) return;
    if(mode=="single") return;
    if(mode=="luma" || mode=="flow") {
        for(std::size_t n=0;n<companions.size();++n){
            if(companions[n].size()!=dst.size())continue;
            const double a=n<opacities.size()?opacities[n]:.55;
            if(mode=="luma") blend_layer(dst,companions[n],a*.72,(n&1)?"multiply":"screen");
            else {
                // Organic traveling mask; unlike old full-frame overlay this keeps
                // source identity while allowing companion footage to flow through.
                const auto base=dst; const auto& src=companions[n];
                const double cx=width*(.5+.24*std::sin(phase*.73+n*2.1));
                const double cy=height*(.5+.19*std::cos(phase*.57+n*1.7));
                const double rx=width*(.32+.10*std::sin(phase*.31+n));
                const double ry=height*(.28+.08*std::cos(phase*.43+n));
                for(int y=0;y<height;++y)for(int x=0;x<width;++x){
                    const double q=std::sqrt(((x-cx)*(x-cx))/(rx*rx)+((y-cy)*(y-cy))/(ry*ry));
                    const double mask=std::clamp((1.18-q)*2.5,0.0,1.0)*a;
                    if(mask<=.001)continue; const auto i=static_cast<std::size_t>((y*width+x)*3);
                    for(int c=0;c<3;++c)dst[i+c]=clamp8(base[i+c]*(1-mask)+src[i+c]*mask);
                }
            }
        }
        return;
    }
    if(mode=="strips"){
        const int count=10+static_cast<int>(companions.size())*2; const int sw=std::max(1,width/count);
        for(int x=0;x<width;++x){
            const int strip=(x/sw+static_cast<int>(phase*2.4))%count;
            if(strip%3==0)continue; const std::size_t n=static_cast<std::size_t>(strip)%companions.size();
            const auto& src=companions[n]; if(src.size()!=dst.size())continue; const double a=(n<opacities.size()?opacities[n]:.6)*.86;
            for(int y=0;y<height;++y){const auto i=static_cast<std::size_t>((y*width+x)*3);for(int c=0;c<3;++c)dst[i+c]=clamp8(dst[i+c]*(1-a)+src[i+c]*a);}
        }
        return;
    }
    if(mode=="split"){
        const auto& src=companions.front(); if(src.size()!=dst.size())return; const double a=opacities.empty()?.75:opacities.front();
        const double boundary=width*(.18+.64*progress)+std::sin(phase*1.8)*width*.09;
        for(int y=0;y<height;++y)for(int x=0;x<width;++x){const double b=boundary+(y-height*.5)*.22; if(x>b)continue; const auto i=static_cast<std::size_t>((y*width+x)*3);for(int c=0;c<3;++c)dst[i+c]=clamp8(dst[i+c]*(1-a)+src[i+c]*a);}
        return;
    }
    if(mode=="mosaic"){
        const int cols=3, rows=2; const int cw=std::max(1,width/cols), ch=std::max(1,height/rows);
        for(int y=0;y<height;++y)for(int x=0;x<width;++x){const int cell=(x/cw)+(y/ch)*cols+static_cast<int>(phase*.8); if(cell%3==0)continue; const std::size_t n=static_cast<std::size_t>(cell)%companions.size(); const auto& src=companions[n]; if(src.size()!=dst.size())continue; const double a=(n<opacities.size()?opacities[n]:.68)*.90; const auto i=static_cast<std::size_t>((y*width+x)*3);for(int c=0;c<3;++c)dst[i+c]=clamp8(dst[i+c]*(1-a)+src[i+c]*a);}
        return;
    }
    if(mode=="swap"){
        const std::size_t n=static_cast<std::size_t>(std::floor((progress*4.0+phase*.25)))%companions.size(); const auto& src=companions[n]; if(src.size()!=dst.size())return; const double a=std::clamp(.72+(n<opacities.size()?opacities[n]:.6)*.25,0.0,.94); blend_layer(dst,src,a,"normal"); return;
    }
    for(std::size_t n=0;n<companions.size();++n) blend_layer(dst,companions[n],n<opacities.size()?opacities[n]:.6,n<blend_modes.size()?blend_modes[n]:"normal");
}

void blend_layer(
    std::vector<std::uint8_t>& dst,
    const std::vector<std::uint8_t>& src,
    double opacity,
    const std::string& mode
) {
    if (dst.size() != src.size()) return;
    const double a = std::clamp(opacity, 0.0, 1.0);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (std::int64_t idx = 0; idx < static_cast<std::int64_t>(dst.size()); ++idx) {
        const auto i = static_cast<std::size_t>(idx);
        const double d = dst[i] / 255.0;
        const double sv = src[i] / 255.0;
        double mixed = sv;
        if (mode == "screen") mixed = 1.0 - (1.0 - d) * (1.0 - sv);
        else if (mode == "multiply") mixed = d * sv;
        else if (mode == "overlay")
            mixed = d < 0.5
                ? 2.0 * d * sv
                : 1.0 - 2.0 * (1.0 - d) * (1.0 - sv);
        else if (mode == "lighten") mixed = std::max(d, sv);
        const double out = d * (1.0 - a) + mixed * a;
        dst[i] = clamp8(out * 255.0);
    }
}

void crossfade(
    std::vector<std::uint8_t>& dst,
    const std::vector<std::uint8_t>& previous,
    double amount
) {
    if (dst.size() != previous.size()) return;
    const double a = std::clamp(amount, 0.0, 1.0);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (std::int64_t idx = 0; idx < static_cast<std::int64_t>(dst.size()); ++idx) {
        const auto i = static_cast<std::size_t>(idx);
        dst[i] = clamp8(previous[i] * (1.0 - a) + dst[i] * a);
    }
}

} // namespace tubeviz
