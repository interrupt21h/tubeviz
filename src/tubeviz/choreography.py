# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import math

from .library import SceneCandidate
from .models import Section, SectionAIDirection, SectionTrajectory, TrackAnalysis, VisualArcPoint


@dataclass(frozen=True)
class ChoreographyConfig:
    trajectory_strength: float = 0.85
    anticipation_seconds: float = 12.0
    visual_arc_strength: float = 0.70


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, float(value)))


def _smooth(values: list[float], radius: int = 1) -> list[float]:
    if not values:
        return []
    out: list[float] = []
    for i in range(len(values)):
        lo, hi = max(0, i-radius), min(len(values), i+radius+1)
        window = values[lo:hi]
        weights = [1.0 / (1.0 + abs((lo+j)-i)) for j in range(len(window))]
        out.append(sum(v*w for v, w in zip(window, weights)) / sum(weights))
    return out


def _section_tension(section: Section) -> float:
    semantic = section.audio_semantics
    semantic_tension = (
        semantic.get("tense", 0.0)
        + semantic.get("aggressive", 0.0)
        + semantic.get("kinetic", 0.0)
        + semantic.get("explosive", 0.0)
        + semantic.get("chaotic", 0.0)
    )
    return _clamp(
        .30*section.energy + .18*_clamp(section.onset_density/.65)
        + .15*section.percussive_ratio + .10*section.bass_weight
        + .10*section.brightness + .08*section.noisiness
        + .09*_clamp(semantic_tension*2.5)
        + .08*section.music_embedding_velocity + .05*section.music_embedding_novelty
    )


def _nearest_future_peak(sections: list[Section], index: int, tensions: list[float]) -> tuple[int | None, float | None]:
    current = tensions[index]
    best: tuple[int | None, float | None] = (None, None)
    for j in range(index+1, min(len(sections), index+5)):
        s = sections[j]
        elevated = tensions[j] >= max(.62, current + .07)
        labelled = s.label == "peak" or s.vibe in {"heavy", "euphoric", "fractured"}
        if elevated or labelled:
            best = (j, max(0.0, s.start - sections[index].end))
            break
    return best


def _phase(build: float, drop: float, release: float, tension: float, slope: float, label: str) -> str:
    if drop >= .62 or (label == "peak" and slope >= -.02):
        return "drop"
    if build >= .55:
        return "build"
    if release >= .55:
        return "release"
    if tension >= .68:
        return "sustain"
    return "space"


def _blend_direction(section: Section, trajectory: SectionTrajectory, cfg: ChoreographyConfig) -> SectionAIDirection | None:
    base = section.ai_direction
    if base is None:
        return None
    s = _clamp(cfg.trajectory_strength)
    # Builds accelerate visual density while preserving a little headroom for the drop.
    build = trajectory.build_probability
    drop = trajectory.drop_probability
    release = trajectory.release_probability
    desired_motion = _clamp(base.desired_motion + s*(.20*build + .24*drop - .16*release))
    desired_complexity = _clamp(base.desired_complexity + s*(.18*build + .28*drop - .18*release))
    edit_density = _clamp(base.edit_density + s*(.24*build + .20*drop - .22*release))
    arc = _clamp(cfg.visual_arc_strength, 0.0, 1.5)
    continuity = _clamp(
        base.continuity + s*(.18*release - .18*build - .28*drop)
        + arc*(.10*(1.0-drop) + .08*release - .12*drop)
    )
    vector_intensity = min(2.0, max(0.0, base.vector_intensity * (1 + s*(.22*build + .28*drop - .14*release))))
    codec_intensity = min(2.0, max(0.0, base.codec_intensity * (1 + s*(.16*build + .42*drop - .18*release))))
    return base.model_copy(update={
        "desired_motion": desired_motion,
        "desired_complexity": desired_complexity,
        "edit_density": edit_density,
        "continuity": continuity,
        "vector_intensity": vector_intensity,
        "codec_intensity": codec_intensity,
        "notes": (base.notes + f"; trajectory={trajectory.phase}").strip("; "),
    })


