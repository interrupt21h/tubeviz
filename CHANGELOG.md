# Changelog

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
