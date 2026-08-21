# tubeviz

tubeviz is a music-aware visualizer that builds a reusable local video corpus,
analyzes complete music tracks, remembers recurring musical motifs, and directs
indexed video scenes through a video-first multi-source VJ renderer in sync with the track.

## Pipeline

```text
search_terms.txt
      │
      ▼
tubeviz ingest ── yt-dlp ── FFmpeg normalization/scene detection
      │
      ▼
library/metadata.sqlite3 + normalized video corpus
      │
      ├──────────────────────────────┐
      │                              │
      ▼                              ▼
tubeviz analyze                  music structure
      │                              │
      └────────── scene planner ◄────┘
                     │
                     ▼
               timeline.json
                     │
                     ▼
               tubeviz serve
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
    dual video layers      procedural canvas
          │                     │
          └──────────┬──────────┘
                     ▼
                  browser
```

## Install

Python 3.11+ and FFmpeg/ffprobe are required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest -q
```

## 1. Build the clip library

```bash
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --cookies-from-browser chrome
```

`--results-per-term` is a READY-clip quota. tubeviz progressively expands
`ytsearch` when the initial result window cannot fill that quota, and continues
after blocked, rejected, duplicate, or failed candidates. The default search
window expands from 50 up to 250 results in 50-result increments. The default
20-minute duration is only a preference; the default hard source limit is one
hour.

Useful ingest options:

```bash
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --results-per-term 10 \
  --search-pool 50 \
  --max-search-pool 500 \
  --search-pool-step 50 \
  --preferred-max-duration 1200 \
  --hard-max-duration 0 \
  --scene-threshold 0.40 \
  --min-scene-seconds 1.5
```

Inspect the corpus:

```bash
tubeviz library stats --library ./library
```

## 2. Analyze music and attach clips

The preferred workflow embeds a deterministic scene plan directly in the
track timeline:

```bash
tubeviz analyze song.flac \
  --library ./library \
  --section-seconds 8 \
  --scene-crossfade 1.25 \
  --clip-opacity 0.92 \
  --output song.timeline.json
```

Each musical section receives an indexed scene. Recurring motifs are assigned a
stable provenance/search-term family. On later occurrences, tubeviz prefers the
same source clip while rotating to another detected shot when possible.

If a specific search-term bucket has no usable scene, planning falls back to the
full READY corpus rather than disabling video for that section.

## 3. Serve the visualizer

```bash
tubeviz serve song.timeline.json \
  --audio song.flac \
  --library ./library \
  --host 0.0.0.0 \
  --port 8080
```

Open `http://localhost:8080/`.

The browser uses two muted `<video>` elements beneath a transparent Canvas.
The inactive video seeks to the next indexed scene and then crossfades in, which
avoids a black frame between source clips. The Canvas continues to provide beat,
onset, harmonic-warp, motif, world-memory, and phase-transition effects over the
actual footage.

Indexed scenes are source time ranges, not duplicated media files. If a selected
scene is shorter than its musical section, the browser loops within that exact
scene range until the next scene cue arrives.

## Existing timelines

You do not have to rerun music analysis just to try clips. If an existing
timeline has no `scene_plan`, `serve --library` plans scenes in memory:

```bash
tubeviz serve existing.timeline.json \
  --audio song.flac \
  --library ./library
```

To ignore an embedded plan and select again from the current library:

```bash
tubeviz serve song.timeline.json \
  --audio song.flac \
  --library ./library \
  --replan-scenes
```

`--replan-scenes` is useful after ingesting additional footage.

## Scene-selection behavior

For each section tubeviz currently uses a deterministic selector:

1. map recurring motifs to a stable search term;
2. rotate non-motif sections through available search terms;
3. prefer scene durations close to the musical-section duration;
4. avoid recently used scenes;
5. for motif callbacks, prefer the same source clip but a different shot;
6. fall back to the entire READY scene library if needed.

Metadata/provenance semantic ranking is always available. Optional OpenCLIP
visual embeddings let SceneIntent search the full scene corpus by image/text
similarity while retaining motif source-memory and the same renderer cue
contract.

Install semantic support:

```bash
pip install -e '.[semantic,dev]'
```

Index existing scene thumbnails:

```bash
tubeviz library embed --library ./library --device auto
```

OpenCLIP's default tubeviz model is `ViT-B-32` with
`laion2b_s34b_b79k`. Embeddings are persisted in SQLite and only new scenes are
processed on subsequent runs.

Then analyze with semantic retrieval:

```bash
tubeviz analyze song.flac \
  --library ./library \
  --semantic \
  --section-seconds 8 \
  --output song.timeline.json
```

or re-plan an existing timeline at serve time:

```bash
tubeviz serve song.timeline.json \
  --audio song.flac \
  --library ./library \
  --replan-scenes \
  --semantic
```

