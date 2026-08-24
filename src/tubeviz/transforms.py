# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .media import run_checked
from .models import CompositeLayer, DirectedTimeline, SceneSelection, Section, VideoTransform


@dataclass(frozen=True)
class TransformConfig:
    enabled: bool = True
    intensity: float = 1.0
    allow_reverse: bool = True
    max_playback_rate: float = 1.65
    min_playback_rate: float = 0.65


@dataclass(frozen=True)
class MaterializeConfig:
    width: int = 1280
    height: int = 720
    fps: int = 30
    crf: int = 20
    preset: str = "medium"


_BLEND_MODES = ("normal", "screen", "multiply", "overlay", "lighten")


def _stable_unit(value: str) -> float:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def plan_transform(
    section: Section,
    selection: SceneSelection,
    config: TransformConfig | None = None,
) -> VideoTransform:
    cfg = config or TransformConfig()
    if not cfg.enabled:
        return VideoTransform()

    intensity = _clamp(cfg.intensity, 0.0, 2.0)
    if section.ai_direction is not None:
        # AI direction modulates a user's global effect ceiling rather than
        # replacing it. Spacious sections naturally back off; complex/payoff
        # sections can use more of the configured budget.
        ai_scale = .62 + .50*section.ai_direction.desired_complexity + .20*section.ai_direction.edit_density
        intensity = _clamp(intensity * ai_scale, 0.0, 2.0)
    if intensity <= 0.0:
        return VideoTransform()
    energy = _clamp(section.energy, 0.0, 1.0)
    brightness = _clamp(section.brightness, 0.0, 1.0)
    density = _clamp(section.onset_density / 0.65, 0.0, 1.0)
    bass = _clamp(section.bass_weight, 0.0, 1.0)
    percussive = _clamp(section.percussive_ratio, 0.0, 1.0)
    tonal = _clamp(section.tonal_stability, 0.0, 1.0)
    noisiness = _clamp(section.noisiness, 0.0, 1.0)
    tempo_drive = _clamp((section.local_tempo_bpm - 80.0) / 80.0, 0.0, 1.0)
    vibe = section.vibe
    mutation = max(0, selection.occurrence - 1)
    salt = f"{selection.scene_id}:{section.index}:{selection.motif_id or '-'}"
    r1 = _stable_unit(salt + ":a")
    r2 = _stable_unit(salt + ":b")
    r3 = _stable_unit(salt + ":c")

    rate = 0.80 + energy * 0.42 + tempo_drive * 0.22 + (r1 - 0.5) * 0.08
    if section.label in {"ambient", "breakdown"} or vibe in {"ambient", "hypnotic"}:
        rate *= 0.90
    elif section.label == "peak" or vibe in {"driving", "euphoric"}:
        rate *= 1.08
    rate = 1.0 + (rate - 1.0) * intensity
    if selection.direction.rhythm_alignment > 0.0:
        # The visual director searched source offsets/rates for natural motion
        # accents that align with the music. Preserve that phase-lock while
        # retaining some section-level rate character.
        aligned = selection.direction.source_playback_rate
        weight = _clamp(0.42 + 0.48 * selection.direction.rhythm_alignment, 0.0, 0.92)
        rate = rate * (1.0 - weight) + aligned * weight
    rate = _clamp(rate, cfg.min_playback_rate, cfg.max_playback_rate)

    zoom = 1.015 + intensity * (0.05 + 0.14 * energy + 0.04 * mutation)
    pan_amount = intensity * (0.04 + 0.12 * density)
    hue = intensity * ((r2 - 0.5) * 22.0 + mutation * 7.0)
    saturation_target = _clamp(0.82 + brightness * 0.65 + energy * 0.18, 0.45, 1.8)
    contrast_target = _clamp(0.92 + energy * 0.38 + mutation * 0.06, 0.7, 1.75)
    brightness_target = _clamp(0.78 + brightness * 0.50 + energy * 0.16, 0.6, 1.45)
    saturation = _clamp(1.0 + (saturation_target - 1.0) * intensity, 0.3, 2.5)
    contrast = _clamp(1.0 + (contrast_target - 1.0) * intensity, 0.5, 2.2)
    css_brightness = _clamp(1.0 + (brightness_target - 1.0) * intensity, 0.5, 1.8)
    color = selection.direction.color
    if color.palette or selection.direction.motion_match > 0.0:
        hue = _clamp(
            hue * 0.35 + color.hue_shift_degrees * (0.35 + 0.35 * intensity),
            -180.0, 180.0,
        )
        saturation = _clamp(
            saturation * (0.72 + 0.28 * color.saturation_scale),
            0.25, 3.0,
        )
        contrast = _clamp(
            contrast * (0.78 + 0.22 * color.contrast_scale),
            0.45, 2.5,
        )
        css_brightness = _clamp(
            css_brightness * (0.82 + 0.18 * color.brightness_scale),
            0.45, 2.0,
        )
    feedback = _clamp(
        intensity * (0.05 + 0.18 * energy + 0.20 * tonal + 0.08 * mutation)
        * (1.25 if vibe in {"hypnotic", "dream"} else 1.0),
        0.0, 0.58,
    )
    glitch = _clamp(
        intensity * max(0.0, density - 0.16) * (0.18 + energy * 0.24 + noisiness * 0.28)
        * (1.35 if vibe == "fractured" else 1.0),
        0.0, 0.68,
    )
    noise = _clamp(intensity * (0.02 + 0.12 * energy + 0.05 * mutation), 0.0, 0.30)
    pixelate = _clamp(intensity * max(0.0, density - 0.30) * (0.20 + 0.30 * energy), 0.0, 0.55)
    rgb_split = _clamp(intensity * max(0.0, energy - 0.45) * (0.12 + 0.22 * density), 0.0, 0.42)
    scanlines = _clamp(intensity * (0.04 + 0.10 * mutation + 0.08 * (1.0 - brightness)), 0.0, 0.35)
    vignette = _clamp(0.12 + intensity * (0.10 + 0.15 * (1.0 - energy)), 0.0, 0.55)
    # These effects are applied to the already-composited video frame in the browser.
    # They deliberately remain modest as persistent treatments; musical edit cues pulse
    # them much harder at beats/bars/harmonic transitions.
    ripple = _clamp(intensity * (0.025 + 0.12 * density + 0.16 * bass + 0.06 * energy), 0.0, 0.42)
    kaleidoscope = _clamp(
        intensity * (0.015 + max(0.0, tonal - 0.55) * 0.14 + mutation * 0.025),
        0.0, 0.24,
    )
    # Rectangular tiling is intentionally retired; organic flow/vortex
    # transforms provide the same multi-image energy without boxed overlays.
    tiles = 0.0
    tunnel = _clamp(intensity * (0.015 + 0.05 * mutation + max(0.0, energy - 0.45) * 0.10 + bass * 0.07), 0.0, 0.32)
    posterize = _clamp(intensity * max(0.0, density - 0.32) * (0.15 + 0.22 * energy), 0.0, 0.48)
    edge = _clamp(intensity * (0.02 + 0.08 * energy + 0.09 * noisiness + 0.05 * (1.0 - brightness)), 0.0, 0.34)
    strobe = _clamp(intensity * max(0.0, energy - 0.66) * (0.18 + 0.22 * density), 0.0, 0.42)
    shutter = _clamp(intensity * max(0.0, density - 0.48) * (0.14 + 0.22 * energy), 0.0, 0.38)

    # Rendered-video temporal effects. These are intentionally modest as
    # persistent treatments; edit cues can push them much harder on musical events.
    slit_scan = _clamp(intensity * (0.012 + 0.10 * density + 0.08 * percussive + 0.025 * mutation), 0.0, 0.38)
    frame_echo = _clamp(intensity * (0.02 + 0.11 * energy + 0.14 * tonal + 0.025 * mutation), 0.0, 0.44)
    mirror_corridor = _clamp(intensity * (0.01 + 0.10 * mutation + 0.10 * max(0.0, energy - 0.60)), 0.0, 0.34)
    mask_wipe = _clamp(intensity * (0.02 + 0.10 * density + 0.05 * (1.0 - brightness)), 0.0, 0.30)
    solarize = _clamp(intensity * max(0.0, energy - 0.48) * (0.12 + 0.18 * density), 0.0, 0.34)

    datamosh = _clamp(intensity * max(0.0, density - 0.34) * (0.18 + 0.30 * energy), 0.0, 0.52)
    block_displace = _clamp(intensity * max(0.0, energy - 0.38) * (0.12 + 0.28 * density), 0.0, 0.48)
    chroma_delay = _clamp(intensity * (0.02 + 0.13 * energy + 0.07 * mutation), 0.0, 0.38)
    vhs_tracking = _clamp(intensity * (0.03 + 0.13 * (1.0 - brightness) + 0.10 * density), 0.0, 0.38)
    vortex = _clamp(intensity * (0.01 + 0.05 * mutation + max(0.0, energy - 0.52) * 0.12 + tonal * 0.08), 0.0, 0.36)
    motion_trails = _clamp(intensity * (0.02 + 0.12 * energy + 0.08 * density + 0.10 * tonal), 0.0, 0.48)
    slice_recursion = _clamp(intensity * max(0.0, density - 0.45) * (0.16 + 0.24 * energy), 0.0, 0.42)

    style_options = {
        "ambient": ("dream", "cinematic"),
        "hypnotic": ("dream", "recursive", "cinematic"),
        "dark": ("analog", "recursive", "cinematic"),
        "heavy": ("kinetic", "analog", "recursive"),
        "driving": ("kinetic", "cinematic", "fracture"),
        "euphoric": ("cinematic", "recursive", "kinetic"),
        "fractured": ("fracture", "datamosh", "analog"),
        "groove": ("cinematic", "analog", "kinetic"),
    }.get(vibe, ("cinematic",))
    style_index = int(_stable_unit(salt + ":style") * len(style_options)) % len(style_options)
    effect_style = selection.direction.effect_family or style_options[style_index]

    blur = 0.0 if energy > 0.45 else intensity * (1.0 - energy) * 1.4
    grayscale = _clamp((0.22 - brightness) * 1.6, 0.0, 0.35)

    reverse = bool(
        cfg.allow_reverse
        and intensity >= 0.6
        and mutation > 0
        and r3 > 0.72
        and section.label in {"build", "peak"}
    )
    mirror = bool(r1 > 0.78 or mutation % 3 == 2)
    blend = _BLEND_MODES[int(_stable_unit(salt + ":blend") * len(_BLEND_MODES)) % len(_BLEND_MODES)]
    if section.label == "ambient" and blend == "multiply":
        blend = "normal"

    return VideoTransform(
        playback_rate=rate,
        reverse=reverse,
        mirror=mirror,
        zoom=_clamp(zoom, 1.0, 1.55),
        pan_x=_clamp((r1 - 0.5) * 2.0 * pan_amount, -0.35, 0.35),
        pan_y=_clamp((r2 - 0.5) * 2.0 * pan_amount, -0.25, 0.25),
        rotation_degrees=_clamp((r3 - 0.5) * intensity * 2.4, -3.0, 3.0),
        brightness=css_brightness,
        contrast=contrast,
        saturation=saturation,
        hue_degrees=_clamp(hue, -45.0, 45.0),
        blur_px=_clamp(blur, 0.0, 3.0),
        grayscale=grayscale,
        feedback=feedback,
        glitch=glitch,
        noise=noise,
        pixelate=pixelate,
        rgb_split=rgb_split,
        scanlines=scanlines,
        vignette=vignette,
        ripple=ripple,
        kaleidoscope=kaleidoscope,
        tiles=tiles,
        tunnel=tunnel,
        posterize=posterize,
        edge=edge,
        strobe=strobe,
        shutter=shutter,
        slit_scan=slit_scan,
        frame_echo=frame_echo,
        mirror_corridor=mirror_corridor,
        mask_wipe=mask_wipe,
        solarize=solarize,
        datamosh=datamosh,
        block_displace=block_displace,
        chroma_delay=chroma_delay,
        vhs_tracking=vhs_tracking,
        vortex=vortex,
        motion_trails=motion_trails,
        slice_recursion=slice_recursion,
        effect_style=effect_style,
        blend_mode=blend,
    )


