#include "tubeviz/effects.hpp"

#include <algorithm>
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
    beat_warp *= decay_for(0.76, fps);
    beat_low *= decay_for(0.82, fps);
    beat_mid *= decay_for(0.80, fps);
    beat_high *= decay_for(0.76, fps);
    ripple *= decay_for(0.90, fps);
    chroma *= decay_for(0.90, fps);
    vortex *= decay_for(0.91, fps);
    bloom *= decay_for(0.92, fps);
    harmonic *= decay_for(0.94, fps);
}

void ReactiveState::apply(const Cue& cue) {
    if (cue.action == "beat_warp" || cue.action == "video_edit_beat_warp") {
        beat_warp = std::max(beat_warp, cue.amount);
        beat_low = std::max(beat_low, cue.low);
        beat_mid = std::max(beat_mid, cue.mid);
        beat_high = std::max(beat_high, cue.high);
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
    }
}

void apply_transform(
    std::vector<std::uint8_t>& rgb,
    int width,
    int height,
    const Transform& t,
    std::uint64_t frame_index
) {
    if (rgb.empty()) return;
    const bool color = std::abs(t.brightness - 1.0) > 1e-4 ||
                       std::abs(t.contrast - 1.0) > 1e-4 ||
                       std::abs(t.saturation - 1.0) > 1e-4 ||
                       std::abs(t.hue_degrees) > 1e-4 ||
                       t.grayscale > 1e-4 || t.noise > 1e-4;
    if (color) {
        const double gray = std::clamp(t.grayscale, 0.0, 1.0);
        const double noise_amount = 28.0 * std::clamp(t.noise, 0.0, 1.0);
        const double hue = t.hue_degrees * 3.14159265358979323846 / 180.0;
        const double hc = std::cos(hue), hs = std::sin(hue);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            std::size_t i = static_cast<std::size_t>(y) * width * 3;
            for (int x = 0; x < width; ++x, i += 3) {
                double r = rgb[i], g = rgb[i + 1], b = rgb[i + 2];
                const double luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
                r = luma + (r - luma) * t.saturation;
                g = luma + (g - luma) * t.saturation;
                b = luma + (b - luma) * t.saturation;
                if (std::abs(t.hue_degrees) > 1e-4) {
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
                rgb[i] = clamp8(r); rgb[i + 1] = clamp8(g); rgb[i + 2] = clamp8(b);
            }
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

    if (t.scanlines > 1e-4) {
        const double gain = 1.0 - 0.32 * std::clamp(t.scanlines, 0.0, 1.0);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 1; y < height; y += 2) {
            auto i = static_cast<std::size_t>(y) * width * 3;
            for (int x = 0; x < width; ++x, i += 3) {
                rgb[i] = clamp8(rgb[i] * gain);
                rgb[i + 1] = clamp8(rgb[i + 1] * gain);
                rgb[i + 2] = clamp8(rgb[i + 2] * gain);
            }
        }
    }

    if (t.vignette > 1e-4) {
        const double amount = std::clamp(t.vignette, 0.0, 1.0);
        const double cx = (width - 1) * 0.5, cy = (height - 1) * 0.5;
        const double inv_r2 = 1.0 / std::max(1.0, cx * cx + cy * cy);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const double dx = x - cx, dy = y - cy;
                const double r2 = std::min(1.0, (dx * dx + dy * dy) * inv_r2);
                // Cheap smooth radial approximation; avoids millions of
                // sqrt()/pow() calls per HD frame.
                const double shaped = r2 * (0.68 + 0.32 * r2);
                const double gain = 1.0 - amount * 0.58 * shaped;
                const auto i = static_cast<std::size_t>((y * width + x) * 3);
                rgb[i] = clamp8(rgb[i] * gain);
                rgb[i + 1] = clamp8(rgb[i + 1] * gain);
                rgb[i + 2] = clamp8(rgb[i + 2] * gain);
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
    const double ripple = std::clamp(
        state.ripple + state.beat_warp * state.beat_mid * 0.35, 0.0, 1.0
    );
    const double radial = std::clamp(
        state.beat_warp * state.beat_low + state.vortex * 0.25, 0.0, 1.0
    );
    if (ripple > 0.015 || radial > 0.015) {
        const auto src = rgb;
        const double cx = width * (0.5 + 0.05 * std::sin(phase * 0.7));
        const double cy = height * (0.5 + 0.04 * std::cos(phase * 0.6));
        const double inv_scale2 =
            1.0 / (static_cast<double>(std::max(width, height)) *
                   std::max(width, height));
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            const double wave =
                std::sin(y * 0.055 + phase * 11.0) * width * 0.012 * ripple;
            for (int x = 0; x < width; ++x) {
                double sx = x - wave;
                double sy = y;
                if (radial > 0.0) {
                    const double dx = x - cx, dy = y - cy;
                    const double rr2 = (dx * dx + dy * dy) * inv_scale2;
                    // Ring centered around r ~= .22 using a rational falloff.
                    // This is visually close to the old exp/sqrt formulation
                    // and dramatically cheaper on multi-megapixel frames.
                    const double distance = std::abs(rr2 - 0.0484);
                    const double envelope = 1.0 / (1.0 + 125.0 * distance);
                    const double push = radial * 0.072 * envelope;
                    sx -= dx * push;
                    sy -= dy * push;
                }
                const int ix = std::clamp(static_cast<int>(sx + 0.5), 0, width - 1);
                const int iy = std::clamp(static_cast<int>(sy + 0.5), 0, height - 1);
                const auto di = static_cast<std::size_t>((y * width + x) * 3);
                const auto si = static_cast<std::size_t>((iy * width + ix) * 3);
                rgb[di] = src[si];
                rgb[di + 1] = src[si + 1];
                rgb[di + 2] = src[si + 2];
            }
        }
    }

    const double chroma = std::clamp(
        state.chroma + state.beat_warp * state.beat_high * 0.55, 0.0, 1.0
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