Each selection records its `intent_query` and `semantic_score` in the timeline.

## HTTP endpoints

- `/` — browser visualizer
- `/api/timeline` — complete directed timeline including `scene_plan`
- `/api/status` — clip-renderer/library status
- `/audio` — selected music file when supplied
- `/media/...` — normalized clip files, rooted only at `library/normalized`
- `/transforms/...` — cached FFmpeg-transformed scene files, rooted only at `library/transforms`
- `/ws` — deterministic playback clock and visual cues

## Tests

```bash
pytest -q
```

## 4. Music-directed video transforms

v0.7 adds a deterministic transform plan to every selected scene. The plan is
derived from section energy, brightness, onset density, section type, motif
recurrence, and a stable scene salt. Re-analyzing the same track/library with
the same options therefore produces the same visual treatment.

Live browser-safe transforms include:

- playback-rate changes;
- zoom and pan;
- horizontal mirror;
- small camera rotation;
- brightness, contrast, saturation, hue, grayscale, and blur;
- CSS blend modes;
- Canvas temporal-feedback trails;
- horizontal glitch slices and noise lines.

Use the default transform director:

```bash
tubeviz analyze song.flac \
  --library ./library \
  --section-seconds 8 \
  --transform-intensity 1.0 \
  --output song.timeline.json
```

More aggressive treatment:

```bash
tubeviz analyze song.flac \
  --library ./library \
  --transform-intensity 1.6 \
  --output song.timeline.json
```

Disable transforms while retaining scene selection:

```bash
tubeviz analyze song.flac --library ./library --no-transforms -o clean.timeline.json
```

For an existing scene plan, recompute only its transforms at serve time:

```bash
tubeviz serve song.timeline.json \
  --audio song.flac \
  --library ./library \
  --replan-transforms \
  --transform-intensity 1.4
```

### Materialized FFmpeg transforms

Browser playback cannot perform true reverse playback and some temporal effects
are higher quality when rendered ahead of time. `tubeviz materialize` turns each
selected source range into a cached transformed MP4 under `library/transforms/`.
The cache key includes the source file metadata, scene range, transform plan,
and render configuration, so repeated runs reuse identical outputs.

```bash
tubeviz materialize song.timeline.json \
  --library ./library \
  --output song.materialized.json
```

Optional render controls:

```bash
tubeviz materialize song.timeline.json \
  --library ./library \
  --width 1280 \
  --height 720 \
  --fps 30 \
  --crf 18 \
  --preset medium \
  --output song.materialized.json
```

Then serve the materialized timeline normally:

```bash
tubeviz serve song.materialized.json \
  --audio song.flac \
  --library ./library
```

The FFmpeg materializer can bake crop/zoom, pan, mirror, rotation, hue/EQ,
grayscale, blur, noise, temporal mixing, reverse, and PTS retiming. The browser
continues to apply lightweight glitch overlays and blend modes over the cached
video.

You can inspect a generated cache item directly with FFplay:

```bash
ffplay -loop 0 library/transforms/<transform-id>.mp4
```

`/transforms/...` is served separately from `/media/...`; only those two library
subdirectories are exposed to the browser.


## v0.8 video-first renderer

The browser now treats the HTML video elements only as decoders. Every visible frame is drawn into the video-FX canvas first, then crop/zoom/rotation/color, feedback, pixelation, RGB displacement, scanlines, vignette, glitch slicing and beat-accurate edits are applied to those rendered video pixels. Procedural geometry is intentionally subordinate: motif fills and onset fragments sample the rendered footage itself. Beat, bar, onset and drop events can punch, retrigger, jump, slice and briefly freeze the active footage.

## Multi-source video compositor (v0.9)

Tubeviz can now build each musical section from a group of up to four indexed
video scenes.  The primary scene remains motif/semantic-aware; companion scenes
favor different source clips and are transformed independently.

```bash
tubeviz analyze song.flac \
  --library ./library \
  --semantic \
  --max-video-layers 4 \
  --composition-intensity 1.4 \
  --transform-intensity 1.3 \
  --output song.timeline.json
```

Composition modes are selected from section character and energy:

- `single`: one full-frame source
- `pip`: full-frame primary with companion picture-in-picture sources
- `split`: side-by-side or quadrant sources
- `mosaic`: 2x2 source grid
- `luma`: full-frame blended sources using screen/multiply-style luma contrast
- `strips`: beat-switchable vertical source strips

The browser uses eight hidden video decoders as two four-source banks. A section
transition loads the next bank, seeks every layer to its indexed scene range,
and crossfades the rendered groups. Beat editing can rotate the focused source,
retrigger scene ranges, jump within shots, punch the rendered image, glitch
slices, and freeze the final composited frame.

