// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/renderer.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <set>
#include <stdexcept>
#include <thread>

#ifdef TUBEVIZ_HAVE_OPENMP
#include <omp.h>
#endif

namespace tubeviz {
namespace {

bool temporal_hero(const CreativeEffect& c) {
    return c.hero_kind == "flow_melt" || c.hero_kind == "subject_echo" ||
           c.hero_kind == "time_prism" || c.hero_kind == "recursive_portal";
}

} // namespace

Renderer::Renderer(
    Manifest manifest,
    int width,
    int height,
    double fps,
    std::size_t decoder_cache_limit,
    int threads,
    std::string gpu_mode,
    std::string hwdecode_mode
)
    : manifest_(std::move(manifest)),
      width_(width),
      height_(height),
      fps_(fps),
      decoder_cache_limit_(std::max<std::size_t>(4, decoder_cache_limit)),
      threads_(threads),
      gpu_mode_(std::move(gpu_mode)),
      hwdecode_mode_(std::move(hwdecode_mode)) {
    previous_output_.resize(static_cast<std::size_t>(width_) * height_ * 3);
#ifdef TUBEVIZ_HAVE_OPENMP
    if (threads_ > 0) {
        omp_set_dynamic(0);
        omp_set_num_threads(threads_);
    }
#endif
    gpu_ = std::make_unique<GpuPostProcessor>(width_, height_, gpu_mode_);
}

Decoder& Renderer::decoder_for(const std::string& path) {
    ++decoder_use_clock_;
    auto it = decoders_.find(path);
    if (it == decoders_.end()) {
        DecoderEntry entry;
        entry.decoder = std::make_unique<Decoder>(path, width_, height_, hwdecode_mode_);
        entry.last_used = decoder_use_clock_;
        std::cerr << "INFO\tdecoder_open=" << path
                  << "\thw=" << entry.decoder->hardware_backend() << '\n';
        it = decoders_.emplace(path, std::move(entry)).first;
    } else {
        it->second.last_used = decoder_use_clock_;
    }
    return *it->second.decoder;
}

void Renderer::warm_shot(const Shot& shot) {
    // Opening demuxer/codec state is surprisingly expensive for short,
    // high-novelty edits. Keep current/next-shot decoders hot in the LRU cache.
    decoder_for(shot.primary.path);
    for (const auto& layer : shot.companions) {
        decoder_for(layer.path);
    }
}

void Renderer::trim_decoders(const Shot& shot) {
    if (decoders_.size() <= decoder_cache_limit_) return;

    std::set<std::string> protected_paths{shot.primary.path};
    for (const auto& layer : shot.companions) protected_paths.insert(layer.path);

    while (decoders_.size() > decoder_cache_limit_) {
        auto victim = decoders_.end();
        for (auto it = decoders_.begin(); it != decoders_.end(); ++it) {
            if (protected_paths.contains(it->first)) continue;
            if (victim == decoders_.end() || it->second.last_used < victim->second.last_used) {
                victim = it;
            }
        }
        if (victim == decoders_.end()) break;
        decoders_.erase(victim);
    }
}

const Shot* Renderer::shot_at(double time, std::size_t& index) const {
    if (manifest_.shots.empty()) return nullptr;
    while (index + 1 < manifest_.shots.size() && manifest_.shots[index + 1].time <= time + 1e-9) ++index;
    return &manifest_.shots[index];
}

std::vector<std::uint8_t> Renderer::render_layer(const Layer& layer, double shot_time, double now, bool legacy_style) {
    const double span = std::max(0.001, layer.source_end - layer.source_start);
    const double elapsed = std::max(0.0, now - shot_time);
    double offset = std::fmod(elapsed * std::max(0.01, layer.transform.playback_rate), span);
    if (offset < 0.0) offset += span;
    double target = layer.source_start + offset;
    if (layer.transform.reverse) target = layer.source_end - offset;
    target = std::clamp(target, layer.source_start, std::max(layer.source_start, layer.source_end - 0.001));

    // Decoder owns its reusable frame buffer. Copy once because shot-local transforms
    // intentionally mutate this layer before composition.
    auto frame = decoder_for(layer.path).frame_at(target);
    auto transform = layer.transform;
    if (legacy_style) transform.hue_degrees = 0.0;
    apply_transform(frame, width_, height_, transform, static_cast<std::uint64_t>(std::llround(now * fps_)));
    return frame;
}

std::vector<std::uint8_t> Renderer::render_shot(const Shot& shot, double now, bool allow_previous_effects) {
    gpu_frame_used_ = false;
    const bool legacy_style = shot.creative.style_version < 2;
    auto output = render_layer(shot.primary, shot.time, now, legacy_style);
    if (shot.primary.opacity < 0.999) {
        for (auto& c : output) c = static_cast<std::uint8_t>(c * std::clamp(shot.primary.opacity, 0.0, 1.0));
    }

    std::vector<std::uint8_t> portal_companion;
    bool have_portal_companion = false;
    for (const auto& layer : shot.companions) {
        auto companion = render_layer(layer, shot.time, now, legacy_style);
        if (!have_portal_companion) {
            portal_companion = companion;
            have_portal_companion = true;
        }
        blend_layer(output, companion, layer.opacity, layer.blend_mode);
    }

    // Canonical pre-FX color reference. Keep it as renderer state so the final
    // chroma guard can run after every post-processing path.
    color_reference_ = output;

    const double progress = std::clamp(
        (now - shot.time) / std::max(0.001, shot.timeline_end - shot.time),
        0.0, 1.0
    );
    const auto* previous = (has_previous_output_ && allow_previous_effects) ? &previous_output_ : nullptr;

    // Phase-2 hybrid GPU path: one libplacebo/Vulkan shader fuses the expensive
    // spatial/color Creative FX and reactive beat treatment. History-dependent
    // temporal operations remain CPU-side because they consume previous_output_.
    if (gpu_ && gpu_->available()) {
        gpu_frame_used_ = gpu_->apply_spatial(output, shot.creative, reactive_, progress, now * 0.24);
    }
    if (gpu_frame_used_) {
        apply_creative_temporal_effects(
            output, previous, width_, height_, shot.creative, progress, now * 0.24
        );
    } else {
        apply_creative_effects(
            output, previous, width_, height_, shot.creative, progress, now * 0.24
        );
    }

    auto vector_effects = shot.vector_effects;
    if (legacy_style) {
        vector_effects.erase(
            std::remove_if(vector_effects.begin(), vector_effects.end(), [](const VectorEffect& e) {
                return e.kind == "portal" && ((e.seed * 2654435761ULL + 71ULL) % 100ULL) < 90ULL;
            }),
            vector_effects.end()
        );
    }
    apply_vector_effects(
        output,
        have_portal_companion ? &portal_companion : nullptr,
        previous,
        width_,
        height_,
        vector_effects,
        progress,
        now * 0.24
    );
    return output;
}

int Renderer::run() {
    const std::uint64_t total_frames = static_cast<std::uint64_t>(std::ceil(manifest_.duration * fps_));
    std::size_t shot_index = 0;
    const auto frame_bytes = static_cast<std::size_t>(width_) * height_ * 3;

    std::cerr << "INFO\tdecoder_cache=" << decoder_cache_limit_
              << "\tthreads=" << threads_
              << "\thwdecode=" << hwdecode_mode_
              << "\tgpu=" << (gpu_ && gpu_->available() ? gpu_->backend() : "off");
#ifdef TUBEVIZ_HAVE_OPENMP
    std::cerr << "\topenmp=" << omp_get_max_threads();
#else
    std::cerr << "\topenmp=0";
#endif
    std::cerr << '\n';

    for (std::uint64_t frame_index = 0; frame_index < total_frames; ++frame_index) {
        const double now = static_cast<double>(frame_index) / fps_;
        reactive_.decay(fps_);
        while (cue_index_ < manifest_.cues.size() && manifest_.cues[cue_index_].time <= now + 1e-9) {
            reactive_.apply(manifest_.cues[cue_index_++]);
        }

        const Shot* shot = shot_at(now, shot_index);
        if (!shot) throw std::runtime_error("no shot at render time");
        if (shot_index != previous_shot_index_) {
            warm_shot(*shot);
            // Also open the immediately upcoming shot while cache pressure is
            // low. This removes most codec-open stalls at rapid scene cuts.
            if (shot_index + 1 < manifest_.shots.size()) {
                warm_shot(manifest_.shots[shot_index + 1]);
            }
            trim_decoders(*shot);
        }

        const bool shot_changed = shot_index != previous_shot_index_;
        const bool allow_previous_effects = !shot_changed || temporal_hero(shot->creative);
        auto output = render_shot(*shot, now, allow_previous_effects);
        // GPU frames already received reactive treatment in the fused shader.
        if (!gpu_frame_used_) {
            apply_reactive_effects(output, width_, height_, reactive_, now * 0.24);
        }
        // Keep the final color contract after CPU temporal/vector work. This is
        // intentionally retained even on GPU frames so later history/vector
        // passes cannot reintroduce a global cast.
        const double color_progress = std::clamp(
            (now - shot->time) / std::max(0.001, shot->timeline_end - shot->time),
            0.0, 1.0
        );
        apply_source_color_fidelity(
            output, color_reference_, width_, height_, shot->creative, color_progress
        );

        if (shot_index != previous_shot_index_ && shot->crossfade > 0.0 && frame_index > 0 && !previous_output_.empty()) {
            const double progress = std::clamp((now - shot->time) / shot->crossfade, 0.0, 1.0);
            crossfade(output, previous_output_, progress);
        }

        if (std::fwrite(output.data(), 1, frame_bytes, stdout) != frame_bytes) {
            return 2;
        }
        // Avoid a 6+ MiB full-frame copy at 1080p. stdout consumed the current
        // vector synchronously, so swap it into temporal history instead.
        previous_output_.swap(output);
        has_previous_output_ = true;
        previous_shot_index_ = shot_index;

        if (frame_index == 0 || frame_index + 1 == total_frames || (frame_index + 1) % std::max<std::uint64_t>(1, static_cast<std::uint64_t>(fps_)) == 0) {
            std::cerr << "PROGRESS\t" << (frame_index + 1) << '\t' << total_frames << '\n';
        }
    }
    std::fflush(stdout);
    return 0;
}

} // namespace tubeviz
