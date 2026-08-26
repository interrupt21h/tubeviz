// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "tubeviz/decoder.hpp"
#include "tubeviz/effects.hpp"
#include "tubeviz/manifest.hpp"

namespace tubeviz {

class Renderer {
public:
    Renderer(
        Manifest manifest,
        int width,
        int height,
        double fps,
        std::size_t decoder_cache_limit = 16,
        int threads = 0
    );
    int run();

private:
    const Shot* shot_at(double time, std::size_t& index) const;
    std::vector<std::uint8_t> render_layer(const Layer& layer, double shot_time, double now, bool legacy_style);
    std::vector<std::uint8_t> render_shot(const Shot& shot, double now, bool allow_previous_effects);
    Decoder& decoder_for(const std::string& path);
    void trim_decoders(const Shot& shot);
    void warm_shot(const Shot& shot);

    Manifest manifest_;
    int width_{};
    int height_{};
    double fps_{};
    struct DecoderEntry {
        std::unique_ptr<Decoder> decoder;
        std::uint64_t last_used{0};
    };
    std::unordered_map<std::string, DecoderEntry> decoders_;
    std::size_t decoder_cache_limit_{16};
    std::uint64_t decoder_use_clock_{0};
    int threads_{0};
    ReactiveState reactive_{};
    std::size_t cue_index_{0};
    std::vector<std::uint8_t> previous_output_;
    // Composed primary+companion frame before creative/vector/reactive effects. Used
    // by the final source-chroma guard so every native post-processing path obeys
    // CreativeEffectPlan.source_fidelity.
    std::vector<std::uint8_t> color_reference_;
    bool has_previous_output_{false};
    std::size_t previous_shot_index_{static_cast<std::size_t>(-1)};
};

} // namespace tubeviz