def attach_choreography(track: TrackAnalysis, config: ChoreographyConfig | None = None) -> TrackAnalysis:
    cfg = config or ChoreographyConfig()
    sections = list(track.sections)
    if not sections:
        return track
    raw_tension = [_section_tension(s) for s in sections]
    tensions = _smooth(raw_tension, radius=1)
    # Per-section slopes intentionally use neighboring section centers, not raw frame deltas;
    # the layer is planning phrases rather than detecting transients.
    slopes: list[float] = []
    for i, section in enumerate(sections):
        prev = tensions[i-1] if i else tensions[i]
        nxt = tensions[i+1] if i+1 < len(tensions) else tensions[i]
        slopes.append((nxt-prev)/2.0)

    updated: list[Section] = []
    arc: list[VisualArcPoint] = []
    for i, section in enumerate(sections):
        prev_t = tensions[i-1] if i else tensions[i]
        next_t = tensions[i+1] if i+1 < len(tensions) else tensions[i]
        slope = slopes[i]
        rising = _clamp((next_t-prev_t + .05)/.30)
        local_jump = _clamp((tensions[i]-prev_t + .03)/.28)
        future_idx, seconds_to_peak = _nearest_future_peak(sections, i, tensions)
        proximity = 0.0
        if seconds_to_peak is not None:
            proximity = _clamp(1.0 - seconds_to_peak/max(1.0, cfg.anticipation_seconds))
        build = _clamp(
            .38*rising + .25*proximity + .18*(section.label == "build")
            + .10*_clamp(section.onset_density/.60) + .09*section.energy
            + .08*section.music_embedding_velocity
        )
        drop = _clamp(
            .42*local_jump + .23*(section.label == "peak") + .16*section.energy
            + .11*section.percussive_ratio + .08*section.bass_weight
            + .12*section.music_embedding_novelty
        )
        falling = _clamp((prev_t-next_t + .05)/.30)
        release = _clamp(.52*falling + .24*(section.label == "breakdown") + .14*(1-section.energy) + .10*(section.vibe in {"ambient","hypnotic"}))
        phase = _phase(build, drop, release, tensions[i], slope, section.label)
        withholding = _clamp(build * proximity * (1.0-drop) * .85)
        trajectory = SectionTrajectory(
            tension=tensions[i], tension_slope=slope,
            build_probability=build, drop_probability=drop,
            release_probability=release, time_to_peak=seconds_to_peak,
            phase=phase, anticipation=proximity,
            withholding=withholding,
            target_motion=_clamp(.30 + .48*tensions[i] + .15*build + .12*drop - .16*release),
            target_complexity=_clamp(.28 + .44*tensions[i] + .20*build + .15*drop - .18*release),
            target_contrast=_clamp(.22 + .24*build + .45*drop - .22*release),
            target_edit_density=_clamp(.25 + .45*tensions[i] + .20*build + .12*drop - .23*release),
        )
        ai_direction = _blend_direction(section, trajectory, cfg)
        updated_section = section.model_copy(update={"trajectory": trajectory, "ai_direction": ai_direction})
        updated.append(updated_section)
        arc.append(VisualArcPoint(
            section_index=section.index,
            start=section.start,
            end=section.end,
            phase=phase,
            intensity=tensions[i],
            build=build,
            payoff=drop,
            continuity=(ai_direction.continuity if ai_direction else _clamp(.62-.42*trajectory.target_contrast)),
            visual_world=(ai_direction.visual_world if ai_direction else section.vibe),
        ))
    return track.model_copy(update={"sections": updated, "visual_arc": arc})


def shot_trajectory(section: Section, progress: float) -> dict[str, float]:
    """Continuous visual targets at normalized progress through a musical section."""
    t = section.trajectory
    if t is None:
        return {"motion": .5, "complexity": .5, "contrast": .35, "density": .5, "withhold": 0.0, "impact": 0.0}
    p = _clamp(progress)
    ease = p*p*(3.0-2.0*p)
    # Builds are deliberately nonlinear so the first half stays readable and the last quarter accelerates.
    build_ramp = ease**1.55
    impact = t.drop_probability * math.exp(-((p-.12)/.20)**2)
    release_ramp = t.release_probability * ease
    return {
        "motion": _clamp(t.target_motion + .26*t.build_probability*(build_ramp-.45) + .16*impact - .18*release_ramp),
        "complexity": _clamp(t.target_complexity + .23*t.build_probability*(build_ramp-.40) + .18*impact - .18*release_ramp),
        "contrast": _clamp(t.target_contrast + .30*t.build_probability*build_ramp + .22*impact - .15*release_ramp),
        "density": _clamp(t.target_edit_density + .30*t.build_probability*(build_ramp-.45) + .14*impact - .20*release_ramp),
        "withhold": _clamp(t.withholding * max(0.0, (p-.82)/.18)),
        "impact": _clamp(impact),
    }


