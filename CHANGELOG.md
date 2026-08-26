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
