#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace tubeviz {

struct Transform {
    double playback_rate{1.0};
    bool reverse{false};
    bool mirror{false};
    double brightness{1.0};
    double contrast{1.0};
    double saturation{1.0};
    double grayscale{0.0};
    double scanlines{0.0};
    double vignette{0.0};
    double pixelate{0.0};
    double rgb_split{0.0};
    double noise{0.0};
    double ripple{0.0};
    double vortex{0.0};
    double motion_trails{0.0};
    double frame_echo{0.0};
    double hue_degrees{0.0};
};

struct Layer {
    std::string path;
    double source_start{0.0};
    double source_end{0.0};
    double opacity{1.0};
    std::string blend_mode{"normal"};
    Transform transform{};
};

struct Shot {
    double time{0.0};
    double timeline_end{0.0};
    double crossfade{0.0};
    Layer primary{};
    std::vector<Layer> companions;
};

struct Cue {
    double time{0.0};
    std::string action;
    double amount{0.0};
    double low{0.0};
    double mid{0.0};
    double high{0.0};
};

struct Manifest {
    double duration{0.0};
    std::vector<Shot> shots;
    std::vector<Cue> cues;
};

Manifest load_manifest(const std::string& path);
std::string percent_decode(const std::string& input);

} // namespace tubeviz
