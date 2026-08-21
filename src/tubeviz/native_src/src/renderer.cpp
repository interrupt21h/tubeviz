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

Renderer::Renderer(
    Manifest manifest,
    int width,
    int height,
    double fps,
    std::size_t decoder_cache_limit,
    int threads
)
    : manifest_(std::move(manifest)),
      width_(width),
      height_(height),
      fps_(fps),
      decoder_cache_limit_(std::max<std::size_t>(4, decoder_cache_limit)),
      threads_(threads) {
    previous_output_.resize(static_cast<std::size_t>(width_) * height_ * 3);
#ifdef TUBEVIZ_HAVE_OPENMP
    if (threads_ > 0) {
        omp_set_dynamic(0);
        omp_set_num_threads(threads_);
    }
#endif
}

Decoder& Renderer::decoder_for(const std::string& path) {
    ++decoder_use_clock_;
    auto it = decoders_.find(path);
    if (it == decoders_.end()) {
        DecoderEntry entry;
        entry.decoder = std::make_unique<Decoder>(path, width_, height_);
        entry.last_used = decoder_use_clock_;
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

std::vector<std::uint8_t> Renderer::render_layer(const Layer& layer, double shot_time, double now) {
    const double span = std::max(0.001, layer.source_end - layer.source_start);
    const double elapsed = std::max(0.0, now - shot_time);
    double offset = std::fmod(elapsed * std::max(0.01, layer.transform.playback_rate), span);
    if (offset < 0.0) offset += span;
    double target = layer.source_start + offset;
    if (layer.transform.reverse) target = layer.source_end - offset;
    target = std::clamp(target, layer.source_start, std::max(layer.source_start, layer.source_end - 0.001));

    auto frame = decoder_for(layer.path).frame_at(target);
    apply_transform(frame, width_, height_, layer.transform, static_cast<std::uint64_t>(std::llround(now * fps_)));
    return frame;
}

std::vector<std::uint8_t> Renderer::render_shot(const Shot& shot, double now) {
    auto output = render_layer(shot.primary, shot.time, now);
    if (shot.primary.opacity < 0.999) {
        for (auto& c : output) c = static_cast<std::uint8_t>(c * std::clamp(shot.primary.opacity, 0.0, 1.0));
    }

    std::vector<std::uint8_t> portal_companion;
    bool have_portal_companion = false;
    for (const auto& layer : shot.companions) {
        auto companion = render_layer(layer, shot.time, now);
        if (!have_portal_companion) {
            portal_companion = companion;
            have_portal_companion = true;
        }
        blend_layer(output, companion, layer.opacity, layer.blend_mode);
    }

    const double progress = std::clamp(
        (now - shot.time) / std::max(0.001, shot.timeline_end - shot.time),
        0.0, 1.0
    );
    apply_vector_effects(
        output,
        have_portal_companion ? &portal_companion : nullptr,
        previous_output_.empty() ? nullptr : &previous_output_,
        width_,
        height_,
        shot.vector_effects,
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
              << "\tthreads=" << threads_;
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

        auto output = render_shot(*shot, now);
        apply_reactive_effects(output, width_, height_, reactive_, now * 0.24);

        if (shot_index != previous_shot_index_ && shot->crossfade > 0.0 && frame_index > 0 && !previous_output_.empty()) {
            // Freeze-frame crossfade for Phase 1. Phase 2 keeps the outgoing
            // decoder alive and performs GPU texture crossfades.
            const double progress = std::clamp((now - shot->time) / shot->crossfade, 0.0, 1.0);
            crossfade(output, previous_output_, progress);
        }

        if (std::fwrite(output.data(), 1, frame_bytes, stdout) != frame_bytes) {
            return 2;
        }
        previous_output_ = output;
        previous_shot_index_ = shot_index;

        if (frame_index == 0 || frame_index + 1 == total_frames || (frame_index + 1) % std::max<std::uint64_t>(1, static_cast<std::uint64_t>(fps_)) == 0) {
            std::cerr << "PROGRESS\t" << (frame_index + 1) << '\t' << total_frames << '\n';
        }
    }
    std::fflush(stdout);
    return 0;
}

} // namespace tubeviz