`tubeviz materialize` now materializes transforms for both the primary source and
all companion sources. The final masks, feedback, compositing, and beat editing
remain live so baked assets still respond to the music.

## v0.10 rendered-video effects

Tubeviz remains video-first: all live effects operate on the already-composited video frame.
The renderer now adds ripple/displacement slicing, kaleidoscope wedges, mirrored video tiling,
recursive feedback tunnels, posterization, edge/light extraction, strobe exposure, and shutter/frame-hold effects.
These combine with the existing pixelation, RGB displacement, glitch slicing, scanlines, vignette, feedback,
and multi-source composition. Beats, bars, harmonic changes, motif recalls, and drops pulse effect intensity
through `video_edit_*` timeline cues rather than leaving effects static for an entire section.

`--transform-intensity` controls both persistent scene treatment and the strength of live video effects.
A useful aggressive test is:

```bash
tubeviz analyze song.flac \
  --library ./library \
  --semantic \
  --max-video-layers 4 \
  --composition-intensity 1.5 \
  --transform-intensity 1.7 \
  --section-seconds 8 \
  --output song.timeline.json
```

Then serve normally with `tubeviz serve`.


## v0.12 temporal video synthesis and live performance controls

v0.12 expands the post-compositor into a temporal video-synthesis engine. All
effects below consume the already-composited video frame; no decorative
background visualizer is required.

New planned effects:

- `slit_scan`: horizontal time-slices sourced from several recent rendered frames;
- `frame_echo`: delayed video taps with progressive scale/opacity;
- `mirror_corridor`: mirrored moving video bands;
- `mask_wipe`: animated radial/diagonal reveals of delayed video;
- `solarize`: low-resolution luminance-threshold solarization;
- `datamosh`: deterministic displaced blocks copied from delayed video;
- `block_displace`: grid regions displaced from the current rendered frame;
- `chroma_delay`: hue-separated delayed video taps;
- `vhs_tracking`: moving horizontal tracking-band distortion;
- `vortex`: radial wedges of transformed rendered video;
- `motion_trails`: difference/screen blends against delayed frames;
- `slice_recursion`: recursively rescaled horizontal video slices.

Sections also receive an `effect_style` (`dream`, `analog`, `cinematic`,
`kinetic`, `fracture`, `recursive`, or `datamosh`) derived deterministically
from musical structure and scene identity.

The music editor can pulse these effects through cues such as
`video_edit_datamosh`, `video_edit_slitscan`, `video_edit_echo`,
`video_edit_vortex`, `video_edit_motion_trails`, and
`video_edit_slice_recursion`.

The browser HUD includes live controls for Master, Motion, Trails, Glitch, and
Strobe. These are performance-time multipliers over the planned timeline, so a
track does not need to be re-analyzed merely to make a live set more or less
aggressive.

The temporal delay buffers are half-resolution canvases to bound memory use,
while the final video canvas remains full-resolution. Motif memory overlays are
transient and clipped; there is no persistent rectangular thumbnail path.


## v0.12.2 live/HLS ingest safeguards

tubeviz rejects active, upcoming, and `post_live` sources before download.
Archived livestreams (`was_live`) remain eligible only when yt-dlp exposes a
finite HTTP/HTTPS VOD representation.

The downloader now prefers direct HTTP/HTTPS formats before fragmented
fallbacks and will not deliberately fall back to an HLS-only source. Network
behavior is bounded with configurable socket/retry settings, while finite
fragmented downloads can use concurrent fragment fetching.

Relevant ingest options:

```bash
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --download-socket-timeout 20 \
  --concurrent-fragments 4 \
  --download-retries 2 \
  --fragment-retries 2
```

A live candidate now produces output such as:

```text
reject: VIDEO_ID: active live stream
```

instead of launching FFmpeg against an open-ended YouTube HLS manifest.


## Offline final rendering

v0.13 adds a deterministic offline browser renderer for producing the complete
tubeviz composition as a video file. It uses the same `visualizer.js` engine as
interactive playback: decoded clips, multi-source composition, music-directed
edits, temporal buffers, feedback, datamosh, organic kaleidoscope, and other
Canvas effects are all rendered by Chromium.

Install the render extra:

```bash
pip install -e '.[render,dev]'
```

By default tubeviz uses the installed Google Chrome channel because normalized
library media is H.264 MP4 and branded Chrome/Edge provide broader proprietary
media-codec support than open-source Chromium builds. To use Playwright's
bundled Chromium instead:

```bash
playwright install chromium
tubeviz render ... --browser-channel chromium
```

Render a timeline:

```bash
tubeviz render song.timeline.json \
  --audio song.flac \
  --library ./library \
  --output song.mp4 \
  --width 1920 \
  --height 1080 \
  --fps 60 \
  --crf 18
```

