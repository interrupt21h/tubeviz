#include "tubeviz/effects.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>

namespace tubeviz {
namespace {

inline std::uint8_t clamp8(double value) {
    return static_cast<std::uint8_t>(std::clamp(value, 0.0, 255.0));
}

inline double decay_for(double base, double fps) {
    return std::pow(base, 60.0 / std::max(1.0, fps));
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
                       t.grayscale > 1e-4 || t.noise > 1e-4;
    if (color) {
        std::minstd_rand rng(static_cast<unsigned>(frame_index * 2654435761ULL));
        std::uniform_real_distribution<double> noise(-1.0, 1.0);
        for (std::size_t i = 0; i + 2 < rgb.size(); i += 3) {
            double r = rgb[i], g = rgb[i + 1], b = rgb[i + 2];
            const double luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
            r = luma + (r - luma) * t.saturation;
            g = luma + (g - luma) * t.saturation;
            b = luma + (b - luma) * t.saturation;
            const double gray = std::clamp(t.grayscale, 0.0, 1.0);
            r = r * (1.0 - gray) + luma * gray;
            g = g * (1.0 - gray) + luma * gray;
            b = b * (1.0 - gray) + luma * gray;
            r = (r - 127.5) * t.contrast + 127.5;
            g = (g - 127.5) * t.contrast + 127.5;
            b = (b - 127.5) * t.contrast + 127.5;
            r *= t.brightness; g *= t.brightness; b *= t.brightness;
            if (t.noise > 1e-4) {
                const double n = noise(rng) * 28.0 * std::clamp(t.noise, 0.0, 1.0);
                r += n; g += n; b += n;
            }
            rgb[i] = clamp8(r); rgb[i + 1] = clamp8(g); rgb[i + 2] = clamp8(b);
        }
    }

    if (t.mirror) {
        const int stride = width * 3;
        for (int y = 0; y < height; ++y) {
            auto* row = rgb.data() + y * stride;
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
        const double amount = std::clamp(t.scanlines, 0.0, 1.0);
        for (int y = 1; y < height; y += 2) {
            for (int x = 0; x < width; ++x) {
                const auto i = static_cast<std::size_t>((y * width + x) * 3);
                rgb[i] = clamp8(rgb[i] * (1.0 - 0.32 * amount));
                rgb[i + 1] = clamp8(rgb[i + 1] * (1.0 - 0.32 * amount));
                rgb[i + 2] = clamp8(rgb[i + 2] * (1.0 - 0.32 * amount));
            }
        }
    }

    if (t.vignette > 1e-4) {
        const double amount = std::clamp(t.vignette, 0.0, 1.0);
        const double cx = (width - 1) * 0.5, cy = (height - 1) * 0.5;
        const double inv = 1.0 / std::sqrt(cx * cx + cy * cy);
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const double dx = x - cx, dy = y - cy;
                const double r = std::sqrt(dx * dx + dy * dy) * inv;
                const double gain = 1.0 - amount * 0.58 * std::pow(r, 1.7);
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
    const double ripple = std::clamp(state.ripple + state.beat_warp * state.beat_mid * 0.35, 0.0, 1.0);
    const double radial = std::clamp(state.beat_warp * state.beat_low + state.vortex * 0.25, 0.0, 1.0);
    if (ripple > 0.015 || radial > 0.015) {
        const auto src = rgb;
        const double cx = width * (0.5 + 0.05 * std::sin(phase * 0.7));
        const double cy = height * (0.5 + 0.04 * std::cos(phase * 0.6));
        for (int y = 0; y < height; ++y) {
            const double wave = std::sin(y * 0.055 + phase * 11.0) * width * 0.012 * ripple;
            for (int x = 0; x < width; ++x) {
                double sx = x - wave;
                double sy = y;
                if (radial > 0.0) {
                    const double dx = x - cx, dy = y - cy;
                    const double rr = std::sqrt(dx * dx + dy * dy) / std::max(width, height);
                    const double push = radial * 0.075 * std::exp(-8.0 * std::abs(rr - 0.22));
                    sx -= dx * push;
                    sy -= dy * push;
                }
                const int ix = std::clamp(static_cast<int>(std::lround(sx)), 0, width - 1);
                const int iy = std::clamp(static_cast<int>(std::lround(sy)), 0, height - 1);
                const auto di = static_cast<std::size_t>((y * width + x) * 3);
                const auto si = static_cast<std::size_t>((iy * width + ix) * 3);
                rgb[di] = src[si]; rgb[di + 1] = src[si + 1]; rgb[di + 2] = src[si + 2];
            }
        }
    }

    const double chroma = std::clamp(state.chroma + state.beat_warp * state.beat_high * 0.55, 0.0, 1.0);
    if (chroma > 0.015) {
        const auto src = rgb;
        const int offset = std::max(1, static_cast<int>(std::lround(width * 0.012 * chroma)));
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const auto i = static_cast<std::size_t>((y * width + x) * 3);
                const int xr = std::clamp(x + offset, 0, width - 1);
                const int xb = std::clamp(x - offset, 0, width - 1);
                rgb[i] = src[static_cast<std::size_t>((y * width + xr) * 3)];
                rgb[i + 2] = src[static_cast<std::size_t>((y * width + xb) * 3 + 2)];
            }
        }
    }

    if (state.bloom > 0.02 || state.harmonic > 0.02) {
        const double gain = 1.0 + 0.24 * std::clamp(state.bloom, 0.0, 1.0) + 0.10 * state.harmonic;
        for (auto& c : rgb) c = clamp8(c * gain);
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
    for (std::size_t i = 0; i < dst.size(); ++i) {
        const double d = dst[i] / 255.0;
        const double s = src[i] / 255.0;
        double mixed = s;
        if (mode == "screen") mixed = 1.0 - (1.0 - d) * (1.0 - s);
        else if (mode == "multiply") mixed = d * s;
        else if (mode == "overlay") mixed = d < 0.5 ? 2.0 * d * s : 1.0 - 2.0 * (1.0 - d) * (1.0 - s);
        else if (mode == "lighten") mixed = std::max(d, s);
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
    for (std::size_t i = 0; i < dst.size(); ++i) {
        dst[i] = clamp8(previous[i] * (1.0 - a) + dst[i] * a);
    }
}

} // namespace tubeviz
