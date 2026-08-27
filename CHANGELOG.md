# 0.38.1 — WebGPU preview validation fixes

- Fix the fused WGSL compositor failing to compile in current Chrome/Dawn because `target` is a reserved WGSL keyword; rename the local depth focal-point variable without changing the shader behavior.
- Create textures used as destinations of `GPUQueue.copyExternalImageToTexture()` with `RENDER_ATTACHMENT` in addition to `TEXTURE_BINDING | COPY_DST`, matching current WebGPU validation requirements.
- Store temporal history in the canvas preferred format instead of hard-coded `rgba8unorm`, keeping the swap-chain-to-history `copyTextureToTexture()` copy format-compatible on platforms whose preferred canvas format is `bgra8unorm`.
- Build the render pipeline asynchronously and inspect WGSL compilation diagnostics before declaring WebGPU available. Shader/pipeline failures now become normal initialization errors so preview can fall back to Canvas2D instead of creating contagious invalid GPU objects and flooding DevTools. Track later uncaptured GPU validation errors as renderer failures so live preview can fall back on the following frame instead of remaining stuck on a broken GPU path.
- Add WebGPU regression coverage for the reserved-keyword fix, external-image texture usage flags, history texture format, and asynchronous shader/pipeline validation path.

# 0.38.0 — Sequential WebCodecs pipeline and compressed-image removal

- Replace the v0.37 all-IDR `TVZ1` browser source cache with `TVZ2`, a normal-GOP Annex-B H.264 transport carrying explicit key/delta flags. Source `VideoDecoder`s now advance sequentially and only restart from the closest prior IDR when timeline access moves backwards, substantially reducing cache size and making hardware decoding behave like video decoding instead of independent still-frame decoding. Existing `TVZ1` caches remain readable.
- Keep key access units independently restartable by prepending the current SPS/PPS when needed, use a two-second GOP with B-frames disabled, attempt NVENC cache creation first, and retain ultrafast x264 fallback. Cache identity includes the transport version/GOP so old all-IDR files are never mistaken for the new layout.
- Move WebCodecs output encoding and `/ws/offline-render` backpressure into a dedicated `browser_encode_worker.js`. Offline rendering now separates source-decode workers, WebGPU composition, and output-codec/network work instead of servicing all codec callbacks on the page thread. Main-thread `VideoEncoder` remains an automatic compatibility fallback if worker encoding is unavailable.
- Remove PNG/JPEG browser frame export from offline rendering entirely. The non-WebCodecs compatibility path now sends tightly packed RGBA frames over the binary WebSocket and FFmpeg consumes `rawvideo`; there is no `canvas.toBlob()`, base64 frame API, PNG/JPEG image stream, or FFmpeg image decode in the browser render architecture. The old `frames` transport spelling is accepted only as a deprecated alias for `raw`.
- Expand the fused WebGPU compositor with pixelation, posterization, solarization, edge extraction, horizontal glitch, block displacement, VHS-style tracking, ripple/tempo deformation, slit-scan history, datamosh-like history blocks, motion trails, and frame echo. These effects no longer require their Canvas2D full-frame implementations when WebGPU is active.
- Keep temporal history GPU-resident for WebGPU shots. CPU half-resolution delay buffers are now updated only when a rare compatibility mask actually needs them, and the full-resolution Canvas2D history copy is skipped while the GPU compositor is active. Hero flow/depth/temporal behavior is folded into the fused GPU parameters where possible.
- Add regression coverage for TVZ2 key/delta packing, sequential worker decode wiring, encoder-worker ownership, raw-RGBA fallback, complete removal of image-compression transport, and the expanded WGSL effect set. Validate the new transport with a real FFmpeg H.264 encode/decode smoke test and validate raw fallback by encoding synthetic RGBA frames through FFmpeg.

# 0.37.2 — Complete audio-AI packaging

- Add `nnaudio==0.3.4` to the `audio-ai` optional dependency group in `pyproject.toml`, alongside PyTorch and Transformers. This makes `pip install -e '.[audio-ai]'` install the complete learned-audio runtime instead of relying on nnAudio to have been installed separately.
- Keep nnAudio out of the base dependency set so core ingest, library, preview, and rendering installs do not pull in the PyTorch stack unless audio AI is requested.
- Add repository-layout regression coverage for the nnAudio dependency and update the documented `audio-ai` extra contents.

# 0.37.1 — WebGPU preview reliability

- Fix live WebGPU preview initialization so the visible GPU canvas is never transferred to a worker until worker-side WebGPU has passed a real scratch-canvas probe. This preserves the main-thread WebGPU fallback; once `transferControlToOffscreen()` has run, the original canvas can no longer create a context.
- Use main-thread WebGPU for interactive preview by default. The preview compositor still executes pixel work on the GPU, but avoids transferring two `VideoFrame`s to a worker and synchronizing them on every displayed frame. The worker WebGPU path remains preferred for deterministic offline browser rendering.
- Add an end-to-end worker probe that checks secure-context access, `WorkerNavigator.gpu`, adapter/device creation, WGSL pipeline creation, external-image copies, rendering, and queue synchronization on a scratch `OffscreenCanvas` before the visible canvas is transferred.
- Make preview startup fail-safe: WebGPU initialization errors no longer abort the top-level visualizer module. Interactive preview falls back to Canvas2D and remains usable even when **Preview GPU** explicitly prefers WebGPU.
- Preserve strict `--browser-gpu webgpu` behavior for offline rendering: `tubevizOfflineInit()` fails with the actual WebGPU reason instead of silently rendering offline through Canvas2D.
- Add a GPU-worker frame watchdog and asynchronous device-loss propagation. A stalled/lost worker now restores the Canvas2D preview instead of freezing indefinitely on the last GPU frame.
- Add a visible renderer-status line to the preview HUD showing `WebGPU` vs `Canvas2D` and the initialization/fallback reason. This makes insecure-origin, unavailable-adapter, worker, shader, and device-loss problems diagnosable without opening DevTools.
- Clarify the Studio Preview GPU selector: WebGPU is preferred for interactive preview but falls back safely; the offline Browser GPU selector retains its strict WebGPU option.

# 0.37.0 — Browser WebCodecs source decode and worker WebGPU compositor

- Remove the normal offline browser renderer's per-output-frame `HTMLVideoElement.currentTime` seek cycle. The private render server now exposes `/api/offline-source/{scene_index}/{layer_index}`, which resolves the exact timeline media securely beneath the selected library and builds/reuses a content-addressed, frame-addressable H.264 source cache.
- Add the `TVZ1` browser source transport: FFmpeg samples only the requested scene range at render FPS, creates all-IDR Annex-B H.264 with AUD/SPS/PPS suitable for random WebCodecs access, packs independent access units, and stores them beneath `library/browser-webcodecs-cache/`. `h264_nvenc` is attempted first and `libx264` is the automatic fallback.
- Add `browser_source.js` plus a dedicated `browser_source_worker.js`. Offline source layers now prefer `VideoDecoder` with hardware acceleration, decode only the access unit needed for the requested timestamp, and transfer the resulting `VideoFrame` back to the compositor. Main-thread WebCodecs remains a fallback if module workers are unavailable; individual clips fall back to HTML video in `auto` mode.
- Look ahead one scene while the current shot renders and prepare the next scene transport serially in the background. The prewarm request cancels its response body after headers because the server-side content-addressed cache is already complete, avoiding an unnecessary duplicate in-browser buffer. Cached transport responses use `FileResponse`, so repeat renders stream the cache from disk instead of first reading the entire packed scene into Python memory.
- Add `--browser-source-decode auto|webcodecs|video` and expose the same control in Studio. `auto` prefers the worker WebCodecs path and retains HTML video compatibility; `webcodecs` makes decoder availability/cache preparation failures fatal for debugging.
- Move WebGPU command construction and the GPU canvas off the main thread with `transferControlToOffscreen()` and a dedicated module worker. Keep a main-thread WebGPU fallback where the canvas has not already transferred.
- Replace the small v0.36 finishing shader with a fused worker WGSL compositor for common full-frame work: source-relative warp/flow, pseudo-depth parallax, real RGB displacement, bloom/streak approximation, temporal feedback/history, restrained directed color/palette accents, final source-chroma fidelity, vignette, scanlines, and strobe.
- Add a persistent GPU history texture so feedback/temporal accumulation no longer depends on a full-resolution main-thread history copy for the migrated effect families. Rare local-symmetry/hero/vector/legacy effects stay on the compatibility compositor for deterministic parity and automatic fallback.
- When WebGPU is active, skip the corresponding Canvas2D implementations of directed color, spectral/chromatic displacement, common creative flow/depth/temporal/palette/feedback, bass/ripple warp, RGB/chroma delay, and final source-fidelity pass; pass their bounded automation values to the fused GPU shader instead.
- Preserve all v0.36 output fast paths: one in-page offline render sequence, binary render WebSocket, hardware-preferred WebCodecs H.264 output, direct Annex-B stream muxing, and binary PNG/JPEG fallback.
- Add validation for the source transport packer, independent SPS/PPS+IDR access units, decoder mode configuration, source-worker/GPU-worker assets, CLI/Studio propagation, and the existing browser render fallbacks. A real FFmpeg smoke test confirms the packed source transport can be unpacked and decoded as H.264.

