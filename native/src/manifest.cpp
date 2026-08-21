#include "tubeviz/manifest.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace tubeviz {
namespace {

std::vector<std::string> split_tab(const std::string& line) {
    std::vector<std::string> fields;
    std::size_t start = 0;
    while (true) {
        const auto pos = line.find('\t', start);
        if (pos == std::string::npos) {
            fields.emplace_back(line.substr(start));
            break;
        }
        fields.emplace_back(line.substr(start, pos - start));
        start = pos + 1;
    }
    return fields;
}

double as_double(const std::vector<std::string>& f, std::size_t i, double fallback = 0.0) {
    if (i >= f.size() || f[i].empty()) return fallback;
    return std::stod(f[i]);
}

bool as_bool(const std::vector<std::string>& f, std::size_t i) {
    return i < f.size() && (f[i] == "1" || f[i] == "true");
}

Transform parse_transform(const std::vector<std::string>& f, std::size_t base) {
    Transform t;
    t.playback_rate = as_double(f, base + 0, 1.0);
    t.reverse = as_bool(f, base + 1);
    t.mirror = as_bool(f, base + 2);
    t.brightness = as_double(f, base + 3, 1.0);
    t.contrast = as_double(f, base + 4, 1.0);
    t.saturation = as_double(f, base + 5, 1.0);
    t.grayscale = as_double(f, base + 6, 0.0);
    t.scanlines = as_double(f, base + 7, 0.0);
    t.vignette = as_double(f, base + 8, 0.0);
    t.pixelate = as_double(f, base + 9, 0.0);
    t.rgb_split = as_double(f, base + 10, 0.0);
    t.noise = as_double(f, base + 11, 0.0);
    t.ripple = as_double(f, base + 12, 0.0);
    t.vortex = as_double(f, base + 13, 0.0);
    t.motion_trails = as_double(f, base + 14, 0.0);
    t.frame_echo = as_double(f, base + 15, 0.0);
    t.hue_degrees = as_double(f, base + 16, 0.0);
    return t;
}

} // namespace

std::string percent_decode(const std::string& input) {
    std::string out;
    out.reserve(input.size());
    for (std::size_t i = 0; i < input.size(); ++i) {
        if (input[i] == '%' && i + 2 < input.size()) {
            const auto hex = input.substr(i + 1, 2);
            char* end = nullptr;
            const long value = std::strtol(hex.c_str(), &end, 16);
            if (end && *end == '\0') {
                out.push_back(static_cast<char>(value));
                i += 2;
                continue;
            }
        }
        out.push_back(input[i]);
    }
    return out;
}

Manifest load_manifest(const std::string& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("unable to open manifest: " + path);

    Manifest manifest;
    Shot* current = nullptr;
    std::string line;
    std::size_t line_no = 0;
    while (std::getline(in, line)) {
        ++line_no;
        if (line.empty() || line[0] == '#') continue;
        const auto f = split_tab(line);
        if (f.empty()) continue;

        if (f[0] == "META") {
            if (f.size() < 2) throw std::runtime_error("invalid META line");
            manifest.duration = std::stod(f[1]);
        } else if (f[0] == "SHOT") {
            if (f.size() < 25) {
                throw std::runtime_error("invalid SHOT line " + std::to_string(line_no));
            }
            Shot shot;
            shot.time = as_double(f, 1);
            shot.timeline_end = as_double(f, 2);
            shot.crossfade = as_double(f, 3);
            shot.primary.path = percent_decode(f[4]);
            shot.primary.source_start = as_double(f, 5);
            shot.primary.source_end = as_double(f, 6);
            shot.primary.opacity = as_double(f, 7, 1.0);
            shot.primary.blend_mode = "normal";
            shot.primary.transform = parse_transform(f, 8);
            manifest.shots.push_back(std::move(shot));
            current = &manifest.shots.back();
        } else if (f[0] == "LAYER") {
            if (!current) throw std::runtime_error("LAYER before SHOT at line " + std::to_string(line_no));
            if (f.size() < 23) throw std::runtime_error("invalid LAYER line " + std::to_string(line_no));
            Layer layer;
            layer.path = percent_decode(f[1]);
            layer.source_start = as_double(f, 2);
            layer.source_end = as_double(f, 3);
            layer.opacity = as_double(f, 4, 0.65);
            layer.blend_mode = f[5];
            layer.transform = parse_transform(f, 6);
            current->companions.push_back(std::move(layer));
        } else if (f[0] == "VEC") {
            if (!current) throw std::runtime_error("VEC before SHOT at line " + std::to_string(line_no));
            if (f.size() < 17) throw std::runtime_error("invalid VEC line " + std::to_string(line_no));
            VectorEffect effect;
            effect.kind = f[1];
            effect.amount = as_double(f, 2);
            effect.opacity = as_double(f, 3);
            effect.seed = static_cast<std::uint64_t>(std::stoull(f[4]));
            effect.count = static_cast<int>(as_double(f, 5));
            effect.line_width = as_double(f, 6, 1.0);
            effect.visible = as_bool(f, 7);
            effect.displace = as_bool(f, 8);
            effect.motion_x = as_double(f, 9);
            effect.motion_y = as_double(f, 10);
            effect.amount_samples[0] = as_double(f, 11, effect.amount);
            effect.amount_samples[1] = as_double(f, 12, effect.amount);
            effect.amount_samples[2] = as_double(f, 13, effect.amount);
            effect.amount_samples[3] = as_double(f, 14, effect.amount);
            effect.explode = as_double(f, 15);
            effect.radius = as_double(f, 16);
            current->vector_effects.push_back(std::move(effect));
        } else if (f[0] == "CUE") {
            if (f.size() < 7) throw std::runtime_error("invalid CUE line " + std::to_string(line_no));
            Cue cue;
            cue.time = as_double(f, 1);
            cue.action = f[2];
            cue.amount = as_double(f, 3);
            cue.low = as_double(f, 4);
            cue.mid = as_double(f, 5);
            cue.high = as_double(f, 6);
            manifest.cues.push_back(std::move(cue));
        } else {
            throw std::runtime_error("unknown manifest record at line " + std::to_string(line_no) + ": " + f[0]);
        }
    }

    std::sort(manifest.shots.begin(), manifest.shots.end(), [](const Shot& a, const Shot& b) {
        return a.time < b.time;
    });
    std::sort(manifest.cues.begin(), manifest.cues.end(), [](const Cue& a, const Cue& b) {
        return a.time < b.time;
    });
    if (manifest.duration <= 0.0) throw std::runtime_error("manifest duration must be positive");
    if (manifest.shots.empty()) throw std::runtime_error("manifest contains no shots");
    return manifest;
}

} // namespace tubeviz
