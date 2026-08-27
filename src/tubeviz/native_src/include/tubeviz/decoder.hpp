// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <libswscale/swscale.h>
}

namespace tubeviz {

class Decoder {
public:
    Decoder(std::string path, int output_width, int output_height, std::string hwdecode = "auto");
    ~Decoder();

    Decoder(const Decoder&) = delete;
    Decoder& operator=(const Decoder&) = delete;

    void seek(double seconds);
    const std::vector<std::uint8_t>& frame_at(double seconds);
    const std::string& path() const noexcept { return path_; }
    bool hardware_decode() const noexcept { return hardware_decode_; }
    const std::string& hardware_backend() const noexcept { return hardware_backend_; }

private:
    static AVPixelFormat select_hw_format(AVCodecContext* context, const AVPixelFormat* formats);
    bool decode_until(double target_seconds);
    void convert_frame(AVFrame* frame);
    double frame_seconds(const AVFrame* frame) const;

    std::string path_;
    int output_width_{};
    int output_height_{};

    AVFormatContext* format_{nullptr};
    AVCodecContext* codec_{nullptr};
    AVFrame* frame_{nullptr};
    AVFrame* software_frame_{nullptr};
    AVPacket* packet_{nullptr};
    AVBufferRef* hw_device_ctx_{nullptr};
    AVPixelFormat hw_pixel_format_{AV_PIX_FMT_NONE};
    bool hardware_decode_{false};
    std::string hardware_backend_{"software"};
    SwsContext* sws_{nullptr};
    int stream_index_{-1};
    AVRational time_base_{};
    double current_seconds_{-1.0};
    bool eof_{false};

    std::vector<std::uint8_t> rgb_;
};

} // namespace tubeviz
