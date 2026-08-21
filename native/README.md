# tubeviz native renderer

This is the Phase-1 native rendering backend introduced in tubeviz 0.19.

It intentionally moves media scheduling/decode out of Chrome first:

- C++20 frame scheduler
- FFmpeg/libavformat/libavcodec sequential video decode
- FFmpeg/libswscale conversion directly to the requested RGB output size
- multiple simultaneous source layers
- screen/multiply/overlay/lighten software blending
- source-level mirror/color/grayscale/noise/scanline/vignette transforms
- music-reactive beat warp, ripple, chromatic displacement, bloom and harmonic response
- raw RGB24 stdout for direct FFmpeg encoding; no PNG/JPEG or browser screenshot stage

libplacebo is detected at build time and linked when available, but the Phase-1
renderer remains software-composited. `shaders/beat_warp.glsl` is the first
custom-shader prototype for the Phase-2 Vulkan/libplacebo backend.

## Build

Debian/Ubuntu packages:

```bash
sudo apt install build-essential cmake pkg-config \
  libavformat-dev libavcodec-dev libavutil-dev libswscale-dev
```

Optional Phase-2 dependency:

```bash
sudo apt install libplacebo-dev libvulkan-dev
```

Then:

```bash
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native -j
```

Or use:

```bash
tubeviz native build
```
