// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "tubeviz/decoder.hpp"
#include "tubeviz/effects.hpp"
#include "tubeviz/gpu.hpp"
#include "tubeviz/manifest.hpp"
#include "tubeviz/resident_gpu.hpp"

namespace tubeviz {

class Renderer {
public:
    Renderer(
        Manifest manifest,
        int width,
        int height,
        double fps,
        std::size_t decoder_cache_limit = 16,
        int threads = 0,
        std::string gpu_mode = "auto",
        std::string hwdecode_mode = "auto"
    );
    int run();

private:
    const Shot* shot_at(double time, std::size_t& index) const;
    double layer_target(const Layer& layer, double shot_time, double now) const;
    std::vector<std::uint8_t> render_layer(const Layer& layer, double shot_time, double now, bool legacy_style);
    std::vector<std::uint8_t> render_shot(const Shot& shot, double now, bool allow_previous_effects);
    bool render_shot_resident(
        const Shot& shot,
        double now,
        bool allow_previous_effects,
        bool shot_changed,
        std::vector<std::uint8_t>& output,
        ResidentGpuTiming& timing,
        double& decode_ms
    );
    Decoder& decoder_for(const std::string& path);
    void trim_decoders(const Shot& shot);
    void warm_shot(const Shot& shot);
    void emit_perf(std::uint64_t frames) const;

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
    std::string gpu_mode_{"auto"};
    std::string hwdecode_mode_{"auto"};
    std::unique_ptr<ResidentGpuPipeline> resident_;
    bool resident_disabled_{false};
    bool resident_cuda_fallback_reported_{false};
    std::unique_ptr<GpuPostProcessor> gpu_;
    bool gpu_frame_used_{false};
    ReactiveState reactive_{};
    std::size_t cue_index_{0};
    std::vector<std::uint8_t> previous_output_;
    std::vector<std::uint8_t> color_reference_;
    bool has_previous_output_{false};
    std::size_t previous_shot_index_{static_cast<std::size_t>(-1)};

    // Cumulative performance counters. These deliberately report renderer stage
    // time rather than only aggregate fps so CUDA/Vulkan fallback and encoder
    // backpressure are immediately visible in ordinary render logs.
    std::uint64_t resident_frames_{0};
    std::uint64_t fallback_frames_{0};
    double perf_decode_ms_{0.0};
    double perf_map_ms_{0.0};
    double perf_compose_ms_{0.0};
    double perf_effects_ms_{0.0};
    double perf_download_ms_{0.0};
    double perf_cpu_ms_{0.0};
    double perf_pipe_ms_{0.0};
};

} // namespace tubeviz
