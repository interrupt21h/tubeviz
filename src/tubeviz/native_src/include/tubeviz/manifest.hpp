// SPDX-License-Identifier: Apache-2.0
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

struct VectorEffect {
    std::string kind;
    double amount{0.0};
    double opacity{0.0};
    std::uint64_t seed{0};
    int count{0};
    double line_width{1.0};
    bool visible{true};
    bool displace{false};
    double motion_x{0.0};
    double motion_y{0.0};
    double amount_samples[4]{0.0, 0.0, 0.0, 0.0};
    double explode{0.0};
    double radius{0.0};
};

struct CreativeEffect {
    int style_version{0};
    double flow_warp{0.0};
    double flow_trails{0.0};
    double flow_rgb{0.0};
    double temporal_echo{0.0};
    double temporal_rgb{0.0};
    double temporal_smear{0.0};
    double camera_energy{0.0};
    double target_x{0.5};
    double target_y{0.5};
    double drift_x{0.0};
    double drift_y{0.0};
    double depth_parallax{0.0};
    double depth_fog{0.0};
    double subject_preserve{0.0};
    double subject_radius{0.28};
    double background_warp{0.0};
    double feedback{0.0};
    double feedback_scale{0.004};
    double feedback_rotation{0.0};
    double local_symmetry{0.0};
    int symmetry_segments{4};
    double texture_bloom{0.0};
    double texture_streaks{0.0};
    double palette_strength{0.0};
    // High source fidelity keeps music-directed color a restrained, source-relative
    // grade.  These values are applied once after source-layer composition.
    double source_fidelity{0.90};
    double color_hue_shift{0.0};
    double color_saturation{1.0};
    double color_contrast{1.0};
    double color_brightness{1.0};
    int palette_r{128};
    int palette_g{160};
    int palette_b{220};
    std::string hero_kind;
    double hero_amount{0.0};
    double hero_start{0.0};
    double hero_end{1.0};
    double abstraction{0.0};
    // The common envelope is retained for compact/older creative manifests.
    // New manifests additionally carry independent curves so native rendering
    // follows the same per-effect trajectories as the browser renderer.
    double envelope[4]{1.0, 1.0, 1.0, 1.0};
    double flow_warp_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double flow_trails_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double flow_rgb_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double temporal_echo_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double temporal_rgb_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double temporal_smear_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double camera_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double depth_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double background_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double feedback_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double symmetry_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double bloom_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double streaks_envelope[4]{1.0, 1.0, 1.0, 1.0};
    double palette_envelope[4]{1.0, 1.0, 1.0, 1.0};
};

struct Shot {
    double time{0.0};
    double timeline_end{0.0};
    double crossfade{0.0};
    Layer primary{};
    std::vector<Layer> companions;
    std::vector<VectorEffect> vector_effects;
    CreativeEffect creative{};
};

struct Cue {
    double time{0.0};
    std::string action;
    double amount{0.0};
    double low{0.0};
    double mid{0.0};
    double high{0.0};
    int warp_mode{4};
    int warp_variant{0};
    double center_x{0.5};
    double center_y{0.5};
    double direction{0.0};
    double frequency{1.0};
    double polarity{1.0};
    double duration{0.18};
    double attack{0.07};
    double overshoot{0.15};
};

struct Manifest {
    double duration{0.0};
    std::vector<Shot> shots;
    std::vector<Cue> cues;
};

Manifest load_manifest(const std::string& path);
std::string percent_decode(const std::string& input);

} // namespace tubeviz
