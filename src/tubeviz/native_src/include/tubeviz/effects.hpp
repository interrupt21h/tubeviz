// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "tubeviz/manifest.hpp"

namespace tubeviz {

struct ReactiveState {
    double beat_warp{0.0};
    double beat_low{0.0};
    double beat_mid{0.0};
    double beat_high{0.0};
    int beat_mode{4};
    int beat_variant{0};
    double beat_center_x{0.5};
    double beat_center_y{0.5};
    double beat_direction{0.0};
    double beat_frequency{1.0};
    double beat_polarity{1.0};
    double beat_duration{0.18};
    double beat_attack{0.07};
    double beat_overshoot{0.15};
    double beat_elapsed{1.0};
    double ripple{0.0};
    double chroma{0.0};
    double vortex{0.0};
    double bloom{0.0};
    double harmonic{0.0};
    double tempo_warp{0.0};
    double punch{0.0};
    double strobe{0.0};
    double tunnel{0.0};
    double kaleidoscope{0.0};
    double edge{0.0};
    double slit_scan{0.0};
    double echo{0.0};
    double corridor{0.0};
    double mask{0.0};
    double solarize{0.0};
    double datamosh{0.0};
    double motion_trails{0.0};
    double slice_recursion{0.0};
    double freeze{0.0};
    double switcher{0.0};

    void decay(double fps);
    void apply(const Cue& cue);
    double beat_phase() const;
    double beat_envelope() const;
    double beat_amount() const;
};

void apply_transform(
    std::vector<std::uint8_t>& rgb,
    int width,
    int height,
    const Transform& transform,
    std::uint64_t frame_index
);

void apply_reactive_effects(
    std::vector<std::uint8_t>& rgb,
    int width,
    int height,
    const ReactiveState& state,
    double phase
);

// Legacy/video-first transform effects that WebGPU applies after composition.
// Native output intentionally owns an equivalent implementation so enabling the
// native backend does not silently drop stylization, temporal or glitch effects.
void apply_post_transform_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const Transform& transform,
    double progress,
    double phase
);

// Multi-source composition grammar shared conceptually with browser preview.
void compose_layers(
    std::vector<std::uint8_t>& destination,
    const std::vector<std::vector<std::uint8_t>>& companions,
    const std::vector<double>& opacities,
    const std::vector<std::string>& blend_modes,
    const std::string& composition_mode,
    int width,
    int height,
    double progress,
    double phase
);

void apply_creative_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const CreativeEffect& creative,
    double progress,
    double phase
);

// History-dependent subset used when spatial/color work is fused on the GPU.
// This keeps temporal echo/feedback semantics without repeating the expensive
// spatial/color CPU passes.
void apply_creative_temporal_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const CreativeEffect& creative,
    double progress,
    double phase
);

// Re-anchor final hue/saturation toward the composed source frame while retaining
// effect-generated luminance/structure. This is the native equivalent of Canvas
// 'color' blending and makes source_fidelity a whole-render contract.
void apply_source_color_fidelity(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>& reference,
    int width,
    int height,
    const CreativeEffect& creative,
    double progress
);

void apply_vector_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* companion,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const std::vector<VectorEffect>& effects,
    double progress,
    double phase
);

void blend_layer(
    std::vector<std::uint8_t>& destination,
    const std::vector<std::uint8_t>& source,
    double opacity,
    const std::string& mode
);

void crossfade(
    std::vector<std::uint8_t>& destination,
    const std::vector<std::uint8_t>& previous,
    double amount
);

} // namespace tubeviz