## Compatibility and quality boundary

- Live interactive preview still uses normal `HTMLVideoElement` playback because browsers already schedule continuous media playback efficiently; the WebCodecs source worker is used for deterministic **offline** frame access where repeated exact seeks were pathological.
- The browser source transport is a high-quality temporary render cache, not a replacement for canonical library media. Deleting `library/browser-webcodecs-cache/` is safe; it will be regenerated on the next browser render.
- Complex semantic masks, vector drawing, codec-fallback simulations, and rare hero effects still execute on Canvas2D before the worker GPU pass. This keeps visual compatibility while the high-frequency/full-frame effect workload moves off the main thread.
- The final browser output path is still hybrid rather than a fully zero-copy `VideoDecoder → WebGPU external texture → VideoEncoder` graph. `VideoFrame` transfer removes the seek/decode bottleneck and WebGPU moves common effects off-thread; the remaining Canvas2D compatibility layer is the next boundary for future optimization.

# 0.36.0 — Browser rendering acceleration foundation

- Replace the browser offline renderer's per-frame Playwright `page.evaluate()` + base64 transport with a single in-page render loop and a dedicated binary WebSocket stream to the local render server.
- Add an `auto` WebCodecs transport that probes `VideoEncoder.isConfigSupported()` and, when H.264 is available, creates `VideoFrame`s directly from the composed canvas, asks Chrome to prefer hardware encoding, streams Annex-B H.264 access units, and lets FFmpeg copy/mux that stream with the original audio. This removes PNG/JPEG encoding, base64 conversion, per-frame browser RPC, and FFmpeg image decoding from the fast path.
- Keep a robust binary PNG/JPEG WebSocket fallback. `auto` retries the full render with this fallback if a browser advertises H.264 WebCodecs but fails during encoder initialization or use.
- Add `--browser-transport auto|webcodecs|frames`, `--browser-gpu auto|webgpu|off`, and `--webcodecs-bitrate`; expose the same controls in Studio. WebCodecs currently emits H.264, so non-H.264 output requests use the frame fallback.
- Add a real WebGPU finishing stage behind feature detection. The first GPU stage uses a high-performance adapter and a fused WGSL pass for simple full-frame finishing operations; Canvas2D remains the compatibility/reference compositor while more effect families migrate incrementally.
- Make interactive preview start at a 720p-class internal render target instead of blindly multiplying the viewport by `devicePixelRatio`. `preview=auto` adapts among approximately 540p, 720p and 1080p based on measured frame time; fixed `540p`, `720p`, `1080p` and `native` modes are also available.
- Drive live rendering from `HTMLVideoElement.requestVideoFrameCallback()` when a source is actively playing, so 24/30 fps media is not repeatedly reprocessed at a 60/120/144 Hz display refresh rate. Idle previews render at a low cadence instead of burning a full animation loop.
- Add Studio Preview quality and Preview GPU selectors and propagate them as query parameters when launching the managed preview.
- Add `/ws/offline-render` to the local FastAPI preview/render service for ordered binary browser output. The endpoint is only enabled for the private offline render server when a sink is supplied.
- Preserve the old `tubevizRenderFrame`, frame-export, Canvas2D and image2pipe APIs as fallbacks/backward-compatible debugging surfaces.
- Add regression coverage for WebCodecs muxing, browser acceleration CLI/Studio controls, binary WebSocket delivery, adaptive preview scheduling and WebGPU source presence.

## Current boundary

- v0.36.0 accelerates **browser output encoding/transport** and the first full-frame GPU finishing stage. Source media is still supplied through `HTMLVideoElement`; deterministic offline rendering still seeks those elements for exact source times. A future WebCodecs decoder/demux stage can remove that remaining seek-heavy bottleneck without changing the v0.36 transport protocol.
- The WebGPU stage is deliberately hybrid: complex temporal/vector/semantic Canvas2D effects remain unchanged for visual parity while low-risk full-frame work begins moving to WGSL.

# 0.35.0 — GPU-accelerated native rendering

- Turn the existing optional libplacebo detection into a real Vulkan render path. The native renderer now executes virtual-camera motion, flow/harmonic warping, pseudo-depth parallax, sparse local symmetry, RGB displacement, source-derived bloom/streaks, restrained palette/color direction, reactive beat treatment, and source-fidelity chroma anchoring in one fused libplacebo custom-shader pass.
- Keep temporal/history and vector operations on the CPU after the fused GPU pass so feedback, echoes, flow trails, codec/vector treatments, crossfades, and existing manifest behavior remain compatible. A per-frame GPU failure disables the Vulkan stage once and falls back to the complete CPU effect path for the remainder of the render.
- Add CUDA/NVDEC hardware decode selection (`--native-hwdecode auto|cuda|off`) through FFmpeg's hardware-device API. `auto` discovers a CUDA-capable decoder configuration per source and falls back transparently to software decode when the stream/driver cannot use it. Cached decoders request CUDA's primary device context to avoid creating an unrelated CUDA context for every source clip.
- Add native GPU selection (`--native-gpu auto|vulkan|off`) in the CLI and Studio Render panel. `auto` uses libplacebo/Vulkan when the library is built in and Vulkan initialization succeeds; otherwise rendering remains CPU-compatible.
- Prefer a renderable RGB8 libplacebo texture when the GPU exposes one, allowing direct RGB24 upload/download with no RGB↔RGBA staging conversion. Fall back to RGBA8 only when required by the Vulkan device. Enable asynchronous Vulkan transfer/compute queues when supported.
- Make libplacebo initialization strict-C++20 safe by constructing public parameter structs directly instead of invoking libplacebo's C compound-literal convenience macros. Vulkan uses libplacebo's documented default parameters, which retain asynchronous transfer/compute defaults.
- Share one FFmpeg CUDA hardware-device wrapper across the decoder cache with the CUDA primary context enabled, and make hardware-format fallback choose a genuine software pixel format rather than another unconfigured hwaccel format.
- Download direct RGB8 Vulkan output into a reusable staging buffer and swap it into the renderer only after a successful transfer, preserving a pristine CPU frame for automatic GPU failure fallback without adding another full-frame copy.
- Disable libplacebo's global `dynamic_constants` mode; tubeviz shader controls are explicitly dynamic uniforms, avoiding the documented specialization/performance penalty from making every renderer constant dynamic.
- Fuse shot-local brightness/contrast/saturation/hue/grayscale/noise, scanlines, and vignette into one OpenMP traversal instead of multiple full-HD passes.
- Remove a full-frame temporal-history copy by swapping the completed RGB buffer into `previous_output_` after it has been written to the encoder pipe.
- Add native diagnostics for renderer build features, FFmpeg hardware accelerators, CUDA decode advertisement, libplacebo buildability, and `nvidia-smi`. Native logs now report the selected Vulkan and per-decoder hardware backends.
- Preserve the existing raw-RGB FFmpeg/NVENC output contract and CPU vector/history stages for compatibility. v0.35.0 is therefore a hybrid GPU compositor rather than a CUDA/Vulkan-to-NVENC zero-copy pipeline; this avoids changing timeline/manifests or requiring CUDA-specific build headers.
- Add regression coverage for GPU/hardware-decode defaults, CLI/Studio propagation, CUDA decoder source wiring, libplacebo/CMake integration, and the previous-frame zero-copy swap.