The browser is frame-stepped rather than allowed to run in real time. For every
output frame tubeviz:

1. advances a synthetic music clock;
2. seeks each active source decoder to the exact scene position;
3. applies all timeline cues crossed by that frame;
4. renders the complete multi-source Canvas composition;
5. captures the viewport;
6. writes the frame directly to FFmpeg through `image2pipe`.

FFmpeg simultaneously reads the original music file, encodes the frame stream,
and muxes the original audio into the output. No screen/audio capture is used.

PNG is the default browser-to-FFmpeg transport:

```bash
tubeviz render song.timeline.json \
  --audio song.flac \
  --library ./library \
  -o song.mp4 \
  --frame-format png
```

For much faster long renders with a small intermediate quality tradeoff:

```bash
tubeviz render song.timeline.json \
  --audio song.flac \
  --library ./library \
  -o song.mp4 \
  --frame-format jpeg \
  --jpeg-quality 95
```

A high-quality 4K render:

```bash
tubeviz render song.timeline.json \
  --audio song.flac \
  --library ./library \
  -o song-4k.mp4 \
  --width 3840 \
  --height 2160 \
  --fps 60 \
  --video-codec libx264 \
  --preset slow \
  --crf 16 \
  --audio-codec aac \
  --audio-bitrate 320k
```

If system Chrome is preferable to Playwright's bundled Chromium:

```bash
tubeviz render song.timeline.json \
  --audio song.flac \
  --library ./library \
  -o song.mp4 \
  --browser-channel chrome
```

or provide an explicit executable:

```bash
--browser-executable /usr/bin/google-chrome
```

The offline renderer uses a deterministic FX seed (`--seed`) and substitutes a
synthetic render clock for browser wall-clock time. Temporal-effect decay is
normalized to the requested output FPS, so rendering slower than real time does
not slow down the visual timeline.


### Render performance

v0.13.1 removes two major bottlenecks from the first offline renderer:

- paused video decoders no longer wait on `requestVideoFrameCallback()` after
  every `currentTime` seek; the renderer waits for the media `seeked` event,
  which signals completion of the seek operation;
- frames are exported directly from the final tubeviz Canvas using
  `HTMLCanvasElement.toBlob()` instead of asking Playwright to capture a
  full-page screenshot for every frame.

Render progress now includes average browser, Canvas-export, and FFmpeg-pipe
timings:

```text
frame 450/5626 (8.0%) 7.4 fps-render ETA 699s
[browser 118ms, canvas-export 24ms, ffmpeg-pipe 2ms]
```

For fast previews, JPEG transport remains recommended:

```bash
tubeviz render machine.json \
  --audio machine.mp3 \
  --library ./library \
  -o machine-viz-test.mp4 \
  --width 1280 \
  --height 720 \
  --fps 30 \
  --frame-format jpeg \
  --jpeg-quality 90 \
  --crf 20
```


## v0.14 variable-tempo rhythm and vibe analysis

v0.14 changes music direction from a mostly global-BPM model to a local,
time-varying rhythm model suitable for long DJ mixes and tempo transitions.

The analyzer now computes a frame-wise tempo trajectory with librosa's local
tempo estimator (`feature.tempo(..., aggregate=None)`), median-smooths it, folds
obvious half/double-time aliases into a configurable DJ BPM range, and feeds the
resulting BPM array directly into `beat_track`. The persisted timeline contains
a sparse `tempo_curve`, and significant local tempo changes become
`tempo_change` events.

By default, musical sections are aligned to 8-bar phrases:

```bash
tubeviz analyze mix.mp3 \
  --library ./library \
  --section-bars 8 \
  --output mix.json
```

Use fixed wall-clock sections instead:

```bash
tubeviz analyze mix.mp3 \
  --library ./library \
  --section-bars 0 \
  --section-seconds 16 \
  --output mix.json
```

Tempo controls:

```text
--tempo-window-seconds       local autocorrelation window
--tempo-smoothing-seconds    median smoothing for the tempo curve
--tempo-curve-seconds        spacing of persisted tempo points
--tempo-change-bpm           threshold for tempo-change events
--min-tempo / --max-tempo    absolute analysis bounds
--tempo-octave-min           half-time values below this are doubled
--tempo-octave-max           double-time values above this are halved
```

The default octave-preference range is 75–190 BPM, which is useful for
electronic/DJ material. Set `--tempo-octave-min 0` to disable octave folding.

Each detected beat now carries:

```text
local_bpm
tempo_confidence
pulse
accent
low
mid
high
dominant_band
```

The low/mid/high values are frequency-aware transient strengths. This lets the
renderer react differently to different parts of the rhythm:

