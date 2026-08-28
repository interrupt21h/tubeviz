# tubeviz

[![CI](https://github.com/interrupt21h/tubeviz/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/interrupt21h/tubeviz/actions/workflows/ci.yml)

> AI-directed, beat-synchronized music video generation from a curated video library.

![tubeviz demo — Dream](dream.webp)

**tubeviz** turns a music track and a library of source footage into a beat-aligned,
AI-directed music video. It can acquire and curate footage, detect scenes, analyze music,
plan an edit, apply visual treatments, preview the result interactively, and render a
finished video.

The project supports both a browser-based **Studio** workflow and a full command-line
interface. Both operate on the same persistent media library and the same directed
timeline format.

> [!NOTE]
> **A hack that got out of hand** 🛠️
>
> Tubeviz started as a quick experiment to see whether video could be automatically cut to music. Then things escalated. It’s now a full video-analysis, composition, and rendering system—and it’s still very much a work in progress, so beware of rough edges and sudden changes.


## Sample videos

Complete videos produced with tubeviz:


- [Tubeviz - Empire of the Sun - Walking on a Dream](https://youtu.be/ST6Ei9oyc7w)
- [Tubeviz - Night Tapes - Drifting](https://youtu.be/Z5qFih1OKeo)
- [Tubeviz — Andrew Bayer feat. Alison May — Open End Resource (OCULA Remix)](https://youtu.be/8eqdMmgcG_4)
- [Tubeviz — Step It Up — Stereo MC's](https://youtu.be/nrYzxJzPYbE)

## Architecture

Tubeviz is built around a persistent clip library and a versioned **directed timeline**.
The timeline is a JSON production plan that separates analysis and editorial decisions
from playback and rendering. Once a timeline has been created, it can be previewed,
replanned, materialized, or rendered without repeating the complete ingest and analysis
workflow.

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "background": "#0b1020",
    "primaryColor": "#151b2f",
    "primaryTextColor": "#e8edf7",
    "primaryBorderColor": "#5ee7df",
    "lineColor": "#71809f",
    "secondaryColor": "#1a2036",
    "tertiaryColor": "#11172a",
    "clusterBkg": "#0d1325",
    "clusterBorder": "#34405f",
    "fontFamily": "Inter, ui-sans-serif, system-ui, sans-serif",
    "fontSize": "15px"
  },
  "flowchart": {
    "curve": "basis",
    "htmlLabels": false,
    "nodeSpacing": 48,
    "rankSpacing": 58,
    "diagramPadding": 20
  }
}}%%

flowchart TB

    subgraph INPUTS["INPUTS"]
        BRIEF["✦ Visual brief<br/>or search terms"]
        URLS["▶ Curated<br/>YouTube URLs"]
        AUDIO["♫ Music track"]
    end

    subgraph TV["TUBEVIZ"]
        STUDIO["Studio + CLI"]

        INGEST["Acquisition<br/>& ingest"]
        LIB[("Persistent<br/>clip library")]

        PLAN["Music analysis<br/>& visual direction"]
        TL[("Directed<br/>timeline JSON")]

        PREVIEW["Interactive<br/>preview"]
        RENDER["Browser or<br/>native renderer"]

        AUDIOPATH["♫ Audio source"]
    end

    OUTPUT["◆ Encoded music video"]

    BRIEF --> STUDIO
    URLS --> STUDIO
    AUDIO --> STUDIO

    STUDIO --> INGEST
    INGEST --> LIB

    STUDIO --> PLAN
    LIB --> PLAN

    PLAN --> TL

    TL --> PREVIEW
    TL --> RENDER

    LIB -.-> PREVIEW
    LIB -.-> RENDER

    AUDIO --> AUDIOPATH
    AUDIOPATH -.-> PLAN
    AUDIOPATH -.-> PREVIEW
    AUDIOPATH -.-> RENDER

    RENDER --> OUTPUT

    classDef input fill:#131a2d,stroke:#6878a5,stroke-width:1.5px,color:#e7ebf5;
    classDef process fill:#172036,stroke:#5ee7df,stroke-width:1.8px,color:#f4f8ff;
    classDef intelligence fill:#221b3d,stroke:#b794f6,stroke-width:2px,color:#f5efff;
    classDef storage fill:#101d29,stroke:#38bdf8,stroke-width:2px,color:#eaf9ff;
    classDef render fill:#252035,stroke:#f0abfc,stroke-width:2px,color:#fff1ff;
    classDef output fill:#103026,stroke:#6ee7b7,stroke-width:2.5px,color:#eafff5;
    classDef auxiliary fill:#111827,stroke:#64748b,stroke-width:1.3px,color:#cbd5e1;

    class BRIEF,URLS,AUDIO input;
    class STUDIO,INGEST,PREVIEW process;
    class PLAN intelligence;
    class LIB,TL storage;
    class RENDER render;
    class OUTPUT output;
    class AUDIOPATH auxiliary;

    style INPUTS fill:#0d1325,stroke:#34405f,stroke-width:1px,color:#94a3b8;
    style TV fill:#0d1325,stroke:#435170,stroke-width:1.5px,color:#cbd5e1;

    linkStyle default stroke:#71809f,stroke-width:1.5px;
```

Tubeviz combines several kinds of information when constructing an edit:

- beat, bar, onset, tempo, section, and phrase structure;
- optional learned audio representations and semantic audio analysis;
- detected source scenes, motion, complexity, palette, and temporal visual features;
- optional OpenCLIP embeddings and AI-generated visual descriptions;
- transition quality, novelty, clip reuse, curation preferences, and sequence continuity;
- transforms, compositing, temporal effects, vector treatments, and optional codec-space
  effects.

Source video remains the primary visual material. Effects are scheduled around the
footage rather than replacing it with a standalone audio-reactive shader.

## Contents

- [Quick start](#quick-start)
- [Requirements](#requirements)
- [Installation](#installation)
- [Studio](#studio)
- [AI configuration](#ai-configuration)
- [Building a footage library](#building-a-footage-library)
- [Curating the library](#curating-the-library)
- [Analyzing music and creating a timeline](#analyzing-music-and-creating-a-timeline)
- [Visual direction and effects](#visual-direction-and-effects)
- [Previewing](#previewing)
- [Rendering](#rendering)
- [Hardware acceleration](#hardware-acceleration)
- [FFglitch codec-space effects](#ffglitch-codec-space-effects)
- [Library layout](#library-layout)
- [Recommended workflow](#recommended-workflow)
- [Troubleshooting](#troubleshooting)
- [Command overview](#command-overview)
- [Development](#development)
- [License](#license)

## Quick start

For most users, Studio is the easiest way to work with tubeviz.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[semantic,audio-ai,render]'

tubeviz gui \
  --project-root "$PWD" \
  --library ./library
```

Studio opens in the browser, normally at:

```text
http://127.0.0.1:8090/
```

A typical project flow is:

```text
1. Build or import a footage library
2. Review, trim, reject, and enhance clips
3. Analyze a music track and create a directed timeline
4. Preview and adjust the edit
5. Render the final video
```

The same workflow can be performed entirely from the command line:

```bash
# Acquire footage.
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --results-per-term 10

# Analyze the track and construct an edit.
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --semantic \
  --output timelines/song.json

# Preview it.
tubeviz serve timelines/song.json \
  --library ./library \
  --audio audio/song.mp3

# Render it.
tubeviz render timelines/song.json \
  --library ./library \
  --audio audio/song.mp3 \
  --output output/song.mp4 \
  --backend auto
```

## Requirements

### Core requirements

- Python **3.11+**
- FFmpeg and ffprobe
- yt-dlp, installed with the Python package

### Optional components

| Capability | Additional requirements |
|---|---|
| Studio/browser preview | A current Chrome or Chromium browser |
| Browser offline rendering | Playwright and Chromium |
| Semantic visual selection | OpenCLIP dependencies and Pillow |
| Learned audio analysis | PyTorch, Transformers, and nnAudio |
| Native renderer | CMake, a C++20 compiler, pkg-config, and FFmpeg development libraries |
| Native Vulkan Creative FX | libplacebo and a working Vulkan driver/device |
| Native CUDA/NVDEC source decode | An FFmpeg build with CUDA hwaccel and a usable NVIDIA driver/runtime |
| Codec-space glitch effects | FFglitch `ffedit` |

### Linux system packages

#### Arch Linux / CachyOS

```bash
sudo pacman -S --needed \
  base-devel cmake pkgconf ffmpeg libplacebo vulkan-icd-loader \
  vulkan-tools curl unzip chromium
```

#### Debian / Ubuntu

```bash
sudo apt update
sudo apt install -y \
  build-essential cmake pkg-config ffmpeg curl unzip \
  libavformat-dev libavcodec-dev libavutil-dev libswscale-dev \
  libplacebo-dev libvulkan-dev vulkan-tools
```

Install Chrome/Chromium separately, or use Playwright's managed Chromium build with
`playwright install chromium`. Distribution packaging for Chromium differs between
Debian and Ubuntu.

The compiler, CMake, FFmpeg development headers, libplacebo, and Vulkan packages are
needed only for the native renderer and its optional GPU path. Browser rendering does
not depend on the native renderer.

## Installation

Clone the repository and install the base package:

```bash
git clone https://github.com/interrupt21h/tubeviz.git tubeviz
cd tubeviz
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Install all commonly used optional features:

```bash
pip install -e '.[semantic,audio-ai,render]'
```

The extras can also be installed independently:

| Extra | Purpose |
|---|---|
| `semantic` | OpenCLIP scene embeddings and image support |
| `audio-ai` | CLAP/MERT learned audio analysis |
| `render` | Playwright browser rendering |
| `dev` | Test dependencies |

If you want Playwright to manage its own Chromium build:

```bash
playwright install chromium
```

Verify the installation:

```bash
tubeviz --help
ffmpeg -version
```

For optional acceleration features, also run:

```bash
tubeviz native doctor
tubeviz audio-ai doctor
tubeviz music-ai doctor
tubeviz codec doctor
```

## Studio

Studio provides a browser interface over the same workflows exposed by the CLI.

```bash
tubeviz gui \
  --project-root /path/to/tubeviz-project \
  --library /path/to/tubeviz-project/library
```

Other launch examples:

```bash
tubeviz gui --library ./library --port 8095
tubeviz gui --library ./library --no-open
tubeviz gui --host 0.0.0.0 --port 8090
```

> When binding Studio to a non-loopback address, treat it as a local development service
> and place it behind appropriate network controls if other systems can reach it.

### Create

The **Create** interface covers the main production workflow:

- AI-assisted footage acquisition;
- manual YouTube URL ingest;
- music analysis and timeline generation;
- interactive preview;
- final rendering;
- native renderer build and diagnostics.

![tubeviz Studio — Create](screenshots/screenshot-create.png)

### Library

The **Library** interface is used to inspect and curate source footage. It supports:

- filtering and browsing clips;
- video playback;
- non-destructive In/Out trimming;
- rejection and restoration;
- permanent deletion;
- scene and metadata inspection;
- visual and AI analysis review.

![tubeviz Studio — Library](screenshots/screenshot-library.png)

The clip detail view places the trim controls beside the media so the usable range can
be adjusted while viewing the source.

![tubeviz Studio — Library clip details](screenshots/screenshot-library-detail.png)

### Jobs

Long-running operations appear in the **Jobs** panel with live output, progress,
elapsed time, and cancellation controls when supported.

![tubeviz Studio — Jobs](screenshots/screenshot-jobs.png)

### Command Center

The **Command Center** exposes CLI commands and their arguments from inside Studio. It is
useful for advanced operations that are not part of the curated Create or Library
panels.

![tubeviz Studio — Command Center](screenshots/screenshot-command.png)

For exact command syntax, the CLI remains the authoritative reference:

```bash
tubeviz --help
tubeviz analyze --help
tubeviz render --help
```

## AI configuration

Studio's **AI Settings** page is the central configuration surface for optional learned
and API-backed features.

![tubeviz Studio — AI Settings](screenshots/screenshot-ai.png)

Configuration includes:

- a master AI-feature switch;
- OpenAI API key;
- OpenAI-compatible base URL;
- shared OpenAI model;
- Hugging Face token;
- image detail and frame budget for visual description;
- API timeouts;
- storyboard/video-understanding controls.

Settings are stored outside the repository at:

```text
~/.config/tubeviz/config.json
```

or, when `XDG_CONFIG_HOME` is set:

```text
$XDG_CONFIG_HOME/tubeviz/config.json
```

Set `TUBEVIZ_CONFIG` to use a different configuration file.

Environment variables can also provide credentials:

```bash
export OPENAI_API_KEY='...'
export HF_TOKEN='hf_...'
```

### Hugging Face authentication

Public models can often be downloaded without a token, but a Hugging Face token is
useful for gated models, authenticated access, and rate limits.

```bash
export HF_TOKEN='hf_...'
```

A read token is sufficient for model downloads.

### AI video understanding

When enabled, tubeviz can analyze sampled frames from clips and store descriptions that
cover subjects, actions, location, camera language, lighting, palette, texture, mood,
editing utility, and scene-level characteristics.

This metadata supplements local measurements and OpenCLIP embeddings; it does not
replace deterministic scene analysis.

Existing clips can be analyzed from the CLI:

```bash
tubeviz library ai-describe --library ./library
```

Limit the operation or target a specific clip:

```bash
tubeviz library ai-describe --library ./library --limit 10
tubeviz library ai-describe --library ./library --clip-id 42 --force
```

## Building a footage library

The footage library is persistent. Downloaded media, scene indexes, thumbnails,
embeddings, trim ranges, curation state, provenance, and derived analysis can be reused
across many songs and timelines.

### Theme-first acquisition

A visual brief lets tubeviz generate a diverse set of searches and evaluate candidates
before committing to full downloads.

```bash
tubeviz ingest \
  --visual-brief 'A nocturnal electronic dream: fluorescent city motion, abstract machinery, wet streets, refracted glass, underground dance energy, cinematic movement. Avoid title cards, logos, talking heads, tutorials, and static footage.' \
  --audio audio/song.mp3 \
  --library ./library \
  --target-clips 40 \
  --acquisition-query-count 24 \
  --preview-gate \
  --preview-samples 4 \
  --preview-seconds 4 \
  --min-video-fitness 0.18 \
  --auto-trim
```

The preview gate evaluates short samples before a full download. It can reject footage
with insufficient motion or useful visual activity, excessive text overlays, dominant
talking heads, or other characteristics that make it a poor fit for music-video editing.

### Search-term acquisition

Create a text file containing one visual concept per line:

```text
underground techno warehouse strobe
laser tunnel rave crowd
analog CRT glitch surveillance
industrial machinery sparks
cyberpunk city rain neon
abstract liquid chrome macro
satellite earth night timelapse
high speed train tunnel POV
```

Then ingest it:

```bash
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --results-per-term 10 \
  --cookies-from-browser chrome
```

Semantic discovery and scene embedding can be enabled when the semantic extra is
installed:

```bash
tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --results-per-term 10 \
  --ai-discovery \
  --ai-query-expansion \
  --ai-query-count 8 \
  --ai-candidates-per-term 100 \
  --ai-device auto \
  --ai-index-scenes
```

Useful ingest controls include:

| Option | Purpose |
|---|---|
| `--results-per-term N` | Desired ready clips per search term |
| `--target-clips N` | Overall acquisition target for visual-brief planning |
| `--search-pool N` | Initial search result pool |
| `--max-search-pool N` | Maximum expanded search result pool |
| `--min-duration S` | Reject sources shorter than this |
| `--preferred-max-duration S` | Prefer shorter source videos |
| `--hard-max-duration S` | Reject sources longer than this; `0` disables |
| `--min-source-height PX` | Minimum accepted source height |
| `--max-source-height PX` | Maximum downloaded source height; `0` disables |
| `--media-prep auto\|source\|normalize` | Select source reuse or compatibility-proxy behavior |
| `--normalize-encoder auto\|nvenc\|x264` | Select proxy encoder |
| `--scene-threshold` | Scene-change sensitivity |
| `--min-scene-seconds` | Minimum indexed scene duration |
| `--cookies-from-browser` | Supply browser cookies through yt-dlp |
| `--preview-gate` | Evaluate samples before full download |
| `--auto-trim` | Derive usable In/Out bounds from edge scenes |

Use `tubeviz ingest --help` for the complete acquisition and filtering controls.

### Manual URL ingest

Known YouTube sources can be added directly:

```bash
tubeviz ingest-url \
  'https://www.youtube.com/watch?v=VIDEO_ID' \
  --library ./library
```

Multiple URLs are accepted:

```bash
tubeviz ingest-url URL1 URL2 URL3 \
  --library ./library \
  --term hand-picked
```

Manual ingest uses the same library pipeline as searched footage, including metadata,
duplicate checks, scene indexing, thumbnails, visual analysis, and optional semantic
indexing.

## Curating the library

Inspect basic library state:

```bash
tubeviz library stats --library ./library
tubeviz library list --library ./library --limit 50
tubeviz library list --library ./library --status ready
tubeviz library show VIDEO_ID --library ./library
```

### Reject and restore

Rejecting a clip is non-destructive and prevents it from being selected for future
output:

```bash
tubeviz library reject VIDEO_ID \
  --library ./library \
  --reason 'static talking-head footage'
```

Restore it later:

```bash
tubeviz library restore VIDEO_ID --library ./library
```

### Delete

Permanent deletion removes the clip and its tracked derived assets:

```bash
tubeviz library delete VIDEO_ID --library ./library
```

Use rejection when you may want to reconsider a clip. Use deletion when the source and
its generated assets should be removed completely.

### Trim usable source ranges

Studio supports non-destructive In/Out marks for clips containing intros, title cards,
credits, black leader, or other unusable edge material. The original source remains
unchanged; the saved usable range constrains future scene planning.

### Build or refresh visual indexes

Local temporal visual features:

```bash
tubeviz library visual-index --library ./library
```

OpenCLIP scene embeddings:

```bash
tubeviz library embed --library ./library --device auto
```

## Analyzing music and creating a timeline

The `analyze` command extracts musical structure and can immediately attach a scene plan
from the current library.

A useful general-purpose starting point is:

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --output timelines/song.json \
  --semantic \
  --semantic-device auto \
  --section-bars 8 \
  --max-video-layers 3 \
  --composition-intensity 1.2 \
  --transform-intensity 1.2 \
  --novelty-weight 0.65 \
  --visual-match-weight 1.25 \
  --transition-weight 0.7 \
  --vector-intensity 1.0 \
  --selection-variation 0.30 \
  --min-shot-seconds 0.65 \
  --max-shot-seconds 6.0 \
  --source-excerpt-max-seconds 5.0
```

The resulting timeline contains musical analysis, visual intent, selected footage,
source ranges, transforms, compositing, effect schedules, and provenance required by the
preview and rendering paths.

### Variable tempo and phrase choreography

Tubeviz can model local tempo instead of assuming one BPM for the entire track. Phrase
and section analysis can influence shot duration, visual intensity, anticipation before
peaks, and release after them.

Useful controls include:

```text
--section-bars
--tempo-window-seconds
--tempo-smoothing-seconds
--tempo-change-bpm
--trajectory-strength
--anticipation-seconds
--visual-arc-strength
```

### CLAP audio semantics

CLAP can classify sliding windows of the music and influence scene selection and visual
treatment:

```bash
tubeviz audio-ai doctor --device auto
```

Enable it during analysis:

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --output timelines/song.json \
  --semantic \
  --audio-ai \
  --audio-ai-device auto \
  --audio-ai-window 8 \
  --audio-ai-hop 4 \
  --audio-visual-match-weight 1.1
```

### MERT music representations

MERT can add learned structural representations for novelty and musical change:

```bash
tubeviz music-ai doctor --device auto
```

Enable it with:

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --music-ai \
  --music-ai-device auto \
  --output timelines/song.json
```

### AI director

When configured, the optional AI director can provide whole-song visual direction and
bounded editorial guidance while deterministic validation continues to control actual
scene IDs, durations, source availability, and renderer capabilities.

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --semantic \
  --ai-director \
  --output timelines/song.json
```

Studio can supply the configured API endpoint, model, and key automatically.

### Alternate cuts

Use a deterministic seed for reproducible variation:

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --selection-seed 12345 \
  --selection-variation 0.35 \
  --output timelines/song-alt.json
```

Or request a fresh seed:

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --reshuffle \
  --output timelines/song-alt.json
```

## Visual direction and effects

Tubeviz schedules effects according to musical and visual context. The renderer can mix
ordinary source transforms with semantic/temporal effects, vector treatments, layered
composition, and optional codec-space effects.

### Video-first transforms

Typical source treatments include:

- crop, scale, pan, rotation, and virtual-camera motion;
- flow and harmonic warp;
- pseudo-depth parallax;
- RGB displacement;
- bloom, streaks, scanlines, noise, and vignette;
- palette and contrast direction;
- beat-local deformation with musically selected push, pinch, shear, twist, wave, saddle, lens, and spiral motion;
- multi-source composition and crossfades.

The goal is to preserve source identity while creating motion and continuity that follow
the song.

### Semantic temporal effects

The creative renderer can combine persistent temporal state with source-derived visual
features. Depending on the planned shot, treatments can include:

- feedback and frame echo;
- motion trails;
- slit-scan/history effects;
- pixelation and posterization;
- solarization and edge extraction;
- glitch and block displacement;
- VHS-style tracking;
- ripple and tempo deformation;
- sparse depth, flow, and focal-point treatments.

Effect strength is controlled by the timeline and the analysis settings rather than by a
single global preset.

### Vector effects

Vector treatments derive structure from source imagery and motion. They can be used for
sparse outlines, motion-linked geometry, motif memory, and scene-responsive graphical
accents.

Control their overall contribution with:

```text
--vector-effects / --no-vector-effects
--vector-intensity
```

### Composition

Tubeviz can plan multiple simultaneous source layers when appropriate:

```text
--max-video-layers
--composition-intensity
--clip-opacity
--scene-crossfade
```

Higher values can produce denser edits, but one or two strong source layers are often
more readable than continuous maximum-density composition.

## Previewing

Serve an existing timeline:

```bash
tubeviz serve timelines/song.json \
  --library ./library \
  --audio audio/song.mp3
```

Studio also provides a managed preview action from the Create interface.

The interactive preview uses a responsive pipeline by default. Tubeviz prepares a
lightweight 720p/30fps preview-media cache independently of final-render media, adapts
its internal render resolution and layer count to the measured frame budget, and caps
live presentation near 30 fps. When WebGPU is available, source video surfaces are
composited directly as GPU external textures before the fused post-processing pass,
avoiding the full-frame Canvas2D composition copy. Canvas2D remains the compatibility
path.

Studio's **Preview decode** control normally chooses HTML video for the direct WebGPU
path and can use the worker WebCodecs decoder when Canvas fallback benefits from moving
decode work off the main thread. **Full fidelity** preview remains available when exact
browser-effect inspection matters more than interaction speed. Native/final rendering
never uses these preview-quality reductions.

For best browser GPU support:

- use a current Chrome or Chromium build;
- use a secure context or loopback address;
- keep the browser's hardware acceleration enabled;
- confirm the browser exposes WebGPU;
- avoid remote-display configurations that disable GPU access.

The preview HUD reports the active rendering path so it is possible to distinguish
WebGPU rendering from Canvas2D fallback.

## Rendering

Tubeviz offers two offline rendering backends:

- **native** — C++/FFmpeg renderer with optional libplacebo/Vulkan effects and
  CUDA/NVDEC source decode;
- **browser** — deterministic browser renderer using WebCodecs/WebGPU when available,
  with compatibility fallbacks.

`auto` prefers the native backend when a usable native renderer is available.

### Automatic backend

```bash
tubeviz render timelines/song.json \
  --library ./library \
  --audio audio/song.mp3 \
  --output output/song.mp4 \
  --backend auto \
  --width 1920 \
  --height 1080 \
  --fps 30 \
  --crf 20
```

### Native backend

Build it:

```bash
tubeviz native build --clean
```

Inspect the local toolchain and native build:

```bash
tubeviz native doctor
```

Render explicitly with the native backend:

```bash
tubeviz render timelines/song.json \
  --library ./library \
  --audio audio/song.mp3 \
  --output output/song.mp4 \
  --backend native \
  --width 1920 \
  --height 1080 \
  --fps 30 \
  --video-codec libx264 \
  --crf 20 \
  --native-preset veryfast \
  --native-decoder-cache 16 \
  --native-threads 0 \
  --native-gpu auto \
  --native-hwdecode auto \
  --native-build-if-missing
```

Native GPU controls:

| Option | Behavior |
|---|---|
| `--native-gpu auto` | Use libplacebo/Vulkan when a usable Vulkan device is available; otherwise use CPU effects |
| `--native-gpu vulkan` | Require the Vulkan creative-FX path |
| `--native-gpu off` | Disable native Vulkan effects |
| `--native-hwdecode auto` | Use CUDA/NVDEC when a compatible decoder/device is available |
| `--native-hwdecode cuda` | Require CUDA hardware decode |
| `--native-hwdecode off` | Use software source decode |

### Browser backend

```bash
tubeviz render timelines/song.json \
  --library ./library \
  --audio audio/song.mp3 \
  --output output/song-browser.mp4 \
  --backend browser \
  --width 1920 \
  --height 1080 \
  --fps 30 \
  --browser-transport auto \
  --browser-gpu auto \
  --browser-source-decode auto
```

Browser acceleration controls:

| Option | Purpose |
|---|---|
| `--browser-transport auto\|webcodecs\|raw` | Select encoded browser output or raw RGBA transport |
| `--browser-gpu auto\|webgpu\|off` | Select WebGPU composition behavior |
| `--browser-source-decode auto\|webcodecs\|video` | Select browser source-decoding path |
| `--webcodecs-bitrate N` | Override browser WebCodecs output bitrate; `0` selects automatically |

Use explicit `webgpu` or `webcodecs` modes when diagnosing acceleration. Use `auto` for
normal operation.

## Hardware acceleration

Tubeviz can use several independent acceleration paths. Availability of one does not
imply availability of the others.

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "background": "#ffffff",
    "primaryTextColor": "#f8fafc",
    "textColor": "#f8fafc",
    "lineColor": "#64748b",
    "edgeLabelBackground": "#1e293b",
    "fontFamily": "Inter, ui-sans-serif, system-ui, sans-serif",
    "fontSize": "16px"
  },
  "themeCSS": "
    .edgeLabel {
      background-color: #1e293b !important;
      color: #f8fafc !important;
      border-radius: 4px;
      padding: 2px 6px;
    }
    .edgeLabel p {
      color: #f8fafc !important;
      background-color: #1e293b !important;
    }
    .label text,
    .nodeLabel {
      font-weight: 600;
    }
  ",
  "flowchart": {
    "curve": "basis",
    "nodeSpacing": 45,
    "rankSpacing": 60
  }
}}%%

flowchart LR
    SRC["Source video"] --> DECODE{"Source decode"}

    DECODE -->|"CUDA / NVDEC"| CUDA["NVIDIA decode"]
    DECODE -->|"Software"| CPUDEC["CPU decode"]

    CUDA --> FX{"Creative FX"}
    CPUDEC --> FX

    FX -->|"libplacebo / Vulkan"| VK["GPU effects"]
    FX -->|"CPU"| CPUFX["CPU effects"]

    VK --> ENC["FFmpeg encoder"]
    CPUFX --> ENC

    classDef source fill:#172033,stroke:#64748b,stroke-width:2px,color:#f8fafc
    classDef decision fill:#4c1d5f,stroke:#a855f7,stroke-width:2px,color:#ffffff
    classDef gpu fill:#06384a,stroke:#06b6d4,stroke-width:2.5px,color:#ecfeff
    classDef cpu fill:#1e293b,stroke:#64748b,stroke-width:2px,color:#f8fafc
    classDef output fill:#641747,stroke:#ec4899,stroke-width:2.5px,color:#ffffff

    class SRC source
    class DECODE,FX decision
    class CUDA,VK gpu
    class CPUDEC,CPUFX cpu
    class ENC output

    linkStyle 0 stroke:#64748b,stroke-width:2px
    linkStyle 1,3,5,7 stroke:#06b6d4,stroke-width:3px
    linkStyle 2,4,6,8 stroke:#64748b,stroke-width:2px
```

### Native diagnostics

```bash
tubeviz native doctor
```

Also test the underlying runtimes directly when diagnosing GPU availability:

```bash
vulkaninfo --summary
nvidia-smi
ffmpeg -hide_banner -hwaccels
```

`libplacebo` being installed means the native renderer can be built with libplacebo
support; it does **not** guarantee that Vulkan can create a usable GPU device at runtime.
Likewise, `cuda` appearing in `ffmpeg -hwaccels` means the FFmpeg build advertises CUDA
support; actual source decoding still depends on the driver, codec, and runtime device.

### WSL notes

Under WSL, CUDA/NVDEC and Vulkan are separate paths:

- CUDA/NVDEC uses the NVIDIA Windows driver exposed to WSL;
- Vulkan requires a Vulkan implementation visible inside the Linux environment;
- libplacebo can only use Vulkan devices exposed by that Linux Vulkan stack.

If `vulkaninfo --summary` reports only a CPU renderer such as llvmpipe, native
libplacebo effects will not use the GPU. Resolve Vulkan device visibility before
troubleshooting tubeviz itself.

## FFglitch codec-space effects

FFglitch is optional. Tubeviz uses the external `ffedit` program to materialize true
codec-space motion-vector effects. Other FFglitch tools are not required for normal
tubeviz operation.

Check availability:

```bash
tubeviz codec doctor
```

### Linux x86-64 installation

Download the FFglitch release archive from the official FFglitch site, extract
`ffedit`, and place it on `PATH`. A user-local installation can use `~/.local/bin`:

```bash
mkdir -p ~/.local/bin
# Copy the extracted ffedit binary into ~/.local/bin/ffedit
chmod 0755 ~/.local/bin/ffedit
export PATH="$HOME/.local/bin:$PATH"
```

Verify it:

```bash
command -v ffedit
ffedit -h | head -40
tubeviz codec doctor
```

### Schedule codec effects

Codec-space effects can be included while analyzing a track:

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --codec-glitch musical \
  --codec-glitch-intensity 0.65 \
  --output timelines/song.json
```

Available scheduling profiles are:

```text
off
subtle
musical
aggressive
```

### Materialize codec shots

```bash
tubeviz codec materialize timelines/song.json \
  --library ./library
```

The rendered or previewed timeline can then reference the materialized codec-shot cache.

If FFglitch is unavailable, ordinary analysis, preview, vector effects, and rendering
remain usable.

## Library layout

A tubeviz library is self-contained and reusable. The exact set of derived directories
can vary with enabled features, but the high-level structure is:

```text
library/
├── metadata.sqlite3
├── originals/
├── normalized/
├── thumbnails/
├── metadata/
├── transforms/                 # created when transform materialization is used
├── codec-glitch/               # created when codec effects are materialized
└── browser-webcodecs-cache/    # created by accelerated browser rendering
```

SQLite stores clip metadata, discovery provenance, scenes, duplicate relationships,
trim ranges, tags, curation state, visual features, AI analysis, and scene embeddings.
Generated directories are created only when the corresponding workflow needs them.

### Tags and output pool

User tags are separate from acquisition/search terms. Search terms record how footage
entered the library; tags are for organizing footage for reuse. Studio can also maintain
an output pool that restricts planning to selected ready clips.

With an empty output pool, all eligible ready clips can be selected. When clips are
marked for output, analysis and replanning use only those marked clips. Clearing the pool
returns planning to the full ready library.

Do not treat generated cache directories as irreplaceable source media. The SQLite
library database and original source assets are the important persistent state.

## Recommended workflow

The following workflow works well for a full-length electronic track.

### 1. Build a diverse library

Start with a strong visual brief or a varied set of search concepts. Favor footage with
movement, changing composition, useful camera motion, and minimal persistent text.

```bash
tubeviz ingest \
  --visual-brief 'Kinetic nocturnal electronic imagery with industrial motion, neon infrastructure, crowds, transit, abstract macro textures, and cinematic movement.' \
  --audio audio/song.mp3 \
  --library ./library \
  --target-clips 50 \
  --preview-gate \
  --auto-trim
```

### 2. Curate it

Use Studio's Library view to reject weak material and trim intros/outros. A smaller,
high-quality pool usually produces better edits than a large pool full of visually
static sources.

### 3. Add semantic indexes

```bash
tubeviz library visual-index --library ./library
tubeviz library embed --library ./library --device auto
```

Optionally add AI visual descriptions from Studio or:

```bash
tubeviz library ai-describe --library ./library
```

### 4. Analyze the song

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --output timelines/song.json \
  --semantic \
  --semantic-device auto \
  --audio-ai \
  --audio-ai-device auto \
  --section-bars 8 \
  --max-video-layers 3 \
  --composition-intensity 1.2 \
  --transform-intensity 1.2 \
  --novelty-weight 0.65 \
  --visual-match-weight 1.25 \
  --transition-weight 0.7 \
  --vector-intensity 1.0 \
  --selection-variation 0.30 \
  --min-shot-seconds 0.65 \
  --max-shot-seconds 6 \
  --source-excerpt-max-seconds 5
```

Treat these values as a starting point rather than a required preset. Different music
benefits from different shot lengths, layer density, novelty, and effect intensity.

### 5. Preview and iterate

```bash
tubeviz serve timelines/song.json \
  --library ./library \
  --audio audio/song.mp3
```

If the material is good but the cut is not, create an alternate selection before
changing the visual-effect stack:

```bash
tubeviz analyze audio/song.mp3 \
  --library ./library \
  --semantic \
  --reshuffle \
  --output timelines/song-alt.json
```

### 6. Render

```bash
tubeviz render timelines/song.json \
  --library ./library \
  --audio audio/song.mp3 \
  --output output/song.mp4 \
  --backend auto \
  --width 1920 \
  --height 1080 \
  --fps 30 \
  --crf 20
```

## Troubleshooting

### YouTube returns 403 / Forbidden

Use current yt-dlp and, when necessary, browser cookies:

```bash
pip install -U yt-dlp

tubeviz ingest \
  --terms search_terms.txt \
  --library ./library \
  --cookies-from-browser chrome
```

If the failure is specific to one video, test it directly with yt-dlp before changing
tubeviz settings.

### Ingest appears slow

Large source files, high-resolution downloads, scene detection, preview sampling,
embedding generation, and AI description can each add significant work.

Useful checks:

```bash
tubeviz library stats --library ./library
```

Use Studio's Jobs panel to identify the active stage. To isolate bottlenecks, temporarily
disable optional analysis or reduce the candidate pool rather than assuming the download
itself is stalled.

### Native renderer cache or version mismatch

The native executable is built into a cache directory. If the Python CLI and native
binary appear out of sync, rebuild it cleanly:

```bash
tubeviz native build --clean
tubeviz native doctor
```

You can also inspect the executable reported by `native doctor` and run it directly with
`--version`.

### Native Vulkan effects are unavailable

Start with:

```bash
tubeviz native doctor
vulkaninfo --summary
```

Check both of the following:

1. `libplacebo` is visible to the build through `pkg-config`;
2. Vulkan can create a suitable runtime device.

For example:

```bash
pkg-config --modversion libplacebo
vulkaninfo --summary
```

If Vulkan sees only a CPU renderer, native GPU Creative FX will not be available even
though libplacebo is installed.

Use this render mode to make Vulkan failure explicit while diagnosing it:

```text
--native-gpu vulkan
```

Return to:

```text
--native-gpu auto
```

for normal operation with CPU fallback.

### CUDA/NVDEC is not being used

A native log line such as:

```text
decoder_open=... hw=software
```

means the source is being decoded on the CPU.

Test CUDA independently with the same source file:

```bash
nvidia-smi

ffmpeg -hide_banner -loglevel verbose \
  -hwaccel cuda \
  -hwaccel_output_format cuda \
  -i /path/to/source.mp4 \
  -frames:v 30 \
  -f null -
```

If that command fails, fix the FFmpeg/driver/runtime problem before troubleshooting the
tubeviz decoder.

Use this render mode to require CUDA during diagnosis:

```text
--native-hwdecode cuda
```

### Browser preview is using Canvas2D instead of WebGPU

Check:

- Chrome/Chromium is current;
- browser hardware acceleration is enabled;
- the preview is served from loopback or another secure context;
- `navigator.gpu` is available in DevTools;
- the preview HUD reports the WebGPU initialization reason;
- the GPU/driver is not blocked by the browser.

For normal interactive use, automatic fallback keeps the preview usable. For browser
offline-render diagnostics, require WebGPU explicitly:

```text
--browser-gpu webgpu
```

### Browser rendering is slow

Use automatic accelerated paths first:

```text
--browser-transport auto
--browser-gpu auto
--browser-source-decode auto
```

If the browser cannot use WebCodecs or WebGPU, the fallback paths can be substantially
slower at 1080p. Compare with the native backend when available.

### Studio Play reports no media

Confirm the clip has usable local media and inspect it from the CLI:

```bash
tubeviz library show VIDEO_ID --library ./library
```

If the clip was only partially ingested, reprocess or delete/reingest it as appropriate.

### Confirming which installation is running

```bash
command -v tubeviz
python -c 'import tubeviz, inspect; print(inspect.getfile(tubeviz))'
tubeviz --help
```

When developing from a checkout, activate the intended virtual environment before
launching Studio or rendering.

## Command overview

Top-level commands:

| Command | Purpose |
|---|---|
| `tubeviz ingest` | Search for footage and build/update the library |
| `tubeviz ingest-url` | Add explicit YouTube URLs |
| `tubeviz library ...` | Inspect, curate, describe, and index clips |
| `tubeviz analyze` | Analyze music and create a directed timeline |
| `tubeviz choreography` | Inspect phrase-level choreography |
| `tubeviz audio-ai ...` | CLAP audio-semantic tools |
| `tubeviz music-ai ...` | MERT music-representation tools |
| `tubeviz materialize` | Pre-render planned source transforms into a reusable cache |
| `tubeviz serve` | Serve an interactive timeline preview |
| `tubeviz render` | Render a finished video |
| `tubeviz codec ...` | Inspect and materialize FFglitch effects |
| `tubeviz native ...` | Build and diagnose the native renderer |
| `tubeviz gui` | Launch Studio |

Use the built-in help for the complete current option set:

```bash
tubeviz --help
tubeviz ingest --help
tubeviz ingest-url --help
tubeviz library --help
tubeviz analyze --help
tubeviz serve --help
tubeviz render --help
tubeviz codec --help
tubeviz native --help
```

## Development

Install the development dependencies:

```bash
pip install -e '.[dev,semantic,audio-ai,render]'
```

Run the test suite:

```bash
pytest
```

Useful focused diagnostics include:

```bash
tubeviz native doctor
tubeviz codec doctor
tubeviz audio-ai doctor
tubeviz music-ai doctor
```

Studio screenshots can be generated with the Playwright helper. For example, to capture the complete Library item inspector:

```bash
python scripts/screenshot_studio.py --tab library-details --full-details
```

Release history and implementation-specific changes are documented in
[`CHANGELOG.md`](CHANGELOG.md). The README is intended to describe the current user
workflow and supported capabilities.

## License

Tubeviz is licensed under the **Apache License 2.0**. See [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE).

### Third-party software, models, and media

Tubeviz integrates with external software and optional model providers, each of which is
subject to its own license and terms. Examples include FFmpeg, yt-dlp, Playwright,
OpenCLIP, PyTorch, Transformers, libplacebo, Vulkan implementations, and FFglitch.

Users are responsible for ensuring that source media is acquired and used in accordance
with applicable licenses, copyright law, platform terms, and any other relevant
permissions.