# 0.34.0 — Resource-aware two-pass AI editing

- Upgrade the optional LLM director from a song-only treatment pass into a resource-aware two-pass directing system. Pass 1 now receives a compact manifest of the actual READY/output-pool library plus the renderer capabilities that are enabled for the run.
- Add `ai_resources.py` to summarize eligible clip/scene counts, AI/visual-feature coverage, dominant visual worlds and provenance terms, motion and palette distributions, representative real material, raster/temporal effects, vector primitives, codec-space effects, hero effects, composition modes, and renderer constraints.
- Include the resource manifest in the whole-song director cache key and prompt so an LLM cannot plan as though unavailable footage/effects exist. Persist the compact manifest in `DirectedTimeline.ai_resource_manifest` for auditability.
- Add a second bounded AI edit-consultant pass. For every musical section, tubeviz builds a small candidate slate from the strongest deterministic retrieval results across all shot positions and lets the LLM rank only those validated scene IDs. Invented IDs and unsupported treatment names are discarded.
- Let AI consultation consider the complete eligible output pool even when OpenCLIP semantic embeddings are disabled; metadata, stored vision descriptions, visual fingerprints and deterministic trajectory/effect scoring still form the candidate slate.
- Feed validated consultant preferences back into both greedy scene choice and multi-shot beam search as a soft bonus. Trim/duration rules, motif identity, scene/source cooldowns, novelty pressure, beat-aligned shot windows and media validity remain hard/deterministic.
- Permit the bounded consultant to suggest an existing effect family and at most one sparse hero treatment per musical section. The effect-family hint is applied before deterministic vector/creative planning so it changes the actual generated treatment rather than just timeline metadata.
- Persist per-shot `ai_consultant` provenance: validated preference IDs, whether the final selected scene was preferred, treatment hints and a short editorial reason.
- Add CLI controls `--[no-]ai-edit-consultant`, `--ai-consultant-candidates`, `--ai-consultant-weight`, and `--ai-consultant-max-completion-tokens`. The consultant is enabled by default when `--ai-director --library` is active and inherits the same AI Settings endpoint/model/key.
- Expose the bounded consultant, candidate-slate size and influence weight in Studio. Command Center receives the same flags automatically from argparse.
- Cache section consultations under the AI-director cache hierarchy and fall back cleanly to deterministic ranking if any consultation request fails.
- Add regression coverage for resource-manifest contents, whole-song prompt grounding, rejection of invented candidate IDs, bounded effect validation, cross-term/all-library consultant selection, CLI defaults and Studio argument propagation.

# 0.33.7 — Final source-chroma fidelity guard

- Make `source_fidelity` a whole-render contract rather than a setting used only by the directed color grade. Browser rendering now captures the composed source frame before post FX and re-anchors final hue/saturation toward that source after raster effects, while retaining effect-generated luminance and geometry.
- Add the same final chroma guard to the native renderer using YIQ chroma interpolation against the pre-FX composed source frame. This runs after native creative and vector effects, preventing additive feedback, temporal effects, portals, or other full-frame treatments from collapsing unrelated footage into one magenta palette.
- Reduce routine hue direction further: only about 10% of ordinary shots and 16% of peak shots request a hue bias, and non-color-directed shots keep saturation exactly neutral.
- Hero moments and explicit palette/hue treatments temporarily relax the chroma anchor, preserving intentional color design without allowing it to become the default look of every clip.
- Remove the remaining always-recurrent circular beat grammar: browser bass beat-warp no longer draws concentric clipped rings, and the native renderer no longer uses a radial ring envelope. Both now use a borderless full-frame breathing/push transform.
- Run the native source-chroma guard after reactive beat processing, closing the final path that could modify chroma after fidelity protection.
- Preserve source-derived vector accents in browser rendering by applying the final chroma guard before vector overlays; native vectors are included in the guard because they share the raster buffer and can occupy broad image regions.

# 0.33.6 — Visual treatment diversity and sparse masks

- Add `CreativeEffectPlan.style_version=2` so renderers can recognize the sparse-treatment grammar. Existing v0.33.0-v0.33.5 timelines load as legacy style 0 and receive renderer-time sparsity guards for hue, masks, symmetry, palette overlays, and portals; regenerating the timeline is recommended but no longer required to eliminate the old always-on look.
- Make hue grading optional per shot instead of inevitable: most shots now retain exactly the source hue, while active grades are source-relative and capped to a small ±14° range. AI hue requests are reduced to bounded accents rather than section-wide palette replacement.
- Reduce persistent saturation/chromatic steering and raise normal source fidelity so different library clips retain visibly different palettes. Palette propagation is now gated to a minority of shots instead of having a non-zero floor everywhere.
- Diversify effect families within a section using deterministic compatible variants. The section still establishes a coherent base vocabulary, but later shots no longer all inherit the exact same prismatic/liquid/etc. treatment.
- Make local symmetry genuinely sparse. The old planner left a non-zero symmetry value on nearly every shot; v0.33.6 schedules it only on a small deterministic subset and uses ellipse, polygon, or strip-shaped local regions rather than one repeated circular window.
- Make companion-video `portal` vector effects rare and remove `portal` as the first/default prismatic primitive. Browser and native vector priorities now favor footage-derived flow/voronoi/contour treatments first.
- Gate legacy kaleidoscope, mask-wipe, solarize, mirror-corridor, and vortex effects so they act as punctuation instead of persistent wallpaper. Mask wipes now vary among diagonal, diamond, irregular polygon, and occasional ellipse shapes.
- Remove local symmetry from the common `time_prism` hero treatment; it now uses temporal RGB/smear, displacement, and spectral/flow motion. `recursive_portal` remains the explicit rare symmetry/portal hero.
- Diversify native portal and local-symmetry masks to ellipse, diamond, rounded-rect/strip, and irregular variants rather than a universal circle, and tighten legacy native hue clamps.
- Add regression coverage for clean-hue shots, sparse symmetry/masks, rare portals, family diversity, and non-circular browser mask grammars.

# 0.33.5 — Source-faithful color and temporal rendering

- Replaced the browser renderer's fixed `hue-rotate(±105–125deg)`/`screen` chromatic overlays with true RGB-channel displacement using the source frame's real red, green, and blue samples. This covers prismatic shift, flow RGB, temporal RGB, chroma delay, RGB split, and treble beat-warp accents.
- Changed vibe color direction from absolute hue targets (which repeatedly drove euphoric/hypnotic footage toward purple/fuchsia) to small source-relative hue biases. AI target hues now act as bounded nudges rather than palette replacement.
- Removed duplicated `ColorDirection` hue/saturation/contrast/brightness from per-source transforms. Music-directed grading is now applied once after composition.
- Added per-shot `source_fidelity` to `CreativeEffectPlan`. Normal footage retains roughly 80–95% of its source color identity; rare hero moments may relax that briefly, while disabling Creative FX preserves the source completely.
- Added the same source-fidelity/post-composite color model to the native renderer and extended the native manifest by appending backward-compatible color fields.
- Ordinary scene changes now clear browser delay/feedback history and native previous-frame creative input. Cross-shot temporal inheritance is reserved for explicit temporal hero treatments such as `flow_melt`, `subject_echo`, `time_prism`, and `recursive_portal`.
- Native palette treatment is disabled when a scene has no source palette instead of falling back to an arbitrary synthetic color.
- Added regression tests for bounded source-relative hue direction, true-channel browser effects, source-fidelity scaling, and the extended native manifest.
- Aligned the Library-detail screenshot helper default with the documented `screenshots/screenshot-library-detail.png` filename.

