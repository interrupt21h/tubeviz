// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

extern "C" {
#include <libavutil/frame.h>
}

#include "tubeviz/effects.hpp"
#include "tubeviz/manifest.hpp"

namespace tubeviz {

struct ResidentLayerFrame {
    const AVFrame* frame{nullptr};
    const Transform* transform{nullptr};
    double opacity{1.0};
    std::string blend_mode{"normal"};
};

struct ResidentGpuTiming {
    double map_ms{0.0};
    double compose_ms{0.0};
    double effects_ms{0.0};
    double download_ms{0.0};
    bool hardware_input{false};
};

// GPU-resident native fast path. Source AVFrames are mapped directly into
// libplacebo, composed and transformed on Vulkan, and retained there through
// creative/post/temporal processing. The completed RGB frame is downloaded
// exactly once for the current stdout encoder contract.
//
// When libplacebo is unavailable this class remains buildable and reports
// available()==false, leaving Renderer on its existing CPU fallback path.
class ResidentGpuPipeline {
public:
    ResidentGpuPipeline(int width, int height, std::string mode = "auto");
    ~ResidentGpuPipeline();

    ResidentGpuPipeline(const ResidentGpuPipeline&) = delete;
    ResidentGpuPipeline& operator=(const ResidentGpuPipeline&) = delete;

    bool available() const noexcept;
    const std::string& backend() const noexcept;
    bool last_hardware_map_failed() const noexcept;

    bool render(
        const std::vector<ResidentLayerFrame>& layers,
        const std::string& composition_mode,
        const CreativeEffect& creative,
        const ReactiveState& reactive,
        const Transform& post_transform,
        const std::vector<VectorEffect>& vector_effects,
        double progress,
        double phase,
        bool allow_history,
        double crossfade_history,
        std::vector<std::uint8_t>& rgb,
        ResidentGpuTiming* timing = nullptr
    );

    void reset_history();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::string backend_{"off"};
    bool last_hardware_map_failed_{false};
};

} // namespace tubeviz
