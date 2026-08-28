// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/renderer.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <new>
#include <set>
#include <stdexcept>
#include <thread>

#ifdef TUBEVIZ_HAVE_OPENMP
#include <omp.h>
#endif

namespace tubeviz {
namespace {

using Clock = std::chrono::steady_clock;

double elapsed_ms(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

bool temporal_hero(const CreativeEffect& c) {
    return c.hero_kind == "flow_melt" || c.hero_kind == "subject_echo" ||
           c.hero_kind == "time_prism" || c.hero_kind == "recursive_portal";
}

bool gpu_mode_enabled(const std::string& mode) {
    return mode != "off" && mode != "none" && mode != "cpu";
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
    resident_ = std::make_unique<ResidentGpuPipeline>(width_, height_, gpu_mode_);
    if (!resident_->available()) {
        gpu_ = std::make_unique<GpuPostProcessor>(width_, height_, gpu_mode_);
    }
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
    decoder_for(shot.primary.path);
    for (const auto& layer : shot.companions) decoder_for(layer.path);
}

void Renderer::trim_decoders(const Shot& shot) {
    if (decoders_.size() <= decoder_cache_limit_) return;

    std::set<std::string> protected_paths{shot.primary.path};
    for (const auto& layer : shot.companions) protected_paths.insert(layer.path);

    while (decoders_.size() > decoder_cache_limit_) {
        auto victim = decoders_.end();
        for (auto it = decoders_.begin(); it != decoders_.end(); ++it) {
            if (protected_paths.contains(it->first)) continue;
            if (victim == decoders_.end() || it->second.last_used < victim->second.last_used)
                victim = it;
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

double Renderer::layer_target(const Layer& layer, double shot_time, double now) const {
    const double span = std::max(0.001, layer.source_end - layer.source_start);
    const double elapsed = std::max(0.0, now - shot_time);
    double offset = std::fmod(elapsed * std::max(0.01, layer.transform.playback_rate), span);
    if (offset < 0.0) offset += span;
    double target = layer.source_start + offset;
    if (layer.transform.reverse) target = layer.source_end - offset;
    return std::clamp(target, layer.source_start, std::max(layer.source_start, layer.source_end - 0.001));
}

std::vector<std::uint8_t> Renderer::render_layer(const Layer& layer, double shot_time, double now, bool legacy_style) {
    auto frame = decoder_for(layer.path).frame_at(layer_target(layer, shot_time, now));
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
    std::vector<std::vector<std::uint8_t>> companion_frames;
    std::vector<double> companion_opacities;
    std::vector<std::string> companion_modes;
    companion_frames.reserve(shot.companions.size());
    for (const auto& layer : shot.companions) {
        auto companion = render_layer(layer, shot.time, now, legacy_style);
        if (!have_portal_companion) {
            portal_companion = companion;
            have_portal_companion = true;
        }
        companion_opacities.push_back(layer.opacity);
        companion_modes.push_back(layer.blend_mode);
        companion_frames.push_back(std::move(companion));
    }
    const double composition_progress = std::clamp(
        (now - shot.time) / std::max(0.001, shot.timeline_end - shot.time), 0.0, 1.0
    );
    const std::string effective_composition = reactive_.switcher > 0.08 ? "swap" : shot.composition_mode;
    compose_layers(
        output, companion_frames, companion_opacities, companion_modes,
        effective_composition, width_, height_, composition_progress, now * 0.24
    );

    color_reference_ = output;
    const double progress = composition_progress;
    const auto* previous = (has_previous_output_ && allow_previous_effects) ? &previous_output_ : nullptr;

    if (!gpu_ && gpu_mode_enabled(gpu_mode_))
        gpu_ = std::make_unique<GpuPostProcessor>(width_, height_, gpu_mode_);
    if (gpu_ && gpu_->available()) {
        gpu_frame_used_ = gpu_->apply_spatial(output, shot.creative, reactive_, progress, now * 0.24);
    }
    if (gpu_frame_used_) {
        apply_creative_temporal_effects(output, previous, width_, height_, shot.creative, progress, now * 0.24);
    } else {
        apply_creative_effects(output, previous, width_, height_, shot.creative, progress, now * 0.24);
    }

    auto post_transform = shot.primary.transform;
    post_transform.ripple = std::max(post_transform.ripple, reactive_.tempo_warp * .75);
    post_transform.tunnel = std::max({post_transform.tunnel, reactive_.tunnel, reactive_.punch * .65});
    post_transform.kaleidoscope = std::max(post_transform.kaleidoscope, reactive_.kaleidoscope);
    post_transform.edge = std::max(post_transform.edge, reactive_.edge);
    post_transform.strobe = std::max(post_transform.strobe, reactive_.strobe);
    post_transform.slit_scan = std::max(post_transform.slit_scan, reactive_.slit_scan);
    post_transform.frame_echo = std::max(post_transform.frame_echo, reactive_.echo);
    post_transform.mirror_corridor = std::max(post_transform.mirror_corridor, reactive_.corridor);
    post_transform.mask_wipe = std::max(post_transform.mask_wipe, reactive_.mask);
    post_transform.solarize = std::max(post_transform.solarize, reactive_.solarize);
    post_transform.datamosh = std::max(post_transform.datamosh, reactive_.datamosh);
    post_transform.motion_trails = std::max(post_transform.motion_trails, reactive_.motion_trails);
    post_transform.slice_recursion = std::max(post_transform.slice_recursion, reactive_.slice_recursion);
    post_transform.shutter = std::max(post_transform.shutter, reactive_.freeze);
    apply_post_transform_effects(output, previous, width_, height_, post_transform, progress, now * 0.24);

    auto vector_effects = shot.vector_effects;
    if (legacy_style) {
        vector_effects.erase(
            std::remove_if(vector_effects.begin(), vector_effects.end(), [](const VectorEffect& e) {
                return e.kind == "portal" && ((e.seed * 2654435761ULL + 71ULL) % 100ULL) < 90ULL;
            }), vector_effects.end()
        );
    }
    apply_vector_effects(
        output, have_portal_companion ? &portal_companion : nullptr, previous,
        width_, height_, vector_effects, progress, now * 0.24
    );
    return output;
}

bool Renderer::render_shot_resident(
    const Shot& shot,
    double now,
    bool allow_previous_effects,
    bool shot_changed,
    std::vector<std::uint8_t>& output,
    ResidentGpuTiming& timing,
    double& decode_ms
) {
    if (!resident_ || !resident_->available() || resident_disabled_ || shot.creative.style_version < 2)
        return false;

    const auto decode_start = Clock::now();
    std::vector<AVFrame*> owned;
    std::vector<ResidentLayerFrame> layers;
    owned.reserve(1 + shot.companions.size());
    layers.reserve(1 + shot.companions.size());

    auto append = [&](const Layer& layer) {
        const AVFrame* decoded = decoder_for(layer.path).avframe_at(layer_target(layer, shot.time, now));
        AVFrame* clone = av_frame_clone(decoded);
        if (!clone) throw std::bad_alloc();
        owned.push_back(clone);
        ResidentLayerFrame resident_layer;
        resident_layer.frame = clone;
        resident_layer.transform = &layer.transform;
        resident_layer.opacity = layer.opacity;
        resident_layer.blend_mode = layer.blend_mode;
        layers.push_back(std::move(resident_layer));
    };

    append(shot.primary);
    for (const auto& layer : shot.companions) append(layer);
    decode_ms = elapsed_ms(decode_start);

    auto post = shot.primary.transform;
    post.ripple = std::max(post.ripple, reactive_.tempo_warp * .75);
    post.tunnel = std::max({post.tunnel, reactive_.tunnel, reactive_.punch * .65});
    post.kaleidoscope = std::max(post.kaleidoscope, reactive_.kaleidoscope);
    post.edge = std::max(post.edge, reactive_.edge);
    post.strobe = std::max(post.strobe, reactive_.strobe);
    post.slit_scan = std::max(post.slit_scan, reactive_.slit_scan);
    post.frame_echo = std::max(post.frame_echo, reactive_.echo);
    post.mirror_corridor = std::max(post.mirror_corridor, reactive_.corridor);
    post.mask_wipe = std::max(post.mask_wipe, reactive_.mask);
    post.solarize = std::max(post.solarize, reactive_.solarize);
    post.datamosh = std::max(post.datamosh, reactive_.datamosh);
    post.motion_trails = std::max(post.motion_trails, reactive_.motion_trails);
    post.slice_recursion = std::max(post.slice_recursion, reactive_.slice_recursion);
    post.shutter = std::max(post.shutter, reactive_.freeze);

    const double progress = std::clamp(
        (now - shot.time) / std::max(0.001, shot.timeline_end - shot.time), 0.0, 1.0
    );
    double crossfade_history = 0.0;
    if (shot_changed && has_previous_output_ && shot.crossfade > 0.0) {
        const double q = std::clamp((now - shot.time) / shot.crossfade, 0.0, 1.0);
        crossfade_history = 1.0 - q;
    }
    const std::string composition = reactive_.switcher > 0.08 ? "swap" : shot.composition_mode;
    const bool ok = resident_->render(
        layers, composition, shot.creative, reactive_, post, shot.vector_effects,
        progress, now * 0.24, allow_previous_effects, crossfade_history, output, &timing
    );
    for (AVFrame* frame : owned) av_frame_free(&frame);
    return ok;
}

void Renderer::emit_perf(std::uint64_t frames) const {
    const double resident_n = std::max<std::uint64_t>(1, resident_frames_);
    const double fallback_n = std::max<std::uint64_t>(1, fallback_frames_);
    const double all_n = std::max<std::uint64_t>(1, frames);
    std::cerr
        << "PERF\tframes=" << frames
        << "\tresident=" << resident_frames_
        << "\tfallback=" << fallback_frames_
        << "\tdecode_ms=" << perf_decode_ms_ / resident_n
        << "\tmap_ms=" << perf_map_ms_ / resident_n
        << "\tcompose_ms=" << perf_compose_ms_ / resident_n
        << "\tfx_ms=" << perf_effects_ms_ / resident_n
        << "\tdownload_ms=" << perf_download_ms_ / resident_n
        << "\tcpu_ms=" << perf_cpu_ms_ / fallback_n
        << "\tpipe_ms=" << perf_pipe_ms_ / all_n
        << '\n';
}

int Renderer::run() {
    const std::uint64_t total_frames = static_cast<std::uint64_t>(std::ceil(manifest_.duration * fps_));
    std::size_t shot_index = 0;
    const auto frame_bytes = static_cast<std::size_t>(width_) * height_ * 3;

    std::cerr << "INFO\tdecoder_cache=" << decoder_cache_limit_
              << "\tthreads=" << threads_
              << "\thwdecode=" << hwdecode_mode_
              << "\tresident=" << (resident_ && resident_->available() ? resident_->backend() : "off")
              << "\tgpu_fallback=" << (gpu_ && gpu_->available() ? gpu_->backend() : "lazy");
#ifdef TUBEVIZ_HAVE_OPENMP
    std::cerr << "\topenmp=" << omp_get_max_threads();
#else
    std::cerr << "\topenmp=0";
#endif
    std::cerr << '\n';

    for (std::uint64_t frame_index = 0; frame_index < total_frames; ++frame_index) {
        const double now = static_cast<double>(frame_index) / fps_;
        reactive_.decay(fps_);
        while (cue_index_ < manifest_.cues.size() && manifest_.cues[cue_index_].time <= now + 1e-9)
            reactive_.apply(manifest_.cues[cue_index_++]);

        const Shot* shot = shot_at(now, shot_index);
        if (!shot) throw std::runtime_error("no shot at render time");
        if (shot_index != previous_shot_index_) {
            warm_shot(*shot);
            if (shot_index + 1 < manifest_.shots.size()) warm_shot(manifest_.shots[shot_index + 1]);
            trim_decoders(*shot);
        }

        const bool shot_changed = shot_index != previous_shot_index_;
        const bool allow_previous_effects = !shot_changed || temporal_hero(shot->creative) || shot->creative.history_inherit > 0.04;

        std::vector<std::uint8_t> output;
        ResidentGpuTiming resident_timing{};
        double decode_ms = 0.0;
        bool resident_ok = render_shot_resident(
            *shot, now, allow_previous_effects, shot_changed, output, resident_timing, decode_ms
        );

        // CUDA decode only helps when the hardware AVFrame can remain on the GPU.
        // If direct mapping is unavailable, auto mode switches once to software
        // decode and lets libplacebo upload native YUV directly. This avoids the
        // much worse CUDA -> RGB CPU -> Vulkan round trip.
        if (!resident_ok && resident_ && resident_->last_hardware_map_failed() && hwdecode_mode_ == "auto") {
            if (!resident_cuda_fallback_reported_) {
                std::cerr << "INFO\tresident CUDA/Vulkan mapping unavailable; retrying with software decode + GPU YUV upload\n";
                resident_cuda_fallback_reported_ = true;
            }
            decoders_.clear();
            hwdecode_mode_ = "off";
            resident_ok = render_shot_resident(
                *shot, now, allow_previous_effects, shot_changed, output, resident_timing, decode_ms
            );
        }

        if (resident_ok) {
            ++resident_frames_;
            perf_decode_ms_ += decode_ms;
            perf_map_ms_ += resident_timing.map_ms;
            perf_compose_ms_ += resident_timing.compose_ms;
            perf_effects_ms_ += resident_timing.effects_ms;
            perf_download_ms_ += resident_timing.download_ms;
        } else {
            if (resident_ && resident_->available() && !resident_disabled_ && shot->creative.style_version >= 2) {
                resident_disabled_ = true;
                std::cerr << "WARN\tresident GPU fast path failed; using validated CPU/hybrid fallback for remaining frames\n";
            }
            const auto cpu_start = Clock::now();
            output = render_shot(*shot, now, allow_previous_effects);
            if (!gpu_frame_used_) apply_reactive_effects(output, width_, height_, reactive_, now * 0.24);
            const double color_progress = std::clamp(
                (now - shot->time) / std::max(0.001, shot->timeline_end - shot->time), 0.0, 1.0
            );
            apply_source_color_fidelity(output, color_reference_, width_, height_, shot->creative, color_progress);
            if (shot_changed && shot->crossfade > 0.0 && frame_index > 0 && !previous_output_.empty()) {
                const double q = std::clamp((now - shot->time) / shot->crossfade, 0.0, 1.0);
                crossfade(output, previous_output_, q);
            }
            perf_cpu_ms_ += elapsed_ms(cpu_start);
            ++fallback_frames_;
        }

        const auto pipe_start = Clock::now();
        if (std::fwrite(output.data(), 1, frame_bytes, stdout) != frame_bytes) return 2;
        perf_pipe_ms_ += elapsed_ms(pipe_start);

        previous_output_.swap(output);
        has_previous_output_ = true;
        previous_shot_index_ = shot_index;

        const auto progress_period = std::max<std::uint64_t>(1, static_cast<std::uint64_t>(fps_));
        if (frame_index == 0 || frame_index + 1 == total_frames || (frame_index + 1) % progress_period == 0)
            std::cerr << "PROGRESS\t" << (frame_index + 1) << '\t' << total_frames << '\n';
        const auto perf_period = std::max<std::uint64_t>(1, static_cast<std::uint64_t>(fps_ * 5.0));
        if (frame_index + 1 == total_frames || (frame_index + 1) % perf_period == 0)
            emit_perf(frame_index + 1);
    }
    std::fflush(stdout);
    return 0;
}

} // namespace tubeviz