# 0.33.4 — Robust Library card actions

- Fix Library **Play / Trim** buttons for clips whose titles contain double quotes or other characters that can terminate an inline HTML event-handler attribute. The visible failure happened on the quoted `She said:"..."` clip, making the bug look position-dependent.
- Remove dynamic clip titles, source IDs, and source names from inline JavaScript handlers on Library cards. Card actions now carry only a stable numeric `data-clip-index` and are dispatched through delegated `click`/`change` listeners.
- Apply the same safe dispatch path to Play / Trim, Reject/Restore, Edit tags, Delete, and output-pool toggles so user/YouTube metadata cannot corrupt card event bindings.
- Add a Studio regression test that forbids reintroducing inline dynamic clip-action handlers.

# 0.33.3 — Complete Library-detail screenshots

- Make `--tab library-details` capture the complete Library inspector by default, including all content below the modal's normal internal scrollbar.
- Fix full-detail capture structurally rather than by viewport size: the screenshot helper temporarily hides the underlying Studio chrome, returns the fixed modal overlay to normal document flow, removes the inspector max-height/overflow constraints, and lets the expanded inspector determine the full-page image height.
- Add a pre-capture clipping assertion comparing the inspector's `clientHeight` and `scrollHeight`, so future CSS changes fail loudly instead of silently producing a truncated documentation screenshot.
- Add `--viewport-details` for callers that explicitly want the normal scrollable on-screen presentation. Retain `--full-details` as a backward-compatible v0.33.2 flag; full-height mode no longer requires it.

# 0.33.2 — Library-detail screenshot capture

- Extend `scripts/screenshot_studio.py` with a first-class `--tab library-details` target that opens the Library, chooses a playable clip, opens its Play / Trim inspector, waits for trim/detail initialization, pauses playback on a representative frame, and captures the modal.
- Add `--clip-match` and `--clip-index` for deterministic clip selection, `--clip-time` for an exact captured playhead position, and `--full-details` for a full-height inspector capture including the complete AI metadata panel.
- Add a configurable `--height` viewport option while retaining the existing 1920×1080 defaults.
- Emit clear errors when no playable clip matches instead of silently capturing the Library grid.
- Document Library-detail screenshot examples in the README.

# 0.33.1 — Library trim workflow

- Move the non-destructive In/Out editor directly below the clip video in the Library detail modal, ahead of the much taller AI visual-analysis panel.
- Slightly reduce the modal video maximum height so the video, trim timeline, endpoint readouts, and primary trim controls remain visible together on typical desktop displays.
- Add a Studio regression test that locks the clip-detail ordering to video → In/Out editor → AI metadata.

# 0.33.0 — Semantic temporal creative renderer

- Added a first-class `CreativeEffectPlan` to every directed shot. The plan is a coherent visual state with independent automation curves rather than another collection of random per-frame filters.
- Added content- and motion-aware optical-flow deformation, motion-following chromatic separation, flow trails, temporal RGB memory, frame echo and slit/smear treatments.
- Added saliency-targeted virtual camera choreography. Camera push/pan behavior follows semantic focal points when available, scene motion direction, beat phase and section trajectory instead of always zooming around frame center.
- Upgraded OpenAI storyboard analysis to `tubeviz-storyboard-v2`, requesting per-scene normalized focal points, subject scale, depth hints, and foreground/background region descriptions. Existing AI metadata remains valid; re-analysis enriches camera/subject guidance.
- Added lightweight content-derived depth maps in browser and native renderers. Coarse luminance/color/perspective depth fields drive 2.5D parallax and atmospheric separation without introducing a mandatory depth-model dependency.
- Added semantic foreground preservation. AI person/face/text semantics, focal point, subject scale, radial continuity, and local source-color continuity protect recognizable subjects while allowing backgrounds to warp more aggressively.
- Added recursive target-centered feedback, source-derived bloom/light streaks, palette propagation, local focal-point symmetry, and background-only spatial movement.
- Added five sparse hero treatments — `subject_echo`, `flow_melt`, `depth_burst`, `time_prism`, and `recursive_portal` — selected deterministically from narrative role, musical section, semantics and effect family. Hero shots are globally budgeted and temporally spaced so they remain punctuation rather than constant visual noise.
- Added section/phrase envelopes for creative effects. Builds escalate, breakdowns breathe, pre-impact withholding creates headroom, and payoff shots front-load controlled impact.
- Extended the whole-song AI director schema with optional `creative_trajectory` curves (`abstraction`, `camera_energy`, `temporal`, `feedback`, `depth`, `flow`, `palette`). LLM intent is blended with deterministic audio/scene measurements rather than directly selecting filters.
- Added a shared browser/native creative manifest. Native manifests serialize per-channel four-sample trajectories, preserving different browser automation curves for flow, temporal memory, camera, depth, feedback, symmetry, source texture and palette. A compact common-envelope fallback remains parseable.
- Added native CPU implementations of virtual camera, content-derived depth/parallax, temporal channel delay/smear, optical-motion deformation, recursive feedback, local symmetry, source-derived texture, palette treatment and hero effects, with small-curve-tail skipping to limit CPU overhead.
- Added **Creative FX** enable and intensity controls to Studio and `--creative-effects/--no-creative-effects` plus `--creative-intensity` to `analyze`/`serve`. Creative rendering can be tuned independently from legacy transforms and vector scene-graph effects.
- Kept old timeline compatibility: timelines without `direction.creative` load with an inert default plan, and old native manifests without `CREATIVE` records continue to render.
- Added regression coverage for semantic focal targeting, subject protection, creative disable/intensity behavior, AI trajectory blending, deterministic/spaced hero scheduling, Studio argument forwarding, and extended native creative-manifest serialization.

# 0.32.1 — Single-source OpenAI configuration

- Made the **AI Settings** tab the single source of truth for the OpenAI base URL, model, and API key used by Studio workflows.
- Removed duplicate AI-director endpoint/model fields and the Acquisition Planner LLM credential/model block from the Create tab.
- Renamed the persisted model setting from the vision-specific `openai_vision_model` concept to shared `openai_model`; existing v0.31/v0.32 config files migrate transparently on load.
- OpenAI storyboard descriptions, acquisition/query planning, and whole-song AI directing now inherit the same saved model automatically.
- `tubeviz ingest --visual-brief` and `tubeviz analyze --ai-director` inherit the saved AI Settings endpoint/model when their CLI override flags are omitted.
- Retained `--ai-llm-*` and `--ai-director-*` flags as explicit one-off CLI overrides for custom/local OpenAI-compatible endpoints.
- Kept OpenAI credentials out of process argv and job history; saved secrets continue to be resolved from the protected user configuration/environment at request time.

# 0.32.0 — Conditional media preparation and accelerated compatibility proxies

