// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/decoder.hpp"

#include <algorithm>
#include <cmath>
#include <new>
#include <stdexcept>

extern "C" {
#include <libavutil/dict.h>
#include <libavutil/error.h>
#include <libavutil/imgutils.h>
#include <libavutil/pixdesc.h>
}

namespace tubeviz {
namespace {

std::string av_error(int code) {
    char buffer[AV_ERROR_MAX_STRING_SIZE]{};
    av_strerror(code, buffer, sizeof(buffer));
    return buffer;
}

struct SharedCudaDevice {
    AVBufferRef* ref{nullptr};

    SharedCudaDevice() {
        AVDictionary* options = nullptr;
        av_dict_set(&options, "primary_ctx", "1", 0);
        const int rc = av_hwdevice_ctx_create(&ref, AV_HWDEVICE_TYPE_CUDA, nullptr, options, 0);
        av_dict_free(&options);
        if (rc < 0) ref = nullptr;
    }

    ~SharedCudaDevice() { av_buffer_unref(&ref); }
};

AVBufferRef* shared_cuda_device() {
    static SharedCudaDevice device;
    return device.ref;
}

} // namespace

AVPixelFormat Decoder::select_hw_format(AVCodecContext* context, const AVPixelFormat* formats) {
    auto* self = static_cast<Decoder*>(context->opaque);
    if (!self) return formats[0];
    for (const AVPixelFormat* fmt = formats; *fmt != AV_PIX_FMT_NONE; ++fmt) {
        if (*fmt == self->hw_pixel_format_) return *fmt;
    }
    for (const AVPixelFormat* fmt = formats; *fmt != AV_PIX_FMT_NONE; ++fmt) {
        const AVPixFmtDescriptor* desc = av_pix_fmt_desc_get(*fmt);
        if (!desc || !(desc->flags & AV_PIX_FMT_FLAG_HWACCEL)) return *fmt;
    }
    return formats[0];
}

Decoder::Decoder(std::string path, int output_width, int output_height, std::string hwdecode)
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

    auto alloc_codec = [&]() {
        codec_ = avcodec_alloc_context3(decoder);
        if (!codec_) throw std::bad_alloc();
        const int copy_rc = avcodec_parameters_to_context(codec_, stream->codecpar);
        if (copy_rc < 0) throw std::runtime_error("avcodec_parameters_to_context: " + av_error(copy_rc));
        codec_->thread_count = 0;
        codec_->thread_type = FF_THREAD_FRAME | FF_THREAD_SLICE;
    };
    alloc_codec();

    const bool want_cuda = hwdecode == "auto" || hwdecode == "cuda" || hwdecode == "nvdec";
    if (want_cuda) {
        for (int i = 0;; ++i) {
            const AVCodecHWConfig* config = avcodec_get_hw_config(decoder, i);
            if (!config) break;
            if ((config->methods & AV_CODEC_HW_CONFIG_METHOD_HW_DEVICE_CTX) &&
                config->device_type == AV_HWDEVICE_TYPE_CUDA) {
                hw_pixel_format_ = config->pix_fmt;
                break;
            }
        }
        if (hw_pixel_format_ != AV_PIX_FMT_NONE) {
            if (AVBufferRef* shared = shared_cuda_device()) {
                hw_device_ctx_ = av_buffer_ref(shared);
                if (hw_device_ctx_) {
                    codec_->opaque = this;
                    codec_->get_format = &Decoder::select_hw_format;
                    codec_->hw_device_ctx = av_buffer_ref(hw_device_ctx_);
                    hardware_decode_ = codec_->hw_device_ctx != nullptr;
                    if (hardware_decode_) hardware_backend_ = "cuda/nvdec";
                }
            }
        }
    }

    rc = avcodec_open2(codec_, decoder, nullptr);
    if (rc < 0 && hardware_decode_) {
        avcodec_free_context(&codec_);
        av_buffer_unref(&hw_device_ctx_);
        hw_pixel_format_ = AV_PIX_FMT_NONE;
        hardware_decode_ = false;
        hardware_backend_ = "software";
        alloc_codec();
        rc = avcodec_open2(codec_, decoder, nullptr);
    }
    if (rc < 0) throw std::runtime_error("avcodec_open2(" + path_ + "): " + av_error(rc));

    frame_ = av_frame_alloc();
    held_frame_ = av_frame_alloc();
    software_frame_ = av_frame_alloc();
    packet_ = av_packet_alloc();
    if (!frame_ || !held_frame_ || !software_frame_ || !packet_) throw std::bad_alloc();
    rgb_.resize(static_cast<std::size_t>(output_width_) * output_height_ * 3);
}

Decoder::~Decoder() {
    sws_freeContext(sws_);
    av_packet_free(&packet_);
    av_frame_free(&software_frame_);
    av_frame_free(&held_frame_);
    av_frame_free(&frame_);
    avcodec_free_context(&codec_);
    av_buffer_unref(&hw_device_ctx_);
    avformat_close_input(&format_);
}

