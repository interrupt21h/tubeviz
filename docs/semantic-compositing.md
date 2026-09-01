# Semantic compositing

Tubeviz can optionally decompose library scenes into cached depth and semantic entity tracks before normal rendering. This stage is intentionally separate from the browser and native renderers: expensive ML analysis and semantic treatments are materialized first, then the resulting timeline remains a normal deterministic `DirectedTimeline`.

## Install optional dependencies

```bash
python -m pip install -e '.[semantic-compositing]'
```

SAM 2 and Video Depth Anything are external projects/model-weight dependencies and must be installed/configured separately when those backends are selected. The default `auto` modes fall back to deterministic OpenCV-based depth, detection, and optical-flow tracking when optional model runtimes are unavailable.

## Index a library

```bash
tubeviz-semantic --library ./library index --selected-only
```

The multi-entity indexer attempts open-vocabulary Grounding DINO detection followed by multi-object SAM 2 propagation. Typical configured concepts include people, dancers, animals, vehicles, architecture, sky, water, and trees. Each entity cache records its label, role, confidence, mean area, mean centroid, motion, and mask track.

To force lightweight processing:

```bash
tubeviz-semantic --library ./library index \
  --entity-detector classical \
  --entity-tracker classical \
  --depth-backend classical
```

Inspect one indexed scene:

```bash
tubeviz-semantic --library ./library inspect 123
```

## Entity-aware effects

Effects may target a specific entity, role, or label:

```bash
tubeviz-semantic --library ./library materialize 123 \
  --effect subject_echo \
  --target-label person \
  --amount 0.85 \
  --output person-echo.mp4
```

Multi-object primitives include `entity_split` for short semantic fragmentation events and `entity_outline` for tracked contour/glow treatment. `subject_isolate`, `subject_echo`, and mask transitions can target individual entities instead of an approximate center-of-frame subject.

## Semanticize a timeline

```bash
tubeviz-semantic --library ./library timeline dream.json \
  --auto-index \
  --output dream-semantic.json
```

The deterministic semantic director uses musical energy, bass, percussion, build/drop state, scene complexity, tracked motion, and entity count to choose a sparse treatment. Strong multi-entity fragmentation is treated as punctuation rather than being layered indiscriminately with every other effect.

Render the resulting timeline normally:

```bash
tubeviz render dream-semantic.json \
  --library ./library \
  --audio dream.mp3 \
  --output dream-semantic.mp4 \
  --backend native
```
