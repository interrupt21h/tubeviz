#include "tubeviz/manifest.hpp"
#include "tubeviz/renderer.hpp"

#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>

namespace {

struct Args {
    std::string manifest;
    int width{1920};
    int height{1080};
    double fps{60.0};
};

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
        else if (key == "--version") {
#ifdef TUBEVIZ_HAVE_PLACEBO
            std::cout << "tubeviz-native-render 0.19.0 ffmpeg+libplacebo\n";
#else
            std::cout << "tubeviz-native-render 0.19.0 ffmpeg\n";
#endif
            std::exit(0);
        } else if (key == "--help" || key == "-h") {
            std::cout << "usage: tubeviz-native-render --manifest FILE --width W --height H --fps FPS\n";
            std::exit(0);
        } else {
            throw std::runtime_error("unknown argument: " + key);
        }
    }
    if (args.manifest.empty()) throw std::runtime_error("--manifest is required");
    if (args.width <= 0 || args.height <= 0 || args.fps <= 0.0) throw std::runtime_error("invalid output geometry/fps");
    return args;
}

} // namespace

int main(int argc, char** argv) {
    try {
        const auto args = parse_args(argc, argv);
        auto manifest = tubeviz::load_manifest(args.manifest);
        tubeviz::Renderer renderer(std::move(manifest), args.width, args.height, args.fps);
        return renderer.run();
    } catch (const std::exception& exc) {
        std::cerr << "ERROR\t" << exc.what() << '\n';
        return 1;
    }
}