- Removed unconditional full-video normalization from the default ingest path. `--media-prep auto` now probes downloaded media and directly reuses common browser/native-safe H.264/MP4, VP8/VP9/WebM, and AV1 MP4/WebM sources.
- Added `--media-prep source` for native-oriented workflows that never want an ingest transcode, and `--media-prep normalize` to explicitly retain homogeneous H.264 proxy behavior when desired.
- Changed compatibility-proxy width, height, and FPS defaults to `0`, which preserves downloaded source geometry and frame rate. A 1080p acquisition is no longer automatically reduced to 720p before later rendering.
- Added `--normalize-encoder auto|nvenc|x264`. Auto mode performs a live one-frame `h264_nvenc` capability test, prefers NVENC when it is actually usable, and falls back to libx264 if an auto-selected NVENC transcode fails at runtime.
- Added machine-readable FFmpeg `-progress` handling for required compatibility proxies. Studio now receives periodic elapsed/total/percentage output rather than appearing stalled throughout a long encode.
- Existing compatibility proxies are reused unless `--force` is supplied.
- Scene detection, thumbnails, visual-feature indexing, OpenCLIP classification/embeddings, AI descriptions, transforms, FFglitch processing, browser playback, and native rendering now accept ready media stored directly under `originals/` as well as legacy/proxied media under `normalized/`.
- Added a constrained `/originals` visualizer mount and explicit timeline `/originals/...` URLs; the complete library root is not exposed.
- Updated transform, codec-glitch, native-render, and browser fallback media resolution so direct-source timelines remain valid across preview, materialization, and final rendering.
- Preserved the existing SQLite schema for upgrade compatibility: the historical `normalized_path`/`normalized_sha256` columns now represent the canonical ready-media path/hash and may point at either `originals/` or `normalized/`.
- Fixed `library delete --keep-original` for direct-source clips so a shared ready-media/original path is never accidentally removed.
- Added Studio controls for media-preparation policy and proxy encoder. Manual ingest now labels proxy dimensions/FPS explicitly and defaults them to source-preserving zero values.
- Updated README architecture and ingest documentation to describe conditional preparation, source reuse, NVENC fallback, direct original-media serving, and the new CLI controls.
- Added regression tests for direct H.264/VP9/AV1 compatibility decisions, incompatible-media proxying, NVENC selection/fallback, direct-source native resolution, browser serving, and keep-original deletion semantics.

# 0.31.2 — Unified OpenAI credentials and scrollable live logs

- Make the OpenAI API key saved in Studio AI Settings the default credential for every Tubeviz request sent to `api.openai.com`, including storyboard/clip understanding, acquisition planning/query expansion, and whole-song AI directing.
- Keep explicit `TUBEVIZ_LLM_API_KEY` / CLI credentials as overrides for custom OpenAI-compatible endpoints while preventing the saved OpenAI key from being forwarded automatically to arbitrary third-party/local URLs.
- Keep AI-director secrets out of Studio child-process argv and job history; credentials are resolved at request time instead.
- Preserve the user's live-log scroll position while a job is running. Auto-follow now resumes only when the log is already at (or returned to) the bottom, and Studio retains the full 4,000-line in-memory job tail while polling.

# 0.31.1 — Visible AI library intelligence

- Show an AI-generated visual summary plus semantic and mood tags directly on each enhanced Library card.
- Add a structured AI analysis panel to the clip playback/trim viewer with subjects, actions, settings, camera language, palette, lighting, textures, risks, and normalized editing-utility meters.
- Align per-scene AI descriptions with detected scene timestamps and make scene rows seek the video for rapid verification.
- Retain the complete raw analysis in an expandable diagnostic view and add per-clip re-analysis from the inspector.
- Keep list responses compact by exposing only a curated AI summary while returning the complete metadata from the existing clip-detail endpoint.

# 0.31.0 — Persistent video-understanding workflow

- Add centralized, persistent AI settings and secure OpenAI/Hugging Face credential management.
- Add cached OpenAI storyboard descriptions for new and existing library clips.
- Integrate clip context and scene editing-utility metadata into final semantic scene selection.
- Add Studio and CLI library backfill workflows with per-clip progress.
- Migrate existing libraries in place to schema v7 without rewriting media.

# 0.30.3 — Structured download progress

- Connect yt-dlp's Python `progress_hooks` API to Tubeviz ingest progress.
- Report downloaded and total/estimated bytes, percentage, transfer rate, ETA, completion, and download errors in both CLI and Studio.
- Feed byte counters into Studio's existing determinate progress model instead of leaving downloads indefinitely animated.
- Throttle hook messages to two updates per second to keep logs responsive and readable.

# 0.30.2 — Bounded source resolution

- Default both minimum accepted source height and maximum downloaded source height to 1080p for search and manual URL ingestion.
- Add `--min-source-height` and `--max-source-height` to both ingest commands and expose them in the curated Studio forms and generated Command Center.
- Build yt-dlp format selectors from the requested height bounds instead of downloading unrestricted best-quality representations such as 4K before 720p normalization.
- Download video-only representations by default because Tubeviz discards source audio; request and merge a separate audio stream only with `--keep-audio`.
- Preserve direct finite HTTP format preference, bounded retries, fragment concurrency, and explicit fallback attempts.

# 0.30.1 — Live processing progress

- Added a first-class Studio progress panel with the current processing stage, elapsed time, determinate percentage/counts when available, ETA when reported, and an indeterminate animation for work whose total cannot be known.
- Parse existing render frames, semantic/visual indexes, CLAP windows, ingest terms/URLs, and codec materialization counters into structured job progress without removing their detailed log lines.
- Launch every Studio tubeviz child with Python unbuffered mode and `PYTHONUNBUFFERED=1`, so progress reaches the browser immediately instead of arriving in delayed blocks.
- Added explicit DSP, direction, scene-planning, and timeline-write messages to `tubeviz analyze`.
- Preserve the full live log below the progress panel for diagnostics and verbose yt-dlp/FFmpeg output.

# 0.30.0 — Library tags and temporary output pool

- Added persistent, editable user tags that are independent of ingest/search provenance terms.
- Added tag filtering and per-clip tag editing to Studio's Library cards.
- Added a non-destructive output pool: marking any ready clip temporarily restricts newly planned timelines to marked clips; clearing the pool restores the entire ready library.
- Added individual, visible-result, and tag-based bulk mark/unmark actions.
- Persisted the active pool in SQLite so Studio-launched analysis and replan child processes use the same selection.
- Added schema-v6 migration tables for tags, clip/tag membership, and output selection.
- Automatically remove manually rejected clips from the active output pool while leaving tags intact.
- Made native toolchain diagnostics report all expected library keys even when `pkg-config` or development packages are absent.

# 0.29.2 — Intuitive Studio ranges

- Reorganized README as evergreen product documentation: screenshot first, followed by sample videos, architecture, installation, workflows, and reference material.
- Removed duplicated release/change narratives from README; release notes and implementation-change history now live exclusively in CHANGELOG.md.
- Replaced ambiguous normalized numeric controls with bounded sliders for directing, effects, and acquisition-quality thresholds.
- Added live numeric readouts and human-readable endpoint/recommended-range labels.
- Kept element IDs and exact numeric values unchanged so CLI generation and saved workflows remain compatible.

# 0.29.1 — Manual URL semantic scene ingestion

- Manual YouTube URL ingest now automatically detects scenes, generates thumbnails, indexes temporal visual features, creates OpenCLIP scene embeddings, and assigns zero-shot semantic labels by default.
- Added semantic labels for crowd, dancing, nightlife, city, tunnels, transport, industrial, architecture, nature, water, abstract imagery, lights, human closeups, performance, moving POV, macro, space, fire, smoke, text-heavy footage, talking heads, and static presentations.
- Added Manual Ingest Studio controls for OpenCLIP device/model/weights and explicit opt-outs for semantic embeddings or scene classification.
- Semantic labels are persisted in each scene's visual-feature record so downstream tooling and future Studio inspection can reuse them without re-running inference.

## 0.29.0

- Replaced permissive preview dynamicness proxy with optical-flow motion coverage and temporal-diversity analysis.
- Added explicit hard gates for text occupancy, persistent text overlays, face dominance, motion coverage, temporal diversity, and aesthetic quality.
- Added OpenCV-based text-region detection without OCR and bundled face-dominance detection.
- Long videos now default to eight stratified randomized probes and a 45-second yt-dlp range around the strongest passing region rather than downloading a huge bounded chunk.
- Probe selection filters quality failures before ranking, so a flashy title card cannot win merely by having high pixel activity.
- Studio exposes every quality threshold and long-video excerpt length.
- Per-probe logs report the measurements responsible for acceptance/rejection.

