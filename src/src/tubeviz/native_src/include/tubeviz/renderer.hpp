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
    Renderer(Manifest manifest, int width, int height, double fps);
    int run();

private:
    const Shot* shot_at(double time, std::size_t& index) const;
    std::vector<std::uint8_t> render_layer(const Layer& layer, double shot_time, double now);
    std::vector<std::uint8_t> render_shot(const Shot& shot, double now);
    Decoder& decoder_for(const std::string& path);
    void prune_decoders(const Shot& shot);

    Manifest manifest_;
    int width_{};
    int height_{};
    double fps_{};
    std::unordered_map<std::string, std::unique_ptr<Decoder>> decoders_;
    ReactiveState reactive_{};
    std::size_t cue_index_{0};
    std::vector<std::uint8_t> previous_output_;
    std::size_t previous_shot_index_{static_cast<std::size_t>(-1)};
};

} // namespace tubeviz
