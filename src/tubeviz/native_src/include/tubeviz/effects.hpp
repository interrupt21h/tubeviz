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
    double ripple{0.0};
    double chroma{0.0};
    double vortex{0.0};
    double bloom{0.0};
    double harmonic{0.0};

    void decay(double fps);
    void apply(const Cue& cue);
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
