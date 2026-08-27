// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/manifest.hpp"
#include "tubeviz/renderer.hpp"

#include <cstdlib>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

struct Args {
    std::string manifest;
    int width{1920};
    int height{1080};
    double fps{60.0};
    std::size_t decoder_cache{16};
    int threads{0};
    std::string gpu{"auto"};
    std::string hwdecode{"auto"};
};

bool one_of(const std::string& value, std::initializer_list<const char*> choices) {
    for (const char* choice : choices) if (value == choice) return true;
    return false;
}

Args parse_args(int argc, char** argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        const std::string key = argv[i];
        auto value = [&]() -> std::string {
            if (i + 1 >= argc) throw std::runtime_error("missing value for " + key);
            return argv[++i];
        };
        if (key == "--manifest") args.manifest = value();
        else if (key == "--width") args.width = std::stoi(value());
        else if (key == "--height") args.height = std::stoi(value());
        else if (key == "--fps") args.fps = std::stod(value());
        else if (key == "--decoder-cache") args.decoder_cache = static_cast<std::size_t>(std::stoul(value()));
        else if (key == "--threads") args.threads = std::stoi(value());
        else if (key == "--gpu") args.gpu = value();
        else if (key == "--hwdecode") args.hwdecode = value();
        else if (key == "--version") {
#ifdef TUBEVIZ_HAVE_PLACEBO
            std::cout << "tubeviz-native-render 0.40.1 ffmpeg+vulkan/libplacebo";
#else
            std::cout << "tubeviz-native-render 0.40.1 ffmpeg";
#endif
#ifdef TUBEVIZ_HAVE_OPENMP
            std::cout << "+openmp";
#endif
            std::cout << "+cuda-hwdecode\n";
            std::exit(0);
        } else if (key == "--help" || key == "-h") {
            std::cout
                << "usage: tubeviz-native-render --manifest FILE --width W --height H --fps FPS "
                   "[--decoder-cache N] [--threads N] [--gpu auto|vulkan|off] "
                   "[--hwdecode auto|cuda|off]\n";
            std::exit(0);
        } else {
            throw std::runtime_error("unknown argument: " + key);
        }
    }
    if (args.manifest.empty()) throw std::runtime_error("--manifest is required");
    if (args.width <= 0 || args.height <= 0 || args.fps <= 0.0) throw std::runtime_error("invalid output geometry/fps");
    if (args.threads < 0) throw std::runtime_error("--threads must be >= 0");
    if (!one_of(args.gpu, {"auto", "vulkan", "off", "none", "cpu"}))
        throw std::runtime_error("--gpu must be auto, vulkan, or off");
    if (!one_of(args.hwdecode, {"auto", "cuda", "nvdec", "off", "none", "cpu"}))
        throw std::runtime_error("--hwdecode must be auto, cuda, or off");
    return args;
}

} // namespace

int main(int argc, char** argv) {
    try {
        const auto args = parse_args(argc, argv);
        auto manifest = tubeviz::load_manifest(args.manifest);
        tubeviz::Renderer renderer(
            std::move(manifest),
            args.width,
            args.height,
            args.fps,
            args.decoder_cache,
            args.threads,
            args.gpu,
            args.hwdecode
        );
        return renderer.run();
    } catch (const std::exception& exc) {
        std::cerr << "ERROR\t" << exc.what() << '\n';
        return 1;
    }
}