# Changelog

## 0.28.2

- Make preview dynamicness a hard ingest gate via `--min-dynamic-score`, preventing semantic/theme similarity from rescuing nearly static footage.
- Reweight music-video fitness toward actual motion and motion entropy, with an explicit static-content penalty.
- Keep long finite YouTube search results eligible by default: probe randomized source windows, choose the strongest region, and download only a bounded range with yt-dlp.
- Add `--sample-long-videos` / `--no-sample-long-videos` and `--long-video-segment-attempts`.
- Reinterpret automatic-discovery `--hard-max-duration` as the maximum downloaded clip/segment duration when long-video sampling is enabled.
- Expose the new dynamic and long-source controls in Studio and Command Center.


## 0.28.1 - Visual brief planner and Studio version fix

- Fixed deterministic visual-brief fallback producing paragraph-sized YouTube searches.
- Added strict short-query normalization for deterministic and LLM acquisition plans.
- Negative concepts are kept out of YouTube queries and applied downstream as semantic rejection signals.
- Acquisition query count is now filled to the requested target when an LLM returns too few queries.
- Added Studio acquisition-planner endpoint/model/API-key controls; API keys are passed through `TUBEVIZ_LLM_API_KEY` rather than argv.
- Studio version now comes from `tubeviz.__version__` instead of stale hard-coded 0.27.0 values.
- Added regression tests for the Delilah-style long visual brief and LLM query shortfalls.

## 0.27.0

### Added

- Added phrase-level tension/build/drop/release trajectory analysis with anticipation, time-to-peak, pre-drop withholding, and continuous visual targets.
- Added multi-shot beam-search scene planning with configurable lookahead, beam width, candidate pool, trajectory weight, and transition anticipation weight.
- Added effect/footage compatibility scoring so transform families are matched to source motion/complexity rather than indiscriminately applied.
- Added persisted whole-song `visual_arc` and per-section trajectory metadata.
- Added `tubeviz choreography inspect` with text and JSON output.
- Added optional MERT (`m-a-p/MERT-v1-95M`) music-representation analysis for section novelty/velocity; MERT remains opt-in and uses the existing audio-AI dependency set.
- Added `tubeviz music-ai doctor`.
- Added soft preference learning from manually rejected clips using persisted visual features.
- Added curated Studio controls/help for choreography, sequence planning, MERT and preference-learning parameters; Command Center remains complete automatically.

### Changed

- Visual transform/vector/codec strength now follows phrase trajectory, including deliberate pre-drop restraint and impact amplification.
- The optional whole-song LLM director now receives trajectory metadata and explicit build/drop/release guidance.
- CLAP/OpenCLIP/MERT `auto` device resolution validates PyTorch's compiled CUDA architecture list against the detected GPU and falls back safely when incompatible.

## 0.26.10

### Fixed

- Replaced card-local CSS pseudo-element help bubbles with a document-level floating tooltip layer.
- Tooltips now escape card/section overflow clipping, remain above Studio panels, flip below controls near the top edge, and clamp to the viewport horizontally and vertically.
- Help remains keyboard accessible and can be dismissed with Escape.

## 0.26.9

### Fixed

- Added versioned Studio CSS/JavaScript URLs to prevent stale browser assets after upgrades.
- Added no-cache/no-store headers for Studio HTML and static assets.
- Added a visible Studio version badge so the running UI version can be verified immediately.
- Preserved the v0.26.8 credential reveal, full-width manual URL editor, and contextual help/tooltips.

## 0.26.8

### Fixed

- Fixed the Studio Hugging Face credential reveal control so a token typed into the session field can be reliably shown/hidden.
- Clarified that a server-side `HF_TOKEN` is intentionally never exposed to the browser; the reveal control applies only to a token entered in Studio.

### Changed

- Redesigned Manual YouTube URL Ingest around a full-width monospaced URL editor with live URL count, clear action, primary provenance/cookie settings, and collapsible advanced ingestion controls.
- Added contextual help/tooltips across Studio controls. Curated controls include detailed tubeviz-specific guidance and Command Center controls inherit the live `argparse` help/default/choice metadata.
- Added native browser `title`/accessibility descriptions in addition to visible `?` help affordances for keyboard and pointer users.

## 0.26.7

- Refreshed Studio Create UI into a cleaner source → direct → output workflow layout.
- Added an optional Hugging Face token field with environment-status detection.
- GUI-supplied Hugging Face tokens are injected only into child-process environment (`HF_TOKEN` and compatibility `HUGGING_FACE_HUB_TOKEN`), never command argv, metadata, or job logs.
- Blank token fields continue to inherit `HF_TOKEN`/`HUGGING_FACE_HUB_TOKEN` from the Studio server environment.

## 0.26.6

### Fixed

- Codec-glitch MP4 finalization now occurs on the local temporary filesystem rather than directly inside the library cache.
- Added automatic retry without `+faststart` when FFmpeg cannot reopen/shift the MP4 during moov-atom relocation.
- Codec cache publication now copies to a same-directory hidden file, fsyncs it, and atomically replaces the final cache path.
- Existing completed codec-glitch cache assets remain reusable when a later shot fails.

## 0.26.5

### Added

- Added a complete Studio **Command Center** generated directly from the current `argparse` command tree.
- Every non-GUI leaf CLI command and option is now configurable and launchable from Studio, eliminating drift between newly added CLI functionality and the GUI.
- Added safe generic GUI command execution using validated argument vectors; Studio never interpolates advanced commands through a shell.
- Added a full Manual YouTube URL Ingest card with multi-URL input, provenance tags, normalization controls, scene/index controls, cookies, network tuning, retries, force mode, and verbose yt-dlp support.
- Added Command Center project-path synchronization and exact argument-vector preview.
- Added independent live logging/cancellation for Command Center jobs.
- Added regression coverage ensuring every current non-GUI CLI leaf command is present in the generated GUI schema and representative advanced options remain exposed.

## 0.26.4

- Added `tubeviz ingest-url` for manually adding one or more explicit YouTube video URLs to an existing clip library without search or AI discovery.
- Manual URL ingestion uses the normal yt-dlp metadata, download, normalization, scene detection, visual-feature indexing, duplicate detection, cookie, retry, and persistent-library paths.
- Manual imports default to the `manual` provenance term and support `--term` for user-defined grouping.


## 0.26.3

### Fixed

- Fixed FFglitch 0.10.2 materialization failing when `ffedit -sp` receives fractional effect amounts/timing. FFglitch's setup-parameter parser rejects floating-point JSON literals.
- Codec effect payloads are now embedded as a JavaScript literal in the generated QuickJS transplication script instead of being passed through `-sp`, preserving full floating-point effect precision.
- Added diagnostics that retain the generated FFglitch script path when transplication fails.
- Added regression tests ensuring fractional codec parameters never use the restricted `-sp` parser.

## 0.26.2

### Fixed

- Fixed CLAP inference with current Hugging Face Transformers releases where `ClapModel.get_text_features()` and `get_audio_features()` return `BaseModelOutputWithPooling` instead of a raw tensor.
- Added compatibility extraction for current `pooler_output`, explicit `text_embeds`/`audio_embeds`, legacy raw-tensor returns, and `return_dict=False` tuple returns.
- Added regression tests covering the supported CLAP feature-output forms.

## 0.26.1

### Changed

- Licensed tubeviz under Apache License 2.0 with top-level `LICENSE` and `NOTICE` files and SPDX identifiers on source files.
- Added PEP 639 `license = "Apache-2.0"` and `license-files = ["LICENSE", "NOTICE"]` package metadata.
- Removed the duplicate top-level `native/` C++ source tree; `src/tubeviz/native_src/` is now the single canonical native-renderer source used by both editable installs and wheels.
- Updated native build/test paths for the canonical source tree.
- Expanded README installation documentation with exact FFglitch 0.10.2 requirements, official binary locations, Linux installation commands, `ffedit` PATH setup, codec-materialization architecture, and `tubeviz codec doctor` verification.
- Clarified that third-party software, model weights, and media are not relicensed by tubeviz.