```text
kick / low transient     -> radial lens + ripple / zoom pressure
mid transient            -> shear / vortex movement
hat / high transient     -> chromatic displacement + slit-scan
strong accented beat     -> retrigger / source edit when appropriate
tempo transition         -> broad time/space warp
```

### Vibe features

Sections now carry a richer musical-state description:

```text
local_tempo_bpm
tempo_confidence
pulse_strength
bass_weight
percussive_ratio
tonal_stability
noisiness
spectral_contrast
vibe
```

Vibe labels currently include:

```text
ambient
hypnotic
dark
heavy
driving
euphoric
fractured
groove
```

They are derived from energy, frequency balance, harmonic/percussive
separation, spectral flatness/contrast, chroma stability, onset density, and
local tempo. Vibe is fed into semantic scene intent as well as transform
planning, so footage selection and effects respond to the musical character
instead of only amplitude.

### Organic video composition

New scene plans no longer choose `pip`, `split`, or `mosaic` as default
composition modes. Multi-source sections use full-frame `luma`, moving
`strips`, or `flow` composition. `flow` exposes companion videos through
continuously moving Bezier masks over the primary full-frame source.

Older timelines using PiP/mosaic/split are interpreted as organic flow at
render time.

Rectangular onset video patches have also been removed. Onset fragments are now
irregular clipped refraction droplets derived from the current rendered frame.
Motif echoes use drifting organic masks, and the legacy tile/tunnel effects are
rendered as curved lens/refraction fields rather than nested rectangular video
windows.

The visible image remains video-first: beats and tone deform the composed
footage itself.


## v0.15 AI-assisted clip discovery

v0.15 adds an AI curation stage *before* expensive video downloads.

Install semantic support:

```bash
pip install -e '.[semantic,dev]'
```

Then build a library with AI discovery:

```bash
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --cookies-from-browser chrome \
  --ai-discovery \
  --ai-device cuda \
  --ai-candidates-per-term 100 \
  --results-per-term 10
```

The ingest pipeline becomes:

```text
seed search term
      │
      ▼
query expansion
      │
      ▼
multiple ytsearch result sets
      │
      ▼
deduplicated metadata candidate pool
      │
      ▼
YouTube thumbnail cache
      │
      ▼
OpenCLIP
 ┌────┼───────────┐
 │    │           │
 ▼    ▼           ▼
positive         negative
visual           concepts
relevance        / boring-content cues
 │                │
 └──────┬─────────┘
        ▼
metadata relevance
        │
        ▼
near-duplicate MMR penalty
        │
        ▼
ranked shortlist
        │
        ▼
hydrate / live-format checks
        │
        ▼
download only best candidates
        │
        ▼
normalize / scene detection
        │
        ▼
automatic scene OpenCLIP embeddings
```

OpenCLIP is loaded once for the entire ingest run and reused across all search
terms and newly indexed scenes.

### Query expansion

Without an LLM, tubeviz expands a seed into deterministic visual variants such
as archival footage, vintage film, detail shots, analog/VHS, atmospheric
footage, and motion-heavy interpretations.

An OpenAI-compatible chat-completions endpoint can provide richer query
expansion:

```bash
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --ai-discovery \
  --ai-device cuda \
  --ai-llm-base-url http://localhost:8000/v1 \
  --ai-llm-model my-local-model
```

If the endpoint needs a bearer token:

```bash
--ai-llm-api-key "$TOKEN"
```

The LLM is used only for search-query generation. Thumbnail ranking remains
local OpenCLIP inference.

Disable expansion while keeping AI ranking:

```bash
--no-ai-query-expansion
```

### Pre-download visual ranking

For each candidate tubeviz scores:

```text
OpenCLIP positive visual relevance
- negative-concept similarity
+ title/description/search-query relevance
+ duration preference
- near-duplicate penalty
```

Default negative visual concepts include:

```text
talking head presenter
podcast interview
static slideshow
text only screen
logo title card
modern youtube host
powerpoint presentation
```

Override them:

```bash
--ai-negative-concepts \
  "talking head,podcast,static slideshow,title card,screen recording"
```

Important controls:

```text
--ai-query-count
--ai-candidates-per-term
--ai-model
--ai-pretrained
--ai-device
--ai-batch-size
--ai-diversity-weight
--ai-near-duplicate-threshold
--ai-negative-weight
--ai-metadata-weight
--ai-min-score
```

The near-duplicate penalty is deliberately nonlinear: visually related footage
is allowed, while candidates whose thumbnail cosine similarity crosses the
near-duplicate threshold are penalized sharply.

Typical output:

```text
[1/8] search: NASA mission control archival
  AI queries (8):
    - NASA mission control archival
    - NASA mission control archival archival footage
    - NASA mission control archival vintage film
    ...

  AI preview ranking: 94 thumbnails scored; 6 without usable thumbnails
    +0.281 visual=+0.294 neg=+0.183 div=0.000 abc123 ...
    +0.264 visual=+0.287 neg=+0.175 div=0.421 def456 ...
    ...

  AI shortlist: 73/100 candidates at score >= -0.05
  download: abc123 ...
```

This allows tubeviz to inspect tens or hundreds of cheap thumbnails while only
downloading the small number of source videos needed to fill the READY quota.

### Automatic scene embeddings

After a selected clip is downloaded, normalized, and scene-detected, v0.15
reuses the already-loaded OpenCLIP model to embed the new scene thumbnails.

Therefore an AI-ingested library is immediately usable with:

```bash
tubeviz analyze music.mp3 \
  --library ./library \
  --semantic \
  --semantic-device cuda \
  --output music.json
```

without requiring a separate full:

```bash
tubeviz library embed
```

pass.

Disable automatic scene indexing if desired:

```bash
--no-ai-index-scenes
```

### Inspecting AI decisions

Ranking components are persisted in each clip's `metadata_json`.

Inspect recent rankings:

```bash
tubeviz library ai-report \
  --library ./library \
  --limit 30
```

Or inspect one seed term:

```bash
tubeviz library ai-report \
  --library ./library \
  --term "NASA mission control archival"
```

The report includes final score, visual relevance, negative-concept score,
near-duplicate similarity, persistent clip status, source ID, and title.

This is intentionally inspectable rather than a black-box "AI liked this"
decision.

### Recommended AI ingest

For a reasonably broad visual corpus:

```bash
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --cookies-from-browser chrome \
  --results-per-term 10 \
  --hard-max-duration 600 \
  --ai-discovery \
  --ai-device cuda \
  --ai-query-count 8 \
  --ai-candidates-per-term 120 \
  --ai-diversity-weight 0.32 \
  --ai-near-duplicate-threshold 0.86 \
  --ai-negative-weight 0.50
```

This is intentionally different from asking YouTube for ten results and
downloading all ten: discovery is broad, inspection is cheap, and download is
selective.


## v0.16 library curation

v0.16 adds first-class clip curation commands. Manual rejection is
non-destructive and persistent: rejected clips keep their files and metadata,
are excluded from scene selection, and are skipped by future ingest runs even
when `--force` is supplied.

List clips:

```bash
tubeviz library list --library ./library
```

Useful filters:

```bash
tubeviz library list --library ./library --status ready
tubeviz library list --library ./library --status rejected_manual
tubeviz library list --library ./library --term "NASA mission control archival"
tubeviz library list --library ./library --json
```

Inspect one clip:

```bash
tubeviz library show EDsjLZchiGU --library ./library
```

or machine-readable output:

```bash
tubeviz library show EDsjLZchiGU --library ./library --json
```

`show` includes status, source media paths, scene/embedding counts, search-term
provenance, duplicate aliases, and persisted AI ranking components when
available.

### Reject and restore

Reject footage without deleting it:

```bash
tubeviz library reject EDsjLZchiGU \
  --library ./library \
  --reason "talking head / not useful for VJ footage"
```

A rejected clip becomes:

```text
status = rejected_manual
```

Its files stay on disk, but it is no longer returned by the READY scene query.
Future ingest runs recognize this status and will not hydrate or re-download the
same source ID.

Restore it later:

```bash
tubeviz library restore EDsjLZchiGU --library ./library
```

Restore chooses the best status supported by the files still present:

```text
normalized video exists -> ready
original only exists     -> downloaded
no media exists          -> discovered
```

### Hard delete

Always preview a deletion first:

```bash
tubeviz library delete EDsjLZchiGU \
  --library ./library \
  --dry-run
```

Then delete interactively:

```bash
tubeviz library delete EDsjLZchiGU --library ./library
```

or non-interactively:

```bash
tubeviz library delete EDsjLZchiGU \
  --library ./library \
  --yes
```

Retain the originally downloaded source media while removing the DB record,
normalized media, scene thumbnails, scene embeddings, AI thumbnail, and other
tracked derived data:

```bash
tubeviz library delete EDsjLZchiGU \
  --library ./library \
  --keep-original \
  --yes
```

Hard deletion uses an in-library staging transaction. Tracked files are moved
into a temporary trash directory first; the clip DB rows are then deleted,
which cascades scene rows, scene embeddings, and clip/search-term associations.
If the DB operation fails, staged files are moved back into place. Duplicate
alias records referencing the same physical asset are removed with the
canonical clip so broken shared paths are not left behind.


## v0.17 alternate cuts: selection seeds and reshuffle

Scene selection can now produce reproducible alternate edits from the same
analysis and READY clip library.

Create a persistent alternate cut:

```bash
tubeviz analyze machine.mp3 \
  --library ./library \
  --semantic \
  --semantic-device cuda \
  --selection-seed 42 \
  --output machine-cut-42.json
```

The same library, analysis inputs, and seed reproduce the same scene choices.
A different seed produces another cut:

```bash
--selection-seed 43
```

For an immediately fresh cut, use `--reshuffle`:

```bash
tubeviz analyze machine.mp3 \
  --library ./library \
  --semantic \
  --semantic-device cuda \
  --reshuffle \
  --output machine-random.json
```

tubeviz prints the generated seed so the cut can be recreated later.

Existing analyzed timelines can be replanned at serve time:

```bash
tubeviz serve machine.json \
  --audio machine.mp3 \
  --library ./library \
  --replan-scenes \
  --semantic \
  --semantic-device cuda \
  --selection-seed 42
```

or:

```bash
tubeviz serve machine.json \
  --audio machine.mp3 \
  --library ./library \
  --replan-scenes \
  --semantic \
  --semantic-device cuda \
  --reshuffle
```

`--selection-variation` controls how strongly a seed can vary choices among
semantically plausible candidates. The default is `0.30`. `0` preserves seeded
term mapping and deterministic tie-breaking without adding relevance jitter.
Seed `0` preserves the historical canonical scene-selection behavior.

The offline renderer's existing `render --seed` remains separate: it controls
render-time FX determinism, while `--selection-seed` controls which scenes and
clips are selected.


## v0.18 dynamic shot editing and library exploration

v0.18 changes scene planning from "one video choice per musical section" to a
music-aware shot editor. A section remains the high-level vibe/semantic unit,
but it can contain many beat-aligned video shots.

The default shot density is approximately:

```text
ambient / hypnotic / breakdown   8 beats per shot
groove / moderate passages       6 beats per shot
drive                             4 beats per shot
build                             2–4 beats per shot
peak / heavy / fractured         2 beats per shot
```

For a 120–130 BPM four-minute song this commonly produces roughly 80–140
primary shot decisions instead of only 15–20 long section-level choices.

Dynamic shots are enabled by default. Disable them for the historical behavior:

```bash
--no-dynamic-shots
```

### Automatic unique-source target

By default:

```text
--target-unique-clips 0
```

means automatic. tubeviz targets approximately one unique source clip per 2.4
seconds of track duration, capped by the number of READY clips in the library.
Thus a four-minute track aims for roughly 100 unique sources when the library is
large enough.

Novelty is semantic-bounded: tubeviz first takes the strongest semantic
fraction of candidates and then rewards unseen clips within that plausible
pool. It does not deliberately choose irrelevant footage just to satisfy a
quota.

Controls:

```text
--target-unique-clips
--novelty-weight
--novelty-candidate-fraction
--clip-reuse-cooldown
--scene-reuse-cooldown
```

Defaults:

```text
target unique clips        auto
novelty weight             0.65
semantic exploration pool  top 30%
clip reuse cooldown        20 shot/layer uses
scene reuse cooldown       48 shot/layer uses
```

For especially broad exploration:

```bash
tubeviz analyze song.mp3 \
  --library ./library \
  --semantic \
  --semantic-device cuda \
  --target-unique-clips 120 \
  --novelty-weight 0.8 \
  --clip-reuse-cooldown 28 \
  --scene-reuse-cooldown 64 \
  --selection-seed 42 \
  --output song.json
```

### Short excerpts from long clips

A selected indexed scene no longer implies that tubeviz needs to play its
entire detected duration. Each planned shot chooses a deterministic source
subrange appropriate to the musical shot length.

The default cap is:

```text
--source-excerpt-max-seconds 5
```

So a 30-second detected scene may contribute only a 1.0, 2.0, or 4.0 second
piece. Different shots/seeds can choose different offsets within that same
scene.

Controls:

```text
--min-shot-seconds 0.65
--max-shot-seconds 6.0
--source-excerpt-max-seconds 5.0
```

This means long archival videos are useful raw material without forcing long,
slow visual holds.

### Recommended four-minute EDM cut

The defaults are already novelty-aware and dynamic:

```bash
tubeviz analyze song.mp3 \
  --library ./library \
  --semantic \
  --semantic-device cuda \
  --max-video-layers 4 \
  --composition-intensity 1.3 \
  --transform-intensity 1.5 \
  --reshuffle \
  --output song.json
```

For a deliberately dense edit:

```bash
tubeviz analyze song.mp3 \
  --library ./library \
  --semantic \
  --semantic-device cuda \
  --target-unique-clips 110 \
  --novelty-weight 0.8 \
  --novelty-candidate-fraction 0.35 \
  --clip-reuse-cooldown 24 \
  --scene-reuse-cooldown 64 \
  --min-shot-seconds 0.55 \
  --max-shot-seconds 4 \
  --source-excerpt-max-seconds 3.5 \
  --selection-variation 0.45 \
  --reshuffle \
  --output song-dense.json
```