void Decoder::seek(double seconds) {
    const auto timestamp = static_cast<std::int64_t>(seconds / av_q2d(time_base_));
    const int rc = av_seek_frame(format_, stream_index_, timestamp, AVSEEK_FLAG_BACKWARD);
    if (rc < 0) throw std::runtime_error("av_seek_frame(" + path_ + "): " + av_error(rc));
    avcodec_flush_buffers(codec_);
    av_frame_unref(frame_);
    av_frame_unref(held_frame_);
    av_frame_unref(software_frame_);
    current_seconds_ = -1.0;
    rgb_valid_ = false;
    eof_ = false;
}

double Decoder::frame_seconds(const AVFrame* frame) const {
    std::int64_t pts = frame->best_effort_timestamp;
    if (pts == AV_NOPTS_VALUE) pts = frame->pts;
    if (pts == AV_NOPTS_VALUE) return current_seconds_ < 0.0 ? 0.0 : current_seconds_;
    return static_cast<double>(pts) * av_q2d(time_base_);
}

void Decoder::hold_frame(AVFrame* frame) {
    const double seconds = frame_seconds(frame);
    av_frame_unref(held_frame_);
    const int rc = av_frame_ref(held_frame_, frame);
    if (rc < 0) throw std::runtime_error("av_frame_ref(" + path_ + "): " + av_error(rc));
    current_seconds_ = seconds;
    rgb_valid_ = false;
}

void Decoder::convert_held_frame() {
    if (!held_frame_ || held_frame_->format == AV_PIX_FMT_NONE)
        throw std::runtime_error("no decoded frame available for " + path_);

    AVFrame* source = held_frame_;
    if (hardware_decode_ && static_cast<AVPixelFormat>(held_frame_->format) == hw_pixel_format_) {
        av_frame_unref(software_frame_);
        const int rc = av_hwframe_transfer_data(software_frame_, held_frame_, 0);
        if (rc < 0) throw std::runtime_error("av_hwframe_transfer_data(" + path_ + "): " + av_error(rc));
        source = software_frame_;
    }

    sws_ = sws_getCachedContext(
        sws_,
        source->width, source->height, static_cast<AVPixelFormat>(source->format),
        output_width_, output_height_, AV_PIX_FMT_RGB24,
        SWS_FAST_BILINEAR, nullptr, nullptr, nullptr
    );
    if (!sws_) throw std::runtime_error("sws_getCachedContext failed for " + path_);

    std::uint8_t* dst_data[4] = {rgb_.data(), nullptr, nullptr, nullptr};
    int dst_linesize[4] = {output_width_ * 3, 0, 0, 0};
    sws_scale(sws_, source->data, source->linesize, 0, source->height, dst_data, dst_linesize);
    rgb_valid_ = true;
}

bool Decoder::decode_until(double target_seconds) {
    while (true) {
        int rc = avcodec_receive_frame(codec_, frame_);
        if (rc == 0) {
            hold_frame(frame_);
            av_frame_unref(frame_);
            if (current_seconds_ + 1e-4 >= target_seconds) return true;
            continue;
        }
        if (rc != AVERROR(EAGAIN) && rc != AVERROR_EOF)
            throw std::runtime_error("avcodec_receive_frame(" + path_ + "): " + av_error(rc));
        if (rc == AVERROR_EOF) return current_seconds_ >= 0.0;

        while (true) {
            rc = av_read_frame(format_, packet_);
            if (rc < 0) {
                const int flush_rc = avcodec_send_packet(codec_, nullptr);
                if (flush_rc < 0 && flush_rc != AVERROR_EOF)
                    throw std::runtime_error("avcodec_send_packet(flush," + path_ + "): " + av_error(flush_rc));
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
        if (eof_) {
            while (true) {
                const int drain = avcodec_receive_frame(codec_, frame_);
                if (drain != 0) return current_seconds_ >= 0.0;
                hold_frame(frame_);
                av_frame_unref(frame_);
                if (current_seconds_ + 1e-4 >= target_seconds) return true;
            }
        }
    }
}

const AVFrame* Decoder::avframe_at(double seconds) {
    seconds = std::max(0.0, seconds);
    if (current_seconds_ >= 0.0 && held_frame_->format != AV_PIX_FMT_NONE &&
        seconds <= current_seconds_ + 1e-4 && seconds + 0.04 >= current_seconds_) {
        return held_frame_;
    }
    if (current_seconds_ < 0.0 || seconds + 0.04 < current_seconds_ || seconds - current_seconds_ > 2.0)
        seek(seconds);
    if (!decode_until(seconds) || held_frame_->format == AV_PIX_FMT_NONE)
        throw std::runtime_error("failed to decode frame from " + path_);
    return held_frame_;
}

const std::vector<std::uint8_t>& Decoder::frame_at(double seconds) {
    avframe_at(seconds);
    if (!rgb_valid_) convert_held_frame();
    return rgb_;
}

} // namespace tubeviz