## 0.26.0

### Added

- Added CLAP sliding-window audio-semantic analysis using Hugging Face `ClapModel`/`AutoProcessor` APIs.
- Added a persistent/cached shared audio-visual concept basis spanning mood, motion, visual world, texture, palette and cinematography.
- Added uncertainty-aware CLAP concept distributions and per-section semantic confidence/entropy.
- Added CLAP↔OpenCLIP cross-modal scene scoring through a common text-concept basis rather than invalid direct embedding comparison.
- Audio-semantic concepts now enrich SceneIntent retrieval queries and scene ranking.
- Added deterministic semantic section direction for desired motion, complexity, edit density, transition continuity, target hue, effect family, vector intensity and codec intensity.
- AI-directed edit density is quantized onto the existing beat grid so semantic AI cannot destroy musical timing.
- Added optional whole-song OpenAI-compatible LLM direction that plans themes/treatment only while tubeviz retains clip selection and exact timing authority.
- LLM plans are schema-validated, cached, blended against the deterministic CLAP baseline and confidence-gated when audio semantics are ambiguous.
- Added `tubeviz audio-ai doctor` and `tubeviz audio-ai inspect`.
- Added `--audio-ai`, CLAP model/device/window/hop/cache controls, `--audio-visual-match-weight`, and whole-song `--ai-director-*` controls.
- Added Studio Audio AI controls and Audio AI Doctor.
- Added timeline persistence for CLAP windows, section semantic distributions and section-level AI direction metadata.

## 0.25.0

### Added

- Added a first-class FFglitch codec-space effect subsystem using `ffedit` motion-vector transplication.
- Added controlled MPEG-4 Part 2 AVI preparation encodes so codec behavior is independent of the original YouTube codec/container.
- Added deterministic QuickJS motion-vector effects: drift, wave, shear, explode, implode, spiral, jitter, freeze, feedback, invert, radial wave, and datamosh-style prediction amplification.
- Added Visual Director codec modes: `off`, `subtle`, `musical`, and `aggressive`, plus independent intensity control.
- Added sparse narrative-aware scheduling so codec effects favor builds, mutations, fractured sections, drops and payoffs instead of continuously corrupting footage.
- Added `tubeviz codec doctor`, `tubeviz codec inspect`, and `tubeviz codec materialize`.
- Added `tubeviz library codec-motion-index` using FFglitch's motion-vector JSON export mode.
- Codec-motion magnitude, direction, peaks and accents now augment scene motion matching and beat-to-visual-accent alignment when indexed.
- Added deterministic `library/codec-glitch/` caching with source/range/effect/toolchain provenance sidecars and atomic final writes.
- Codec-materialized selections preserve original source/range provenance so forced rebuilds never recursively glitch prior cache assets.
- Added `/codec-glitch` media serving and native media-path resolution for materialized codec assets.
- Added browser/native raster fallback cues when a timeline contains codec effects that have not yet been materialized.
- Added `tubeviz render --codec-materialize` and `tubeviz serve --codec-materialize` for one-command true codec-space final rendering/preview.
- Added Studio codec controls, FFglitch Doctor, Codec Motion Index, explicit codec materialization, and preview/final-render materialization toggles.

## 0.24.1

### Fixed

- Fixed Studio **Start Preview** reopening an older preview/timeline when the previous preview server was still listening on the fixed port.
- Studio now terminates earlier Studio-managed preview jobs and allocates a fresh local port for each preview launch.
- Preview navigation waits for the new Uvicorn process to reach startup instead of using a fixed 1.2 second delay.
- Preview job metadata records the exact selected timeline, audio, library, and URL.
- `/api/status` now reports the timeline and audio loaded by the current visualizer server.

## 0.24.0

### Changed

- Replaced independent tangent edge strokes with connected contour tracing in the browser vector renderer.
- Added Sobel non-maximum suppression, hysteresis thresholding, connected components, Ramer-Douglas-Peucker simplification, Chaikin smoothing, and temporal contour stabilization.
- Vector echoes now retain and redraw complete contour paths instead of short edge hairs.
- Replaced pseudo-random flow-ribbon origins with a low-resolution local block-matched optical-flow field and streamline integration.
- Reduced visible contour/ribbon counts and opacity to keep source footage dominant.
- Added a Visual Director visible-vector budget: one visible family on ordinary shots, at most two on strong peaks, plus deterministic clean shots with no visible vectors.
- Made vector effect vocabulary family-specific so incompatible visible effects no longer stack on every shot.
- Restricted motif glyphs to callback/peak punctuation rather than persistent display.
- Preserved invisible displacement and motion transplantation independently of the visible-vector budget.
- Reworked native CPU contour rendering into connected component paths and changed native flow seeds from random positions to strong image structure.
- Added browser-runtime and native-manifest pruning for legacy v0.22/v0.23 timelines so old over-dense vector plans no longer stack every visible family.

## 0.23.0

### Added

- Added a visual, non-destructive In/Out trim editor to Studio library playback.
- Added draggable In/Out range handles, detected-scene boundary ticks, a live playhead marker, current-playhead In/Out capture, jump controls, kept-range loop preview, and millisecond readouts.
- Added persistent `usable_start` / `usable_end` clip metadata with an automatic SQLite schema migration.
- Scene selection now excludes scenes outside saved clip bounds and clamps scenes that cross a trim boundary.
- Minimum scene-duration filtering now applies after the trim clamp.
- Visual motion accents are shifted/filtered when a trim cuts into an indexed scene so rhythm alignment cannot use excluded footage.
- Visual-feature indexing explicitly uses original untrimmed scenes, keeping fingerprints stable when trims are changed or cleared.
- Library cards display saved trim ranges and thumbnails prefer scenes that remain inside the usable region.
- Added Studio trim save/clear API endpoints and validation for invalid ranges.

## 0.22.0

### Added

- Added first-class `VectorEffect` scene-graph primitives to the directed timeline.
- Added video-derived contour topology and saliency-oriented subject outlines.
- Added motion-field Bézier ribbons and vector particles.
- Added temporal vector edge echoes.
- Added motion-biased perspective grids.
- Added feature-seeded Delaunay fracture geometry and Voronoi dual geometry.
- Added vector portals that reveal actual companion footage through animated masks.
- Added deterministic recurring motif glyphs as a visual alphabet.
- Added invisible vector displacement fields that deform the rendered footage.
- Added companion-video motion transplantation: temporal motion from one source can deform another.
- Added per-vector-effect automation, deterministic seeds, count, width, opacity, blend, visibility, displacement and source metadata.
- Added `--vector-effects` / `--no-vector-effects` and `--vector-intensity`.
- Added Studio controls for the vector scene graph.
- Added native-manifest `VEC` records and native CPU rendering for the vector-directed effect set.
- Added native vector fallback cues for compatibility with music-reactive raster effects.

## 0.21.0

### Added

- Added persistent temporal scene visual fingerprints stored in SQLite.
- Added `tubeviz library visual-index` for motion/palette/complexity/accent indexing.
- New ingests visually index detected scenes by default; analysis can automatically backfill older libraries.
- Added motion, complexity, brightness, saturation and palette compatibility to scene ranking.
- Added transition-aware scene scoring: continuity during ambient/hypnotic passages and stronger contrast at peaks/payoffs.
- Added natural visual-accent detection and source-offset/playback-rate search to phase-align footage motion with musical beats.
- Added `VisualDirection` and `ColorDirection` timeline metadata with narrative role, effect family, rhythm alignment, transition score and continuous automation curves.
- Added directed palette/hue/saturation/contrast/brightness treatment.
- Added continuously automated spectral displacement and prismatic/chromatic video effects in the browser renderer.
- Added continuous automation for feedback, flow, glitch and bloom.
- Added native-renderer hue rotation and exported major direction-automation peaks as native-compatible ripple/chroma/vortex/bloom cues.
- Added Studio controls for visual matching, transition intelligence, rhythm alignment, visual indexing, and visual-index rebuilds.
- Added `--visual-match-weight`, `--transition-weight`, `--rhythm-alignment`, and `--visual-auto-index`.