The analyze summary now reports both planned shot count and unique source usage.

The `/api/status` endpoint also reports:

```text
planned_shots
unique_primary_clips
unique_clips_with_companions
```

Multiple shots may share one musical `section_index`; transform cue updates now
key scene selections by both section and shot time so each fast shot retains
its own planned transform.

## v0.19 native rendering backend — Phase 1

v0.19 begins replacing the Chrome/Canvas final renderer with a native C++20
media pipeline. The existing browser renderer remains available and is still
the effect-parity reference while native GPU effects are ported.

The Phase-1 native path is:

```text
timeline JSON
    │
    ▼
Python native-manifest compiler
    │
    ▼
tubeviz-native-render (C++20)
    │
    ├─ libavformat/libavcodec decode
    ├─ sequential frame scheduling
    ├─ libswscale RGB conversion
    ├─ multi-source software composition
    ├─ source transforms
    └─ beat/tone reactive deformation
    │
    ▼
raw RGB24 stdout
    │
    ▼
FFmpeg encoder + original song audio
    │
    ▼
output video
```

There is no browser, Playwright, Canvas screenshot, PNG, or JPEG transport in
the native path. FFmpeg receives raw RGB frames directly from the C++ renderer.

### Build the native renderer

On Debian/Ubuntu:

```bash
sudo apt install \
  build-essential cmake pkg-config \
  libavformat-dev libavcodec-dev libavutil-dev libswscale-dev
```

Optional for the upcoming Vulkan/libplacebo phase:

```bash
sudo apt install libplacebo-dev libvulkan-dev
```

Inspect the current toolchain:

```bash
tubeviz native doctor
```

Build:

```bash
tubeviz native build
```

By default the executable is placed under:

```text
~/.cache/tubeviz/native-build/tubeviz-native-render
```

A custom build directory is supported:

```bash
tubeviz native build --build-dir ./build/native --jobs 12
```

### Rendering

`auto` is the default backend. It uses native rendering when a native executable
is found and otherwise falls back to Chrome:

```bash
tubeviz render song.json \
  --audio song.mp3 \
  --library ./library \
  --output song.mp4
```

Force native:

```bash
tubeviz render song.json \
  --audio song.mp3 \
  --library ./library \
  --output song-native.mp4 \
  --backend native
```

Build automatically if needed:

```bash
tubeviz render song.json \
  --audio song.mp3 \
  --library ./library \
  --output song-native.mp4 \
  --backend native \
  --native-build-if-missing
```

Use an explicit executable:

```bash
--native-binary /opt/tubeviz/bin/tubeviz-native-render
```

The generated native manifest can be retained for debugging:

```bash
--native-keep-manifest
```

### Phase-1 effect coverage

The native renderer currently implements:

```text
native sequential source decode
short source excerpts from v0.18
variable playback rate
reverse scheduling (seek-heavy until materialized/GPU phase)
mirror
brightness / contrast / saturation / grayscale
noise
scanlines
vignette
multi-source screen/multiply/overlay/lighten composition
crossfade between shots
beat-warp radial deformation
mid-frequency ripple/shear response
high-frequency chromatic displacement
energy bloom
harmonic-response gain
```

The native manifest consumes the existing `beat_warp`,
`video_edit_beat_warp`, `video_edit_ripple`, `video_edit_chroma_delay`,
`video_edit_vortex`, `energy_bloom`, and `harmonic_warp` timeline cues.

The native decoder is intentionally sequential: it seeks when entering a shot
or after a discontinuity, then decodes forward as output time advances. This
eliminates the old Chrome renderer's pathological per-output-frame media seeks.

### Browser parity

The browser backend remains available explicitly:

```bash
tubeviz render song.json \
  --audio song.mp3 \
  --library ./library \
  --backend browser \
  --browser-executable /usr/bin/google-chrome \
  --output song-browser.mp4
```

Several advanced Canvas effects have not yet been ported to native Phase 1,
including the full temporal-feedback graph, organic moving masks, recursive
slice effects, and the complete datamosh/VHS stack. Use the browser backend when
exact visual parity is more important than native decode performance.

### Phase 2: Vulkan/libplacebo

The native CMake project already detects and links `libplacebo` when available.
A first custom shader prototype lives at:

```text
native/shaders/beat_warp.glsl
```

The next phase moves the software RGB compositor/effect loops to persistent GPU
textures and libplacebo custom shaders, allowing decoded video textures,
history buffers, flow fields, beat uniforms, and final encoder frames to remain
GPU-resident.
