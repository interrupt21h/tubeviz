// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/decoder.hpp"

#include <algorithm>
#include <cmath>
#include <new>
#include <stdexcept>

extern "C" {
#include <libavutil/error.h>
#include <libavutil/imgutils.h>
}

namespace tubeviz {
namespace {

std::string av_error(int code) {
    char buffer[AV_ERROR_MAX_STRING_SIZE]{};
    av_strerror(code, buffer, sizeof(buffer));
    return buffer;
}

} // namespace

Decoder::Decoder(std::string path, int output_width, int output_height)
    : path_(std::move(path)), output_width_(output_width), output_height_(output_height) {
    int rc = avformat_open_input(&format_, path_.c_str(), nullptr, nullptr);
    if (rc < 0) throw std::runtime_error("avformat_open_input(" + path_ + "): " + av_error(rc));
    rc = avformat_find_stream_info(format_, nullptr);
    if (rc < 0) throw std::runtime_error("avformat_find_stream_info(" + path_ + "): " + av_error(rc));

    stream_index_ = av_find_best_stream(format_, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
    if (stream_index_ < 0) throw std::runtime_error("no video stream in " + path_);
    AVStream* stream = format_->streams[stream_index_];
    time_base_ = stream->time_base;

    const AVCodec* decoder = avcodec_find_decoder(stream->codecpar->codec_id);
    if (!decoder) throw std::runtime_error("unsupported video codec in " + path_);
    codec_ = avcodec_alloc_context3(decoder);
    if (!codec_) throw std::bad_alloc();
    rc = avcodec_parameters_to_context(codec_, stream->codecpar);
    if (rc < 0) throw std::runtime_error("avcodec_parameters_to_context: " + av_error(rc));
    // Let libavcodec select the available worker count and use both frame and
    // slice threading when the codec supports them.
    codec_->thread_count = 0;
    codec_->thread_type = FF_THREAD_FRAME | FF_THREAD_SLICE;
    rc = avcodec_open2(codec_, decoder, nullptr);
    if (rc < 0) throw std::runtime_error("avcodec_open2(" + path_ + "): " + av_error(rc));

    frame_ = av_frame_alloc();
    packet_ = av_packet_alloc();
    if (!frame_ || !packet_) throw std::bad_alloc();
    rgb_.resize(static_cast<std::size_t>(output_width_) * output_height_ * 3);
}

Decoder::~Decoder() {
    sws_freeContext(sws_);
    av_packet_free(&packet_);
    av_frame_free(&frame_);
    avcodec_free_context(&codec_);
    avformat_close_input(&format_);
}

void Decoder::seek(double seconds) {
    const auto timestamp = static_cast<std::int64_t>(seconds / av_q2d(time_base_));
    const int rc = av_seek_frame(format_, stream_index_, timestamp, AVSEEK_FLAG_BACKWARD);
    if (rc < 0) throw std::runtime_error("av_seek_frame(" + path_ + "): " + av_error(rc));
    avcodec_flush_buffers(codec_);
    current_seconds_ = -1.0;
    eof_ = false;
}

double Decoder::frame_seconds(const AVFrame* frame) const {
    std::int64_t pts = frame->best_effort_timestamp;
    if (pts == AV_NOPTS_VALUE) pts = frame->pts;
    if (pts == AV_NOPTS_VALUE) return current_seconds_ < 0.0 ? 0.0 : current_seconds_;
    return static_cast<double>(pts) * av_q2d(time_base_);
}

void Decoder::convert_frame(AVFrame* frame) {
    sws_ = sws_getCachedContext(
        sws_,
        frame->width, frame->height, static_cast<AVPixelFormat>(frame->format),
        output_width_, output_height_, AV_PIX_FMT_RGB24,
        SWS_FAST_BILINEAR, nullptr, nullptr, nullptr
    );
    if (!sws_) throw std::runtime_error("sws_getCachedContext failed for " + path_);

    std::uint8_t* dst_data[4] = {rgb_.data(), nullptr, nullptr, nullptr};
    int dst_linesize[4] = {output_width_ * 3, 0, 0, 0};
    sws_scale(
        sws_, frame->data, frame->linesize, 0, frame->height,
        dst_data, dst_linesize
    );
}

bool Decoder::decode_until(double target_seconds) {
    while (true) {
        int rc = avcodec_receive_frame(codec_, frame_);
        if (rc == 0) {
            current_seconds_ = frame_seconds(frame_);
            convert_frame(frame_);
            av_frame_unref(frame_);
            if (current_seconds_ + 1e-4 >= target_seconds) return true;
            continue;
        }
        if (rc != AVERROR(EAGAIN) && rc != AVERROR_EOF) {
            throw std::runtime_error("avcodec_receive_frame(" + path_ + "): " + av_error(rc));
        }
        if (rc == AVERROR_EOF) return false;

        while (true) {
            rc = av_read_frame(format_, packet_);
            if (rc < 0) {
                const int flush_rc = avcodec_send_packet(codec_, nullptr);
                if (flush_rc < 0 && flush_rc != AVERROR_EOF) {
                    throw std::runtime_error("avcodec_send_packet(flush," + path_ + "): " + av_error(flush_rc));
                }
                eof_ = true;
                break;
            }
            if (packet_->stream_index != stream_index_) {
                av_packet_unref(packet_);
                continue;
            }
            rc = avcodec_send_packet(codec_, packet_);
            av_packet_unref(packet_);
            if (rc == AVERROR(EAGAIN)) break;
            if (rc < 0) throw std::runtime_error("avcodec_send_packet(" + path_ + "): " + av_error(rc));
            break;
        }
        // After sending the flush packet, loop once more through
        // avcodec_receive_frame so delayed decoder frames are drained.
        if (eof_) {
            int drain = avcodec_receive_frame(codec_, frame_);
            if (drain == 0) {
                current_seconds_ = frame_seconds(frame_);
                convert_frame(frame_);
                av_frame_unref(frame_);
                if (current_seconds_ + 1e-4 >= target_seconds) return true;
                continue;
            }
            return current_seconds_ >= 0.0;
        }
    }
}

const std::vector<std::uint8_t>& Decoder::frame_at(double seconds) {
    if (seconds < 0.0) seconds = 0.0;

    // Critical fast path: output FPS is commonly higher than source FPS. If
    // the already-decoded frame covers this requested time, reuse it instead
    // of decoding another compressed frame. The old Phase-1 implementation
    // accidentally decoded one source frame for every output frame.
    if (current_seconds_ >= 0.0 &&
        seconds <= current_seconds_ + 1e-4 &&
        seconds + 0.04 >= current_seconds_) {
        return rgb_;
    }

    // Seeking backward or making a large discontinuous jump is exceptional.
    if (current_seconds_ < 0.0 ||
        seconds + 0.04 < current_seconds_ ||
        seconds - current_seconds_ > 2.0) {
        seek(seconds);
    }

    if (!decode_until(seconds) && rgb_.empty()) {
        throw std::runtime_error("failed to decode frame from " + path_);
    }
    return rgb_;
}

} // namespace tubeviz