All notable tubeviz changes are recorded here. The README documents only the current system and current usage.

## 0.20.1

### Fixed

- Fixed Studio clip playback when a clip record does not contain a directly usable `normalized_path`.
- Added library media resolution that prefers normalized media, follows duplicate aliases to canonical media, falls back to downloaded originals, and recovers source-ID-named files from older libraries.
- Studio now reports whether local media is actually available and disables Play when it is not.
- Studio playback now passes the clip's real source namespace instead of assuming every clip is `youtube`.
- Missing media now returns diagnostic state instead of an opaque 404.

## 0.20.0

### Added

- Added `tubeviz gui`, a local FastAPI/browser Studio interface.
- Added Create controls for ingest, music analysis, scene selection, preview, native builds, and final rendering.
- Added visual Library browsing with thumbnails, playback, filtering, reject/restore, and deletion.
- Added background job management with live logs and cancellation.
- Exposed current semantic selection, novelty, dynamic-shot, short-excerpt, composition, native-render, and AI-ingest controls in Studio.

## 0.19.2

### Performance

- Fixed decoded-frame reuse in the native renderer so output FPS higher than source FPS does not force unnecessary compressed-frame decoding.
- Added an LRU cache of decoder contexts across cuts and prewarming for upcoming shots.
- Switched Phase-1 source scaling to `SWS_FAST_BILINEAR`.
- Enabled libavcodec frame/slice threading where supported.
- Added OpenMP parallelization across major CPU effect/composition loops.
- Replaced several expensive radial per-pixel operations with cheaper approximations.
- Replaced per-pixel random-distribution noise with deterministic integer hashing.
- Changed the native encoder default to `veryfast`.
- Added `--native-decoder-cache` and `--native-threads`.
- Added NVENC-aware CQ/rate-control handling and preset mapping.

## 0.19.1

### Fixed

- Improved native-render media-path handling so manifests resolve actual library media rather than relying on fragile path assumptions.
- Improved native renderer diagnostics for missing media.

## 0.19.0

### Added

- Added the Phase-1 native C++ rendering backend.
- Added `tubeviz native build` and `tubeviz native doctor`.
- Added `--backend auto|native|browser`.
- Added native manifest generation and direct FFmpeg/libavcodec source decoding.
- Implemented native CPU versions of the core video transform/composition path.
- Preserved the browser backend as a compatibility/reference renderer.

## 0.18.0

### Added

- Added dynamic beat-aligned shots inside longer musical sections.
- Added automatic unique-source targeting scaled to track duration/library size.
- Added novelty-aware source exploration and source/scene reuse cooldowns.
- Added short source excerpts so a selected scene does not need to play in full.
- Added `--target-unique-clips`, `--novelty-weight`, `--novelty-candidate-fraction`, `--clip-reuse-cooldown`, `--scene-reuse-cooldown`, `--dynamic-shots`, `--min-shot-seconds`, `--max-shot-seconds`, and `--source-excerpt-max-seconds`.

## 0.17.0

### Added

- Added reproducible alternate scene-selection cuts with `--selection-seed`.
- Added `--selection-variation`.
- Added `--reshuffle` for fresh randomized cuts while retaining deterministic behavior once a seed is known.

## 0.16.0

### Added

- Added persistent manual clip rejection and restoration.
- Added hard-delete workflow with dry-run, keep-original, and confirmation controls.
- Added library inspection/curation commands.

## 0.15.0

### Added

- Added AI-assisted pre-download clip discovery.
- Added OpenCLIP visual ranking and scene embeddings.
- Added query expansion from seed visual concepts.
- Added optional OpenAI-compatible LLM query expansion.
- Added visual diversity/near-duplicate penalties, negative-concept penalties, metadata scoring, and minimum AI score.
- Added persisted AI-ranking reports.

## 0.14.0

### Added

- Added local/variable-tempo analysis for long mixes rather than assuming one BPM for the entire track.
- Added smoothed tempo curves and tempo-change events.
- Added richer vibe/section analysis to influence editing and effects.
- Shifted kaleidoscopic/mirrored composition toward more organic video deformation.

## 0.13.0

### Added

- Added deterministic offline final rendering through the browser renderer.
- Added Playwright-driven frame stepping and FFmpeg encoding.
- Added PNG/JPEG browser-to-FFmpeg frame transport.
- Added Chrome/Chromium selection and explicit browser executable support.

## 0.12.2

### Fixed

- Added safeguards against active, upcoming, and post-live sources during ingest.
- Preferred finite direct HTTP/HTTPS video representations.
- Added bounded network timeout/retry controls and concurrent fragment downloading for finite fragmented media.

## 0.12.0

### Added

- Added temporal video-synthesis effects including slit scan, frame echo, mirror corridor, mask wipe, solarize, datamosh-style blocks, block displacement, chroma delay, VHS tracking, vortex, motion trails, and slice recursion.
- Added effect-style direction derived from musical structure and scene identity.
- Added music-edit cues for temporal effects.
- Added live Master/Motion/Trails/Glitch/Strobe performance controls.
- Removed the persistent rectangular motif-thumbnail treatment.

## 0.10.0

### Added

- Added rendered-video ripple/displacement, mirrored video treatment, recursive feedback, posterization, edge/light extraction, strobe exposure, and shutter/frame-hold effects.
- Increased beat/bar/harmonic/drop modulation of effects rather than holding effects static for a section.

## 0.9.0

### Added

- Added multi-source video composition with up to four indexed scenes per musical section.
- Added `single`, `pip`, `split`, `mosaic`, `luma`, and `strips` composition modes.
- Added independent companion-source transforms and beat-driven source focus.
- Extended materialization to companion sources.

## 0.8.0

### Changed

- Converted the visualizer to a video-first rendering model.
- HTML video elements became decoders while visible frames are composed and transformed through the video-FX canvas.
- Procedural geometry became subordinate to transformed source footage.
- Added beat/onset/drop-driven footage punches, retriggers, jumps, slices, and freezes.

## 0.7.0

### Added

- Added deterministic music-directed transform plans per selected scene.
- Added playback rate, crop/zoom/pan, mirror, rotation, color treatment, blur, blend modes, feedback, and glitch treatments.
- Added `tubeviz materialize` for FFmpeg-baked source transforms and transform caching.

## Earlier development

Initial releases established:

- the persistent yt-dlp-backed clip library;
- source normalization, scene detection, thumbnails, and provenance;
- music analysis and timeline JSON;
- deterministic scene planning and motif-aware source reuse;
- the FastAPI/WebSocket interactive visualizer;
- browser video crossfades and indexed scene-range looping.

## 0.28.0 - Theme-first AI acquisition

- Added natural-language `--visual-brief` ingestion with optional `--audio` conditioning.
- Added structured OpenAI-compatible LLM acquisition planning with deterministic fallback.
- Added library-coverage context so discovery can seek underrepresented footage rather than blindly repeating saturated concepts.
- Added explicit positive/negative visual vocabulary for dynamic music-video suitability.
- Added strategic yt-dlp partial-video preview downloads before full source acquisition.
- Added OpenCLIP + temporal visual music-video fitness scoring and `--min-video-fitness` rejection.
- Added automatic weak intro/outro scene trimming after scene visual indexing.
- Added target-aware query quota distribution and disables redundant second-level query expansion for generated acquisition plans.
- Added Studio Visual Brief, preview-gate, fitness and auto-trim controls plus Command Center parity.
- Search-term ingestion remains supported as the legacy/manual discovery path.
