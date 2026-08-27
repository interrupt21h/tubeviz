// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "tubeviz/effects.hpp"
#include "tubeviz/manifest.hpp"

namespace tubeviz {

// Optional libplacebo/Vulkan post processor.  The public class always exists so
// the renderer can be built without libplacebo; in that case available() is
// false and apply_spatial() is a no-op returning false.
class GpuPostProcessor {
public:
    GpuPostProcessor(int width, int height, std::string mode = "auto");
    ~GpuPostProcessor();

    GpuPostProcessor(const GpuPostProcessor&) = delete;
    GpuPostProcessor& operator=(const GpuPostProcessor&) = delete;

    bool available() const noexcept;
    const std::string& backend() const noexcept;

    // Applies the expensive spatial/color portion of Creative FX plus reactive
    // beat treatment in one GPU shader pass. Temporal/history effects remain in
    // the renderer's CPU fallback because they depend on previous-frame state.
    bool apply_spatial(
        std::vector<std::uint8_t>& rgb,
        const CreativeEffect& creative,
        const ReactiveState& reactive,
        double progress,
        double phase
    );

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::string backend_{"off"};
};

} // namespace tubeviz