def attach_transform_plan(
    timeline: DirectedTimeline,
    config: TransformConfig | None = None,
) -> DirectedTimeline:
    section_map = {section.index: section for section in timeline.track.sections}
    updated: list[SceneSelection] = []
    for selection in timeline.scene_plan:
        section = section_map.get(selection.section_index)
        if section is None:
            updated.append(selection)
            continue
        primary_transform = plan_transform(section, selection, config)
        layer_transforms = []
        for idx, layer in enumerate(selection.layers):
            synthetic = selection.model_copy(update={
                "clip_id": layer.clip_id, "scene_id": layer.scene_id, "scene_index": layer.scene_index,
                "source_id": layer.source_id, "title": layer.title, "media_file": layer.media_file,
                "media_url": layer.media_url, "start": layer.start, "end": layer.end,
                "duration": layer.duration, "occurrence": selection.occurrence + idx + 1,
                "layers": [],
            })
            t = plan_transform(section, synthetic, config)
            # Companion layers should diverge spatially/colorimetrically from the primary.
            t = t.model_copy(update={
                "pan_x": _clamp(t.pan_x + (-0.12 if idx % 2 == 0 else 0.12), -0.5, 0.5),
                "rotation_degrees": _clamp(t.rotation_degrees + (-1.0 if idx % 2 == 0 else 1.0), -4.0, 4.0),
                "hue_degrees": _clamp(t.hue_degrees + (18.0 * (idx + 1)), -90.0, 90.0),
                "blend_mode": layer.blend_mode,
            })
            layer_transforms.append(layer.model_copy(update={"transform": t}))
        updated.append(selection.model_copy(update={
            "transform": primary_transform,
            "layers": layer_transforms,
        }))

    # Multiple shots may now exist inside one musical section, so section_index
    # alone is no longer a unique key. Match scene cues by section + cue time.
    by_scene = {
        (item.section_index, round(item.time, 6)): item
        for item in updated
    }
    cues = []
    for cue in timeline.cues:
        if cue.action in {"play_scene", "crossfade_scene"}:
            section_index = cue.parameters.get("section_index")
            key = (section_index, round(float(cue.time), 6))
            replacement = by_scene.get(key)
            if replacement is not None:
                cue = cue.model_copy(
                    update={"parameters": replacement.model_dump(mode="json")}
                )
        cues.append(cue)
    return timeline.model_copy(update={"scene_plan": updated, "cues": cues})


