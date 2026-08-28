#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text()


def write(path, text):
    (ROOT / path).write_text(text)


def replace_once(path, old, new):
    text = read(path)
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one occurrence, found {text.count(old)}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path, pattern, repl):
    text = read(path)
    new, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise SystemExit(f"{path}: regex expected once, got {count}: {pattern!r}")
    write(path, new)


# ---------------------------------------------------------------------------
# Models: explicit whole-song director moments + per-shot provenance.
# ---------------------------------------------------------------------------
replace_once(
    "src/tubeviz/models.py",
    "class SectionAIDirection(BaseModel):\n",
    '''class AIDirectorBeat(BaseModel):
    """A bounded creative idea authored by the whole-song LLM director.

    ``at`` is normalized section progress, not an exact edit time. The deterministic
    editor maps each idea to the nearest valid beat-aligned shot, so the LLM can
    author memorable moments without taking ownership of timing or media validity.
    """

    model_config = ConfigDict(extra="forbid")

    at: float = Field(ge=0.0, le=1.0)
    purpose: str = ""
    source_query: str = ""
    composition: str | None = None
    preferred_effects: list[str] = Field(default_factory=list)
    effect_bias: float = Field(default=1.0, ge=0.25, le=1.75)
    hero_kind: str | None = None
    history_mode: str = "auto"
    hold: bool = False


class SectionAIDirection(BaseModel):
''',
)
replace_once(
    "src/tubeviz/models.py",
    '    effect_family: str | None = None\n    desired_motion: float = Field(default=0.5, ge=0.0, le=1.0)\n',
    '''    effect_family: str | None = None
    # LLM-authored creative intent. The semantic/CLAP director leaves provenance
    # as ``semantic``; a successful whole-song language-model pass changes it to
    # ``llm`` and may author a few shot-local director beats.
    strategy: str = ""
    source_focus: str = ""
    transition_style: str = "auto"
    director_beats: list[AIDirectorBeat] = Field(default_factory=list)
    provenance: str = "semantic"
    director_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    desired_motion: float = Field(default=0.5, ge=0.0, le=1.0)
''',
)
replace_once(
    "src/tubeviz/models.py",
    '    # Advisory provenance from the bounded LLM edit-consultant pass. It records only\n    # validated candidate IDs/treatment hints; hard selection constraints remain deterministic.\n    ai_consultant: dict[str, Any] = Field(default_factory=dict)\n',
    '''    # Whole-song LLM provenance copied onto the final shot. This makes the
    # director's contribution inspectable in JSON and Studio instead of hiding it
    # behind scalar planner weights.
    ai_director: dict[str, Any] = Field(default_factory=dict)
    # Advisory provenance from the bounded LLM edit-consultant pass. It records only
    # validated candidate IDs/treatment hints; hard selection constraints remain deterministic.
    ai_consultant: dict[str, Any] = Field(default_factory=dict)
''',
)