def _feature(candidate: SceneCandidate, key: str, default: float) -> float:
    return float((candidate.visual_features or {}).get(key, default))


def trajectory_scene_score(candidate: SceneCandidate, section: Section, progress: float) -> float:
    target = shot_trajectory(section, progress)
    motion = _feature(candidate, "motion", .5)
    complexity = _feature(candidate, "complexity", .5)
    entropy = _feature(candidate, "visual_entropy", .5)
    brightness = _feature(candidate, "brightness", .5)
    motion_fit = 1.0-abs(motion-target["motion"])
    complexity_fit = 1.0-abs(complexity-target["complexity"])
    # Late builds reward increasingly information-rich imagery, while withholding
    # rewards a clean/simple image immediately before impact.
    richness = _clamp(.55*complexity + .30*entropy + .15*brightness)
    desired_richness = _clamp(.35 + .55*target["density"] - .58*target["withhold"])
    richness_fit = 1.0-abs(richness-desired_richness)
    return _clamp(.46*motion_fit + .36*complexity_fit + .18*richness_fit)


def effect_compatibility_score(candidate: SceneCandidate, section: Section) -> float:
    """Estimate whether the source can tolerate the section's intended FX treatment."""
    f = candidate.visual_features or {}
    if not f:
        return .5
    motion = _feature(candidate, "motion", .5)
    complexity = _feature(candidate, "complexity", .5)
    entropy = _feature(candidate, "visual_entropy", .5)
    cut_rate = _feature(candidate, "cut_rate", _feature(candidate, "change_rate", .2))
    family = section.ai_direction.effect_family if section.ai_direction and section.ai_direction.effect_family else None
    if family is None:
        family = {"heavy":"fracture","fractured":"fracture","driving":"hyper","euphoric":"prismatic","hypnotic":"liquid","ambient":"dream","dark":"analog"}.get(section.vibe,"cinematic")
    if family == "fracture":
        score = .35 + .40*complexity + .20*entropy + .05*(1-motion)
    elif family == "hyper":
        score = .30 + .45*motion + .15*entropy + .10*(1-cut_rate)
    elif family == "liquid":
        score = .38 + .32*(1-cut_rate) + .20*motion + .10*(1-complexity)
    elif family == "prismatic":
        score = .36 + .30*complexity + .22*(1-cut_rate) + .12*entropy
    elif family == "analog":
        score = .42 + .26*(1-cut_rate) + .18*(1-motion) + .14*entropy
    elif family == "dream":
        score = .48 + .26*(1-cut_rate) + .16*(1-motion) + .10*(1-complexity)
    else:
        score = .55 + .20*(1-cut_rate) + .15*(1-abs(complexity-.55)) + .10*(1-abs(motion-.5))
    # Already frantic footage needs fewer synthetic effects.
    overload = _clamp((motion + complexity + entropy + cut_rate - 2.45)/1.2)
    return _clamp(score - .28*overload)


def trajectory_transition_score(previous: SceneCandidate | None, candidate: SceneCandidate, section: Section, progress: float) -> float:
    if previous is None or not previous.visual_features or not candidate.visual_features:
        return .5
    target = shot_trajectory(section, progress)
    a, b = previous.visual_features, candidate.visual_features
    motion_delta = abs(float(a.get("motion", .5))-float(b.get("motion", .5)))
    complexity_delta = abs(float(a.get("complexity", .5))-float(b.get("complexity", .5)))
    brightness_delta = abs(float(a.get("brightness", .5))-float(b.get("brightness", .5)))
    contrast = _clamp(.42*motion_delta + .34*complexity_delta + .24*brightness_delta)
    desired = target["contrast"]
    return _clamp(1.0-abs(contrast-desired))