def _transform_key(selection: SceneSelection, source: Path, cfg: MaterializeConfig) -> str:
    payload = {
        "source": str(source.resolve()),
        "source_size": source.stat().st_size,
        "source_mtime_ns": source.stat().st_mtime_ns,
        "start": round(selection.start, 6),
        "end": round(selection.end, 6),
        "transform": selection.transform.model_dump(mode="json"),
        "render": cfg.__dict__,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _ffmpeg_filters(transform: VideoTransform, cfg: MaterializeConfig) -> list[str]:
    filters: list[str] = []
    zoom = max(1.0, transform.zoom)
    if zoom > 1.001:
        crop_w = 1.0 / zoom
        crop_h = 1.0 / zoom
        # pan -1..1 maps to the available crop travel.
        x_factor = (transform.pan_x + 1.0) / 2.0
        y_factor = (transform.pan_y + 1.0) / 2.0
        filters.append(
            f"crop=iw*{crop_w:.8f}:ih*{crop_h:.8f}:"
            f"(iw-out_w)*{x_factor:.8f}:(ih-out_h)*{y_factor:.8f}"
        )
    filters.append(f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=increase")
    filters.append(f"crop={cfg.width}:{cfg.height}")
    if transform.mirror:
        filters.append("hflip")
    if abs(transform.rotation_degrees) > 0.05:
        radians = transform.rotation_degrees * 3.141592653589793 / 180.0
        filters.append(f"rotate={radians:.9f}:fillcolor=black")
    if abs(transform.hue_degrees) > 0.05:
        filters.append(f"hue=h={transform.hue_degrees:.4f}")
    # ffmpeg eq brightness is additive (-1..1), unlike CSS brightness multiplier.
    eq_brightness = _clamp(transform.brightness - 1.0, -0.5, 0.5)
    filters.append(
        f"eq=brightness={eq_brightness:.5f}:contrast={transform.contrast:.5f}:"
        f"saturation={transform.saturation:.5f}"
    )
    if transform.grayscale > 0.01:
        sat = max(0.0, 1.0 - transform.grayscale)
        filters.append(f"hue=s={sat:.5f}")
    if transform.blur_px > 0.05:
        filters.append(f"gblur=sigma={min(10.0, transform.blur_px):.4f}")
    if transform.noise > 0.02:
        strength = int(round(2 + transform.noise * 28))
        filters.append(f"noise=alls={strength}:allf=t")
    if transform.feedback > 0.04:
        frames = max(2, min(6, 2 + int(round(transform.feedback * 6))))
        filters.append(f"tmix=frames={frames}")
    if transform.reverse:
        filters.append("reverse")
    if abs(transform.playback_rate - 1.0) > 0.001:
        filters.append(f"setpts=PTS/{transform.playback_rate:.8f}")
    filters.extend([f"fps={cfg.fps}", "setsar=1", "format=yuv420p"])
    return filters


def materialize_selection(
    selection: SceneSelection,
    *,
    library_root: Path,
    config: MaterializeConfig | None = None,
    force: bool = False,
) -> SceneSelection:
    cfg = config or MaterializeConfig()
    if selection.transform.materialized:
        existing = library_root / "transforms" / selection.media_file
        if existing.exists() and not force:
            return selection
    source = library_root / "normalized" / selection.media_file
    if not source.exists():
        raise FileNotFoundError(source)
    transform_id = _transform_key(selection, source, cfg)
    out_dir = library_root / "transforms"
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / f"{transform_id}.mp4"

    if force or not destination.exists():
        temp = destination.with_suffix(".tmp.mp4")
        duration = max(0.05, selection.end - selection.start)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{selection.start:.6f}",
            "-t", f"{duration:.6f}",
            "-i", str(source),
            "-map", "0:v:0",
            "-vf", ",".join(_ffmpeg_filters(selection.transform, cfg)),
            "-an",
            "-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(temp),
        ]
        try:
            run_checked(command)
            temp.replace(destination)
        finally:
            temp.unlink(missing_ok=True)

    rendered_duration = max(0.05, (selection.end - selection.start) / selection.transform.playback_rate)
    baked = selection.transform.model_copy(update={"materialized": True, "transform_id": transform_id})
    # Baked FFmpeg effects should not be applied a second time by CSS, but preserve
    # blend mode/feedback metadata for renderer overlays. playback_rate is now 1.
    live = baked.model_copy(update={
        "playback_rate": 1.0,
        "reverse": False,
        "mirror": False,
        "zoom": 1.0,
        "pan_x": 0.0,
        "pan_y": 0.0,
        "rotation_degrees": 0.0,
        "brightness": 1.0,
        "contrast": 1.0,
        "saturation": 1.0,
        "hue_degrees": 0.0,
        "blur_px": 0.0,
        "grayscale": 0.0,
        "noise": 0.0,
        "feedback": 0.0,
    })
    return selection.model_copy(update={
        "media_file": destination.name,
        "media_url": f"/transforms/{destination.name}",
        "start": 0.0,
        "end": rendered_duration,
        "duration": rendered_duration,
        "transform": live,
    })



def _materialize_composite_layer(
    layer: CompositeLayer,
    parent: SceneSelection,
    *,
    library_root: Path,
    config: MaterializeConfig | None = None,
    force: bool = False,
) -> CompositeLayer:
    synthetic = parent.model_copy(update={
        "clip_id": layer.clip_id, "scene_id": layer.scene_id, "scene_index": layer.scene_index,
        "source_id": layer.source_id, "title": layer.title, "media_file": layer.media_file,
        "media_url": layer.media_url, "start": layer.start, "end": layer.end, "duration": layer.duration,
        "transform": layer.transform, "layers": [],
    })
    baked = materialize_selection(synthetic, library_root=library_root, config=config, force=force)
    return layer.model_copy(update={
        "media_file": baked.media_file, "media_url": baked.media_url,
        "start": baked.start, "end": baked.end, "duration": baked.duration,
        "transform": baked.transform,
    })

def materialize_timeline(
    timeline: DirectedTimeline,
    *,
    library_root: Path,
    config: MaterializeConfig | None = None,
    force: bool = False,
) -> DirectedTimeline:
    updated = []
    for selection in timeline.scene_plan:
        baked_primary = materialize_selection(
            selection, library_root=library_root, config=config, force=force
        )
        baked_layers = [
            _materialize_composite_layer(
                layer, selection, library_root=library_root, config=config, force=force
            )
            for layer in selection.layers
        ]
        updated.append(baked_primary.model_copy(update={"layers": baked_layers}))
    by_section = {selection.section_index: selection for selection in updated}
    cues = []
    for cue in timeline.cues:
        if cue.action in {"play_scene", "crossfade_scene"}:
            replacement = by_section.get(cue.parameters.get("section_index"))
            if replacement is not None:
                cue = cue.model_copy(update={"parameters": replacement.model_dump(mode="json")})
        cues.append(cue)
    return timeline.model_copy(update={"scene_plan": updated, "cues": cues})