# ---------------------------------------------------------------------------
# Whole-song director: stronger bounded authority and explicit creative beats.
# ---------------------------------------------------------------------------
replace_once(
    "src/tubeviz/ai_music_director.py",
    "from .audio_ai import top_audio_concepts\n",
    "from .audio_ai import top_audio_concepts\nfrom .ai_resources import COMPOSITION_MODES, HERO_EFFECTS, normalize_effect_name\n",
)
replace_once(
    "src/tubeviz/ai_music_director.py",
    '    semantic_strength: float = 0.75\n',
    '    semantic_strength: float = 1.0\n',
)
replace_once(
    "src/tubeviz/ai_music_director.py",
    '            "effect_family": "dream|liquid|analog|fracture|hyper|prismatic|cinematic",\n            "desired_motion": 0.5,\n',
    '''            "effect_family": "dream|liquid|analog|fracture|hyper|prismatic|cinematic",
            "strategy": "establish|develop|withhold|contrast|escalate|payoff|release|callback",
            "source_focus": "short retrieval/storytelling focus for this section",
            "transition_style": "auto|clean|hard|blend|echo|reset|inherit",
            "director_beats": [{
                "at": 0.72,
                "purpose": "one memorable shot-level idea",
                "source_query": "specific visual subject/action to favor for this moment",
                "composition": "single|flow|luma|strips|split|mosaic|swap|null",
                "preferred_effects": ["motion trails"],
                "effect_bias": 1.05,
                "hero_kind": "subject echo|flow melt|depth burst|time prism|recursive portal|null",
                "history_mode": "auto|inherit|reset",
                "hold": False
            }],
            "desired_motion": 0.5,
''',
)
replace_once(
    "src/tubeviz/ai_music_director.py",
    '        "Actively shape effect_density (how often effects become visible), temporal_persistence (whether trails/feedback can cross compatible cuts), composition_diversity (how often multi-source layouts evolve), and hero_frequency (rare large transformations). These are independent of amplitude/intensity. Treat source-first as the normal state: core-tier effects may remain subtle, accent-tier effects should be absent on most ordinary shots, and hero-tier effects should normally appear only for deliberate hero/payoff moments. Values around 0.55–0.90 are normal for effect density; use values above 1 primarily for genuinely high-energy drops/builds or intentionally experimental sections. It is valid to recommend no special effect for a shot/section. "\n',
    '''        "Your job is to make creative decisions that are recognizable in the finished edit, not merely return adjectives. Give each section a strategy and, when useful, 1–4 director_beats at normalized section progress. A director beat is a bounded shot-level idea: it may steer source retrieval, request a composition, choose a small effect vocabulary, preserve/reset temporal history, deliberately hold a clean shot, or request a hero treatment. The deterministic editor maps it to the nearest valid beat-aligned shot. Use source_query to ask for a concrete visual idea that the actual library can plausibly supply. Do not fill every shot with a beat: contrast and restraint make the directed moments legible. Mosaic/swap/split should be specific compositional ideas, not a section-long default unless there is an exceptional narrative reason. "
        "Actively shape effect_density (how often effects become visible), temporal_persistence (whether trails/feedback can cross compatible cuts), composition_diversity (how often multi-source layouts evolve), and hero_frequency (rare large transformations). These are independent of amplitude/intensity. Treat source-first as the normal state: core-tier effects may remain subtle, accent-tier effects should be absent on most ordinary shots, and hero-tier effects should normally appear only for deliberate hero/payoff moments. Values around 0.55–0.90 are normal for effect density; use values above 1 primarily for genuinely high-energy drops/builds or intentionally experimental sections. It is valid to recommend no special effect for a shot/section. "
''',
)
replace_once(
    "src/tubeviz/ai_music_director.py",
    '        "effect_family": proposed.effect_family or base.effect_family,\n        "desired_motion": mix(base.desired_motion, proposed.desired_motion),\n',
    '''        "effect_family": proposed.effect_family or base.effect_family,
        # Explicit creative intent is not numerically averaged away. Hard timing,
        # candidate validity and renderer safety remain deterministic downstream.
        "strategy": proposed.strategy or base.strategy,
        "source_focus": proposed.source_focus or base.source_focus,
        "transition_style": proposed.transition_style or base.transition_style,
        "director_beats": proposed.director_beats or base.director_beats,
        "provenance": proposed.provenance or base.provenance,
        "director_strength": proposed.director_strength or base.director_strength,
        "desired_motion": mix(base.desired_motion, proposed.desired_motion),
''',
)
replace_once(
    "src/tubeviz/ai_music_director.py",
    'def attach_llm_directions(track: TrackAnalysis, *, config: AIDirectorConfig, resource_manifest: dict[str, Any] | None = None, progress=print) -> TrackAnalysis:\n',
    '''def _sanitize_director_data(data: dict[str, Any]) -> dict[str, Any]:
    """Validate LLM-authored creative authority before Pydantic model loading."""
    out = dict(data)
    preferred = str(out.get("preferred_composition") or "").strip().lower().replace("_", " ")
    out["preferred_composition"] = preferred if preferred in COMPOSITION_MODES else None
    effects: list[str] = []
    for value in out.get("preferred_effects", []) or []:
        name = normalize_effect_name(value)
        if name and name not in effects:
            effects.append(name)
    out["preferred_effects"] = effects[:8]
    beats = []
    for raw in list(out.get("director_beats", []) or [])[:4]:
        if not isinstance(raw, dict):
            continue
        try:
            at = min(1.0, max(0.0, float(raw.get("at", 0.5))))
            effect_bias = min(1.75, max(0.25, float(raw.get("effect_bias", 1.0))))
        except (TypeError, ValueError):
            continue
        composition = str(raw.get("composition") or "").strip().lower().replace("_", " ")
        if composition not in COMPOSITION_MODES:
            composition = None
        hero = str(raw.get("hero_kind") or "").strip().lower().replace("_", " ") or None
        if hero not in HERO_EFFECTS:
            hero = None
        history = str(raw.get("history_mode") or "auto").strip().lower()
        if history not in {"auto", "inherit", "reset"}:
            history = "auto"
        beat_effects: list[str] = []
        for value in raw.get("preferred_effects", []) or []:
            name = normalize_effect_name(value)
            if name and name not in beat_effects:
                beat_effects.append(name)
        beats.append({
            "at": at,
            "purpose": str(raw.get("purpose") or "")[:240],
            "source_query": str(raw.get("source_query") or "")[:280],
            "composition": composition,
            "preferred_effects": beat_effects[:6],
            "effect_bias": effect_bias,
            "hero_kind": hero,
            "history_mode": history,
            "hold": bool(raw.get("hold", False)),
        })
    out["director_beats"] = beats
    out["strategy"] = str(out.get("strategy") or "")[:120]
    out["source_focus"] = str(out.get("source_focus") or "")[:280]
    transition = str(out.get("transition_style") or "auto").strip().lower()
    out["transition_style"] = transition if transition in {"auto", "clean", "hard", "blend", "echo", "reset", "inherit"} else "auto"
    out["provenance"] = "llm"
    return out


def attach_llm_directions(track: TrackAnalysis, *, config: AIDirectorConfig, resource_manifest: dict[str, Any] | None = None, progress=print) -> TrackAnalysis:
''',
)
replace_once(
    "src/tubeviz/ai_music_director.py",
    '        "resources": resource_manifest or {},\n',
    '        "resources": resource_manifest or {},\n        "director_schema": 2,\n',
)
replace_once(
    "src/tubeviz/ai_music_director.py",
    '        # Drop unknown keys rather than letting a chat model break timeline validation.\n        allowed = set(SectionAIDirection.model_fields)\n        data = {key: value for key, value in data.items() if key in allowed}\n',
    '''        # Drop unknown keys rather than letting a chat model break timeline validation.
        allowed = set(SectionAIDirection.model_fields)
        data = {key: value for key, value in data.items() if key in allowed}
        data = _sanitize_director_data(data)
''',
)
replace_once(
    "src/tubeviz/ai_music_director.py",
    '        # High CLAP uncertainty reduces how strongly the language model may pull\n        # choreography away from the deterministic baseline.\n        confidence = section.audio_semantic_confidence\n        strength = config.semantic_strength * (.35 + .65*confidence)\n        sections.append(section.model_copy(update={"ai_direction": _blend(base, proposed, strength)}))\n    return track.model_copy(update={"sections": sections})\n',
    '''        # CLAP remains grounding evidence, but a successful language-model
        # director is intentionally visible. Even low semantic confidence retains
        # at least 70% of the requested numeric authority; explicit director beats
        # are preserved wholesale and remain bounded by deterministic execution.
        confidence = section.audio_semantic_confidence
        strength = min(1.0, max(0.0, config.semantic_strength * (.70 + .30*confidence)))
        merged = _blend(base, proposed, strength).model_copy(update={
            "provenance": "llm", "director_strength": strength,
        })
        sections.append(section.model_copy(update={"ai_direction": merged}))
    directed = [s for s in sections if s.ai_direction is not None and s.ai_direction.provenance == "llm"]
    beat_count = sum(len(s.ai_direction.director_beats) for s in directed if s.ai_direction is not None)
    avg_strength = sum(s.ai_direction.director_strength for s in directed if s.ai_direction is not None) / max(1, len(directed))
    progress(f"AI director: applied LLM plan to {len(directed)}/{len(sections)} sections · {beat_count} creative beats · authority {avg_strength:.2f}")
    return track.model_copy(update={"sections": sections})
''',
)

# ---------------------------------------------------------------------------
# Scene planner: map LLM beats to exact valid shots, source ranking, composition,
# effects, hero moments and provenance without giving the LLM hard timing/media IDs.
# ---------------------------------------------------------------------------
replace_once(
    "src/tubeviz/scene_selector.py",
    'def _excerpt(candidate: SceneCandidate, shot_seconds: float, salt: str, cfg: SceneSelectorConfig) -> tuple[float, float]:\n',
    '''def _director_beat_assignments(section, windows: list[tuple[float, float]]) -> dict[int, object]:
    direction = section.ai_direction
    beats = list(direction.director_beats) if direction is not None else []
    if not beats or not windows:
        return {}
    span = max(0.05, float(section.end-section.start))
    mids = [min(1.0, max(0.0, (((a+b)*.5)-section.start)/span)) for a, b in windows]
    remaining = set(range(len(windows)))
    out: dict[int, object] = {}
    for beat in sorted(beats, key=lambda item: item.at):
        pool = remaining or set(range(len(windows)))
        index = min(pool, key=lambda i: (abs(mids[i]-beat.at), i))
        out[index] = beat
        remaining.discard(index)
    return out


def _excerpt(candidate: SceneCandidate, shot_seconds: float, salt: str, cfg: SceneSelectorConfig) -> tuple[float, float]:
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '        windows = _shot_windows(timeline, section, cfg)\n        consultant_advice: dict[int, dict[str, object]] = {}\n        consultant_hero_used = False\n',
    '''        windows = _shot_windows(timeline, section, cfg)
        director_beats = _director_beat_assignments(section, windows)
        consultant_advice: dict[int, dict[str, object]] = {}
        section_hero_used = 0
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '            shot_duration = max(0.05, shot_end - shot_start)\n\n            # Preserve motif source identity at the entry of a recurring motif,\n',
    '''            shot_duration = max(0.05, shot_end - shot_start)
            director_beat = director_beats.get(local_shot_index)
            director_query = str(getattr(director_beat, "source_query", "") or "").strip()
            director_query_vector = (
                embedder.encode_text([director_query])[0]
                if director_query and embedder is not None else None
            )
            director_query_scores = {
                candidate.scene_id: _semantic_score(
                    candidate,
                    query=director_query,
                    query_vector=director_query_vector,
                    embedding_map=all_embeddings,
                    visual_weight=cfg.visual_semantic_weight * 0.55,
                )
                for candidate in candidates
            } if director_query else {}

            # Preserve motif source identity at the entry of a recurring motif,
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '                    + cfg.preference_weight * _preference_score(candidate, preference_profile)\n                    + preference_bonus(candidate.scene_id, consultant_advice.get(local_shot_index), cfg.ai_consultant_weight)\n',
    '''                    + cfg.preference_weight * _preference_score(candidate, preference_profile)
                    # An explicit whole-song director beat gets a meaningful but
                    # bounded source-retrieval vote for this one shot.
                    + 0.70 * director_query_scores.get(candidate.scene_id, 0.0)
                    + preference_bonus(candidate.scene_id, consultant_advice.get(local_shot_index), cfg.ai_consultant_weight)
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '            if cfg.sequence_lookahead > 1 and len(candidates) > 1 and preferred_clip is None:\n',
    '            if cfg.sequence_lookahead > 1 and len(candidates) > 1 and preferred_clip is None and not director_query:\n',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '            advice = consultant_advice.get(local_shot_index) or {}\n            ai_density = section.ai_direction.effect_density if section.ai_direction is not None else 1.0\n            advice_bias = max(0.25, min(1.75, float(advice.get("effect_bias", 1.0) or 1.0)))\n            effective_density = max(0.0, min(2.5, cfg.effect_density * ai_density * advice_bias))\n            preferred_effects = list(section.ai_direction.preferred_effects if section.ai_direction is not None else [])\n            preferred_effects.extend(str(v) for v in advice.get("preferred_effects", []) if str(v))\n',
    '''            advice = consultant_advice.get(local_shot_index) or {}
            ai_density = section.ai_direction.effect_density if section.ai_direction is not None else 1.0
            advice_bias = max(0.25, min(1.75, float(advice.get("effect_bias", 1.0) or 1.0)))
            director_bias = float(getattr(director_beat, "effect_bias", 1.0) or 1.0)
            if bool(getattr(director_beat, "hold", False)):
                director_bias = min(director_bias, 0.45)
            effective_density = max(0.0, min(2.5, cfg.effect_density * ai_density * advice_bias * director_bias))
            preferred_effects = list(section.ai_direction.preferred_effects if section.ai_direction is not None else [])
            preferred_effects.extend(str(v) for v in getattr(director_beat, "preferred_effects", []) if str(v))
            preferred_effects.extend(str(v) for v in advice.get("preferred_effects", []) if str(v))
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '            requested_family = advice.get("effect_family")\n            requested_hero = advice.get("hero_kind")\n            if requested_hero and cfg.hero_frequency > 0.0 and not consultant_hero_used and direction.creative.hero_amount <= 0.01:\n',
    '''            requested_family = advice.get("effect_family")
            requested_hero = getattr(director_beat, "hero_kind", None) or advice.get("hero_kind")
            hero_budget = min(2, max(1, int(round(section.ai_direction.hero_frequency)))) if section.ai_direction is not None else 1
            if requested_hero and cfg.hero_frequency > 0.0 and section_hero_used < hero_budget and direction.creative.hero_amount <= 0.01:
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '                consultant_hero_used = True\n\n            layer_budget = max(1, min(4, int(cfg.max_video_layers)))\n',
    '                section_hero_used += 1\n\n            layer_budget = max(1, min(4, int(cfg.max_video_layers)))\n',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '            if section.energy < 0.30 or comp_strength <= 0.0:\n                desired_layers = 1\n',
    '''            explicit_composition = getattr(director_beat, "composition", None) or advice.get("composition_mode")
            if bool(getattr(director_beat, "hold", False)):
                explicit_composition = "single"
            if section.energy < 0.30 or comp_strength <= 0.0 or explicit_composition == "single":
                desired_layers = 1
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '            companions = _choose_companions(\n',
    '''            if explicit_composition and explicit_composition != "single" and layer_budget > 1:
                desired_layers = max(2, desired_layers)

            companions = _choose_companions(
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '            composition_mode = _composition_mode(\n                section.label,\n                section.energy,\n                shot_ordinal,\n                desired_layers,\n                section.vibe,\n                diversity=comp_diversity,\n                preferred=(advice.get("composition_mode") or (section.ai_direction.preferred_composition if section.ai_direction is not None else None)),\n            )\n',
    '''            # Section-level composition is a motif suggestion, not wallpaper.
            # Explicit director beats/consultant shots are honored; a broad section
            # preference is sampled at most periodically so "mosaic" cannot occupy
            # an entire section merely because the LLM mentioned it once.
            section_preferred = section.ai_direction.preferred_composition if section.ai_direction is not None else None
            sampled_section_preference = (
                section_preferred
                if not explicit_composition and section_preferred and comp_diversity >= 0.70
                and (shot_ordinal + section.index) % 4 == 0
                else None
            )
            composition_mode = _composition_mode(
                section.label,
                section.energy,
                shot_ordinal,
                desired_layers,
                section.vibe,
                diversity=comp_diversity,
                preferred=(explicit_composition or sampled_section_preference),
            )
''',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '                    intent_query=query,\n',
    '                    intent_query=(query + (f". director shot focus: {director_query}" if director_query else "")),\n',
)
replace_once(
    "src/tubeviz/scene_selector.py",
    '                    layers=composite_layers,\n                    ai_consultant={\n',
    '''                    layers=composite_layers,
                    ai_director={
                        "provenance": section.ai_direction.provenance,
                        "strength": section.ai_direction.director_strength,
                        "strategy": section.ai_direction.strategy,
                        "source_focus": section.ai_direction.source_focus,
                        "transition_style": section.ai_direction.transition_style,
                        "beat_applied": director_beat is not None,
                        "purpose": str(getattr(director_beat, "purpose", "") or ""),
                        "source_query": director_query,
                        "composition_mode": explicit_composition or sampled_section_preference,
                        "preferred_effects": list(getattr(director_beat, "preferred_effects", []) or []),
                        "effect_bias": director_bias,
                        "history_mode": str(getattr(director_beat, "history_mode", "auto") or "auto"),
                        "hero_kind": getattr(director_beat, "hero_kind", None),
                        "hold": bool(getattr(director_beat, "hold", False)),
                    } if section.ai_direction is not None and section.ai_direction.provenance == "llm" else {},
                    ai_consultant={
''',
)

# Explicit whole-song holds/heroes survive automatic hero scheduling; director
# history mode outranks the later bounded edit consultant when both are present.
replace_once(
    "src/tubeviz/creative_effects.py",
    '        creative = selection.direction.creative\n        if max(\n',
    '''        creative = selection.direction.creative
        if bool((selection.ai_director or {}).get("hold")):
            continue
        if creative.hero_kind and creative.hero_amount > 0.01:
            continue
        if max(
''',
)
replace_once(
    "src/tubeviz/creative_effects.py",
    '        advice = current.ai_consultant or {}\n        history_mode = str(advice.get("history_mode") or "auto").lower()\n',
    '''        director_advice = current.ai_director or {}
        advice = current.ai_consultant or {}
        history_mode = str(director_advice.get("history_mode") or advice.get("history_mode") or "auto").lower()
''',
)

# The bounded consultant should execute/refine the whole-song idea, not quietly
# invent an unrelated one for the same shot.
replace_once(
    "src/tubeviz/ai_edit_consultant.py",
    '        "You may ONLY rank scene_id values present in bounded_candidates. Never invent IDs, filenames, timestamps, clips, or effects. Prefer visual storytelling across the whole section: callbacks, contrast, human/abstract alternation, palette/motion progression, and payoff. "\n',
    '''        "You may ONLY rank scene_id values present in bounded_candidates. Never invent IDs, filenames, timestamps, clips, or effects. Prefer visual storytelling across the whole section: callbacks, contrast, human/abstract alternation, palette/motion progression, and payoff. The section's whole-song director plan is primary creative intent: reinforce its strategy and director_beats rather than replacing them; use your candidate ranking and shot advice to make those ideas feasible with the bounded material. "
''',
)

# ---------------------------------------------------------------------------
# Make the director's work visible in the live preview HUD.
# ---------------------------------------------------------------------------
replace_once(
    "src/tubeviz/static/index.html",
    '    #meta,#clip-meta { font-size:12px; opacity:.82; margin-top:6px; max-width:min(820px,80vw); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }\n    #clip-meta { opacity:.68; }\n',
    '''    #meta,#clip-meta,#director-meta { font-size:12px; opacity:.82; margin-top:6px; max-width:min(920px,84vw); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    #clip-meta { opacity:.68; }
    #director-meta { opacity:.90; color:#b9dcff; display:none; }
''',
)
replace_once(
    "src/tubeviz/static/index.html",
    '  <div id="clip-meta">Video renderer</div>\n  <div id="render-meta"',
    '  <div id="clip-meta">Video renderer</div>\n  <div id="director-meta"></div>\n  <div id="render-meta"',
)
replace_once(
    "src/tubeviz/static/visualizer.js",
    "const clipMeta = document.querySelector('#clip-meta');\nconst renderMeta = document.querySelector('#render-meta');\n",
    "const clipMeta = document.querySelector('#clip-meta');\nconst directorMeta = document.querySelector('#director-meta');\nconst renderMeta = document.querySelector('#render-meta');\n",
)
replace_once(
    "src/tubeviz/static/visualizer.js",
    "meta.textContent=`${tempoText} · ${timeline.track.key ?? 'key ?'} · ${timeline.track.sections.length} sections · ${timeline.motifs.length} motifs · ${status.scene_count ?? 0} scene groups`;\n",
    '''meta.textContent=`${tempoText} · ${timeline.track.key ?? 'key ?'} · ${timeline.track.sections.length} sections · ${timeline.motifs.length} motifs · ${status.scene_count ?? 0} scene groups`;
const llmSections=(timeline.track.sections??[]).filter(section=>section?.ai_direction?.provenance==='llm');
const llmBeats=llmSections.reduce((n,section)=>n+(section?.ai_direction?.director_beats?.length??0),0);
if(directorMeta&&llmSections.length){directorMeta.style.display='block';directorMeta.textContent=`AI director active · ${llmSections.length} sections · ${llmBeats} authored moments`;}
''',
)
replace_once(
    "src/tubeviz/static/visualizer.js",
    '    clipMeta.textContent=`${scene.term}${scene.motif_id?` · ${scene.motif_id} #${scene.occurrence}`:\'\'} · ${scene.composition_mode} · ${1+(scene.layers?.length??0)} video layers${align}${family}${vectors} · ${scene.title??scene.source_id}${fxNames?` · fx ${fxNames}`:\'\'}`;\n',
    '''    clipMeta.textContent=`${scene.term}${scene.motif_id?` · ${scene.motif_id} #${scene.occurrence}`:''} · ${scene.composition_mode} · ${1+(scene.layers?.length??0)} video layers${align}${family}${vectors} · ${scene.title??scene.source_id}${fxNames?` · fx ${fxNames}`:''}`;
    if(directorMeta){
      const section=(timeline.track.sections??[]).find(item=>Number(item.index)===Number(scene.section_index));
      const ai=section?.ai_direction??{};const authored=scene.ai_director??{};
      if(ai.provenance==='llm'){
        const beat=authored.beat_applied?` · moment: ${authored.purpose||authored.source_query||authored.hero_kind||authored.composition_mode||'directed accent'}`:'';
        const hold=authored.hold?' · HOLD CLEAN':'';const hero=authored.hero_kind?` · hero ${authored.hero_kind}`:'';
        directorMeta.style.display='block';directorMeta.textContent=`AI director · ${ai.strategy||'direct'} · ${ai.visual_world||ai.source_focus||'section plan'}${beat}${hero}${hold}`;
      }else{directorMeta.style.display='none';directorMeta.textContent='';}
    }
''',
)

# ---------------------------------------------------------------------------
# Defaults: when enabled, the LLM should have clear influence out of the box.
# ---------------------------------------------------------------------------
regex_once(
    "src/tubeviz/cli.py",
    r'(add_argument\(\s*["\']--ai-director-strength["\'][^\n]*?default\s*=\s*)0\.75',
    r'\g<1>0.95',
)
regex_once(
    "src/tubeviz/gui.py",
    r'(["\']ai_director_strength["\']\s*:\s*)0\.75',
    r'\g<1>0.95',
)
replace_once(
    "src/tubeviz/static/gui.html",
    '<label class="slider-field">AI director strength <span class="slider-value" data-for="aiDirectorStrength"></span><input id="aiDirectorStrength" type="range" min="0" max="1" step=".05" value=".75"><span class="slider-scale"><span>off 0</span><b>recommended .55–.85</b><span>full 1</span></span></label>',
    '<label class="slider-field">AI director strength <span class="slider-value" data-for="aiDirectorStrength"></span><input id="aiDirectorStrength" type="range" min="0" max="1" step=".05" value=".95"><span class="slider-scale"><span>subtle 0</span><b>director-led .8–1.0</b><span>full 1</span></span></label>',
)
replace_once(
    "src/tubeviz/static/gui.html",
    'Whole-song directing first receives a compact manifest of the actual output-pool clips and renderer capabilities. The optional bounded edit consultant then ranks only valid scene candidates retrieved by tubeviz. Both use the OpenAI base URL, model, and API key saved in <b>AI Settings</b>; deterministic timing and hard media constraints remain authoritative.',
    'Whole-song directing receives a compact manifest of the actual output-pool clips and renderer capabilities, then authors a section strategy plus a few visible shot-level creative moments. The bounded edit consultant ranks only valid scene candidates to execute that plan. Both use the OpenAI base URL, model, and API key saved in <b>AI Settings</b>; deterministic timing and hard media constraints remain authoritative.',
)

# CLI completion summary should prove whether the LLM actually contributed.
replace_once(
    "src/tubeviz/cli.py",
    '    ai_directed_sections = sum(section.ai_direction is not None for section in analysis.sections)\n',
    '''    ai_directed_sections = sum(section.ai_direction is not None for section in analysis.sections)
    llm_directed_sections = sum(bool(section.ai_direction and section.ai_direction.provenance == "llm") for section in analysis.sections)
    ai_director_beats = sum(len(section.ai_direction.director_beats) for section in analysis.sections if section.ai_direction is not None and section.ai_direction.provenance == "llm")
''',
)
replace_once(
    "src/tubeviz/cli.py",
    '        f"audio_ai_sections={audio_ai_sections} ai_directed_sections={ai_directed_sections}, "\n',
    '        f"audio_ai_sections={audio_ai_sections} ai_directed_sections={ai_directed_sections} llm_sections={llm_directed_sections} director_beats={ai_director_beats}, "\n',
)

# ---------------------------------------------------------------------------
# Release/cache markers.
# ---------------------------------------------------------------------------
for path in [
    "pyproject.toml",
    "src/tubeviz/__init__.py",
    "src/tubeviz/native_src/src/main.cpp",
    "src/tubeviz/static/index.html",
    "src/tubeviz/static/gui.html",
    "src/tubeviz/static/visualizer.js",
    "src/tubeviz/static/browser_gpu.js",
    "src/tubeviz/static/browser_gpu_worker.js",
    "src/tubeviz/static/browser_source.js",
]:
    text = read(path)
    if "0.42.2" in text:
        write(path, text.replace("0.42.2", "0.43.0"))

changelog = read("CHANGELOG.md")
entry = '''# Changelog

## 0.43.0 — AI director authority and visible creative intent

- Promote the whole-song LLM from a mostly invisible scalar bias to a bounded creative director that can author section strategies and 1–4 normalized director beats per section.
- Director beats can steer a concrete source query, composition, effect vocabulary, temporal-history behavior, clean holds and hero treatments while deterministic beat timing and valid media selection remain authoritative.
- Preserve explicit LLM creative moments instead of blending them back into CLAP; numeric direction now retains at least 70% of the requested authority when the director is enabled, with a director-led default strength of 0.95.
- Make broad section composition preferences periodic/soft so a single AI `mosaic` recommendation cannot turn into mosaic wallpaper across an entire section.
- Record whole-song director provenance on every final shot and show the current AI strategy/moment directly in the browser preview HUD.
- Report LLM-directed section and authored-moment counts in analyze progress/summary output and invalidate old whole-song director caches with the new schema.

'''
if changelog.startswith("# Changelog\n"):
    write("CHANGELOG.md", entry + changelog[len("# Changelog\n\n"):])
else:
    raise SystemExit("Unexpected CHANGELOG header")

# ---------------------------------------------------------------------------
# Regression coverage.
# ---------------------------------------------------------------------------
write("tests/test_ai_director_authority.py", '''# SPDX-License-Identifier: Apache-2.0
from tubeviz.ai_music_director import AIDirectorConfig, _blend, _director_prompt, _sanitize_director_data
from tubeviz.models import AIDirectorBeat, Section, SectionAIDirection, TrackAnalysis
from tubeviz.scene_selector import _director_beat_assignments


def _section(direction=None):
    return Section(
        index=0, start=0, end=8, energy=.72, label="build", local_tempo_bpm=124,
        percussive_ratio=.6, bass_weight=.55, vibe="driving",
        audio_semantic_confidence=.2, ai_direction=direction,
    )


def _track(direction=None):
    return TrackAnalysis(
        source="song.wav", duration=8, sample_rate=22050, hop_length=512,
        tempo_bpm=124, beats=[0, .5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5],
        bars=[], sections=[_section(direction)], events=[],
    )


def test_director_beat_model_is_bounded_and_explicit():
    beat=AIDirectorBeat(at=.75, purpose="payoff", source_query="faces emerge from smoke", composition="single", effect_bias=1.1, hero_kind="time prism")
    assert beat.at == .75
    assert beat.source_query.startswith("faces")
    assert beat.composition == "single"


def test_blend_preserves_explicit_director_moment_even_at_low_numeric_strength():
    base=SectionAIDirection(desired_motion=.2, strategy="establish")
    proposed=SectionAIDirection(desired_motion=.9, strategy="payoff", provenance="llm", director_beats=[AIDirectorBeat(at=.8, purpose="time prism payoff", hero_kind="time prism")])
    merged=_blend(base, proposed, .2)
    assert .2 < merged.desired_motion < .9
    assert merged.strategy == "payoff"
    assert merged.director_beats[0].hero_kind == "time prism"


def test_director_response_sanitizer_rejects_invented_capabilities():
    value=_sanitize_director_data({
        "preferred_composition":"mosaic",
        "preferred_effects":["motion trails", "invented laser"],
        "director_beats":[{
            "at":1.8, "composition":"invented layout", "preferred_effects":["ripple", "invented"],
            "hero_kind":"time_prism", "history_mode":"nonsense", "effect_bias":99,
        }],
    })
    assert value["preferred_composition"] == "mosaic"
    assert value["preferred_effects"] == ["motion trails"]
    beat=value["director_beats"][0]
    assert beat["at"] == 1.0
    assert beat["composition"] is None
    assert beat["preferred_effects"] == ["ripple"]
    assert beat["hero_kind"] == "time prism"
    assert beat["history_mode"] == "auto"
    assert beat["effect_bias"] == 1.75


def test_director_prompt_demands_visible_shot_level_creative_decisions():
    prompt=_director_prompt(_track())
    assert "director_beats" in prompt
    assert "recognizable in the finished edit" in prompt
    assert "not a section-long default" in prompt


def test_director_beats_map_to_nearest_distinct_valid_shots():
    direction=SectionAIDirection(director_beats=[
        AIDirectorBeat(at=.12, purpose="open"),
        AIDirectorBeat(at=.88, purpose="payoff"),
    ])
    windows=[(0,2),(2,4),(4,6),(6,8)]
    assigned=_director_beat_assignments(_section(direction), windows)
    assert assigned[0].purpose == "open"
    assert assigned[3].purpose == "payoff"


def test_director_config_defaults_to_full_numeric_authority_budget():
    assert AIDirectorConfig().semantic_strength == 1.0


def test_preview_exposes_director_provenance():
    index=(__import__('pathlib').Path(__file__).parents[1]/"src/tubeviz/static/index.html").read_text()
    js=(__import__('pathlib').Path(__file__).parents[1]/"src/tubeviz/static/visualizer.js").read_text()
    assert 'id="director-meta"' in index
    assert "AI director active" in js
    assert "beat_applied" in js
''')

print("AI director authority patch applied")
