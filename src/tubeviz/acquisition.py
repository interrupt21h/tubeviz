# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json, re, urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .analysis import analyze_track
from .semantic import OpenClipEmbedder, SemanticConfig, cosine_similarity
from .visual_features import VisualFeatureConfig, analyze_scene_visuals


DEFAULT_NEGATIVES = (
    "large text title card", "logo intro on a plain background", "credits screen",
    "person talking directly to camera", "podcast interview", "news broadcast",
    "tutorial screen recording", "powerpoint presentation", "static slideshow",
    "low motion static shot", "advertisement product presentation",
)

@dataclass(frozen=True)
class AcquisitionConfig:
    visual_brief: str
    audio: str | None = None
    target_clips: int = 40
    query_count: int = 24
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout: float = 45.0
    negative_concepts: tuple[str, ...] = DEFAULT_NEGATIVES
    library_summary: str = ""

@dataclass
class AcquisitionPlan:
    brief: str
    audio_summary: str = ""
    queries: list[str] = field(default_factory=list)
    positive_concepts: list[str] = field(default_factory=list)
    negative_concepts: list[str] = field(default_factory=list)
    roles: list[dict] = field(default_factory=list)


def _audio_summary(path: str | None) -> str:
    if not path:
        return ""
    a = analyze_track(path)
    vibes = []
    for s in a.sections:
        if s.vibe not in vibes: vibes.append(s.vibe)
    energies = [s.energy for s in a.sections]
    return (f"duration={a.duration:.1f}s tempo≈{a.tempo_bpm:.1f} BPM; "
            f"vibes={', '.join(vibes[:8])}; sections={len(a.sections)}; "
            f"energy range={min(energies or [0]):.2f}-{max(energies or [0]):.2f}")


def _clean_search_query(value: str, *, max_chars: int = 96) -> str:
    """Normalize planner output into something YouTube search can actually use.

    A visual brief is prose; a YouTube query should be a short subject/motion/style
    phrase. Negative constraints are evaluated later by OpenCLIP and must not be
    appended to the search string.
    """
    value = re.sub(r"https?://\S+", " ", str(value))
    value = re.sub(r"\b(?:avoid|without|exclude)\b.*$", " ", value, flags=re.I)
    value = re.sub(
        r"\b(?:no\s+text|no\s+logos?|no\s+talking\s+heads?|no\s+tutorials?|"
        r"talking\s+heads?|title\s+cards?|logos?|tutorials?|podcasts?|news\s+broadcasts?)\b",
        " ", value, flags=re.I,
    )
    value = re.sub(r"[^\w\-']+", " ", value, flags=re.UNICODE)
    words = value.split()
    # Search result quality falls off quickly with paragraph-sized queries. Keep
    # enough words for subject + motion + cinematography, but never prose.
    if len(words) > 10:
        words = words[:10]
    value = " ".join(words).strip()
    if len(value) > max_chars:
        value = value[:max_chars].rsplit(" ", 1)[0].strip()
    return value


def _brief_visual_phrases(brief: str) -> list[str]:
    # Discard explicit negative guidance before deriving positive search concepts.
    positive = re.split(r"\bavoid\b\s*:?", brief, maxsplit=1, flags=re.I)[0]
    chunks = re.split(r"[\n.;:]+|,", positive)
    stop = {
        "create", "feel", "favor", "visual", "visuals", "world", "footage", "video",
        "electronic", "energy", "should", "into", "from", "with", "that", "this",
        "very", "more", "like", "alive", "evolving", "communal", "release",
    }
    out: list[str] = []
    for chunk in chunks:
        words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", chunk) if w.lower() not in stop]
        if not words:
            continue
        # Preserve compact concrete noun phrases; very long emotional prose is
        # reduced to its most searchable words.
        if len(words) > 7:
            concrete = [w for w in words if len(w) >= 4]
            words = (concrete or words)[:6]
        phrase = _clean_search_query(" ".join(words))
        if len(phrase.split()) >= 2 and phrase.lower() not in {x.lower() for x in out}:
            out.append(phrase)
    return out


def _heuristic_plan(cfg: AcquisitionConfig, audio_summary: str) -> AcquisitionPlan:
    brief = " ".join(cfg.visual_brief.split())
    phrases = _brief_visual_phrases(brief)
    if not phrases:
        phrases = ["cinematic night movement", "abstract light motion", "dynamic crowd movement"]

    modifiers = [
        "cinematic night", "handheld cinematic", "slow motion", "moving camera",
        "POV night", "rain reflections", "silhouette motion", "atmospheric night",
        "kinetic movement", "close up cinematic", "wide cinematic", "light haze",
    ]
    role_queries = [
        "night train window reflections", "subway tunnel POV night",
        "rainy city streets cinematic", "neon rain reflections",
        "underground club dancing handheld", "warehouse rave crowd silhouettes",
        "friends dancing nightclub candid", "crowd hands up strobe lights",
        "nightlife street handheld cinematic", "people running city streets night",
        "club crowd euphoric slow motion", "laser haze dancing silhouettes",
        "blurred city lights moving car", "night subway escalator cinematic",
        "friends embracing nightclub", "crowd dancing colored lights",
        "rain window bokeh night", "POV walking city night",
        "underground station cinematic", "night bus window city lights",
        "small club crowd dancing", "warehouse rave handheld",
        "crowd jumping nightclub", "city tunnel forward motion",
    ]

    queries: list[str] = []
    def add(q: str) -> None:
        q = _clean_search_query(q)
        if not q:
            return
        if q.lower() not in {x.lower() for x in queries}:
            queries.append(q)

    # First preserve the concrete subjects explicitly requested by the brief.
    for i, phrase in enumerate(phrases):
        add(f"{phrase} {modifiers[i % len(modifiers)]} motion")
        if len(queries) >= cfg.query_count:
            break
    # Then fill distinct cinematic roles. These are deliberately short; negative
    # constraints belong in semantic rejection, not YouTube search syntax.
    for q in role_queries:
        if len(queries) >= cfg.query_count:
            break
        add(q)
    # Finally combine remaining concrete concepts with varied camera/motion styles.
    n = 0
    while len(queries) < cfg.query_count and phrases:
        add(f"{phrases[n % len(phrases)]} {modifiers[(n + len(phrases)) % len(modifiers)]}")
        n += 1
        if n > cfg.query_count * 4:
            break

    return AcquisitionPlan(
        brief=brief, audio_summary=audio_summary, queries=queries[:cfg.query_count],
        positive_concepts=[brief, *phrases[:12], "dynamic cinematic music video footage", "strong visual motion"],
        negative_concepts=list(cfg.negative_concepts),
        roles=[{"role":"atmosphere","need":.5},{"role":"build","need":.75},{"role":"drop","need":1.0},{"role":"transition","need":.7}],
    )

def plan_acquisition(cfg: AcquisitionConfig, progress: Callable[[str],None]=print) -> AcquisitionPlan:
    audio_summary = _audio_summary(cfg.audio)
    if not cfg.llm_base_url or not cfg.llm_model:
        progress("Acquisition planner: deterministic fallback (no LLM endpoint/model configured)")
        return _heuristic_plan(cfg, audio_summary)
    schema = {
      "queries":["youtube search query"], "positive_concepts":["visual description"],
      "negative_concepts":["visual anti-pattern"],
      "roles":[{"role":"intro/build/drop/breakdown/transition","need":0.8,"queries":["query"]}]
    }
    prompt = f'''Design a visual acquisition plan for an AI music-video editor. Return ONLY JSON matching this shape: {json.dumps(schema)}.
Create {cfg.query_count} concrete YouTube search queries optimized for visually dynamic reusable footage, not commentary. Diversify subject, scale, motion, texture and camera behavior. Explicitly avoid title cards, logos, credits, talking heads, tutorials, news, static shots and text-heavy footage. Queries should be short and searchable, not prose.
VISUAL BRIEF: {cfg.visual_brief}
AUDIO SUMMARY: {audio_summary or 'not supplied'}
CURRENT LIBRARY COVERAGE: {cfg.library_summary or 'unknown'}
Prefer queries that fill coverage gaps rather than duplicating an already saturated visual vocabulary.'''
    payload = json.dumps({"model":cfg.llm_model,"temperature":.7,"messages":[
        {"role":"system","content":"You are a cinematographer and footage acquisition planner. Output strict JSON only."},
        {"role":"user","content":prompt}]}).encode()
    headers={"Content-Type":"application/json"}
    if cfg.llm_api_key: headers["Authorization"]="Bearer "+cfg.llm_api_key
    try:
        req=urllib.request.Request(cfg.llm_base_url.rstrip('/')+'/chat/completions',data=payload,headers=headers,method='POST')
        with urllib.request.urlopen(req,timeout=cfg.llm_timeout) as r: raw=json.loads(r.read().decode())
        text=raw['choices'][0]['message']['content'].strip()
        text=re.sub(r'^```(?:json)?\s*|\s*```$','',text,flags=re.I)
        obj=json.loads(text)
        q=[]
        def add_query(value):
            x=_clean_search_query(str(value))
            if x and x.lower() not in {v.lower() for v in q}: q.append(x)
        for x in obj.get('queries',[]): add_query(x)
        for role in obj.get('roles',[]):
            for x in role.get('queries',[]) if isinstance(role,dict) else []: add_query(x)
        if not q: raise ValueError('LLM returned no usable short queries')
        # Fill shortfalls deterministically rather than silently returning fewer
        # than --acquisition-query-count searches.
        if len(q) < cfg.query_count:
            for x in _heuristic_plan(cfg,audio_summary).queries:
                add_query(x)
                if len(q) >= cfg.query_count: break
        progress(f"Acquisition planner: LLM ({cfg.llm_model}); queries={min(len(q),cfg.query_count)}")
        return AcquisitionPlan(brief=cfg.visual_brief,audio_summary=audio_summary,queries=q[:cfg.query_count],
            positive_concepts=[str(x) for x in obj.get('positive_concepts',[])][:24] or [cfg.visual_brief],
            negative_concepts=list(dict.fromkeys([*cfg.negative_concepts,*[str(x) for x in obj.get('negative_concepts',[])]]))[:32],
            roles=[x for x in obj.get('roles',[]) if isinstance(x,dict)][:16])
    except Exception as exc:
        progress(f"Acquisition LLM fallback: {exc}")
        return _heuristic_plan(cfg,audio_summary)


def preview_fitness(media: str|Path, *, duration: float, embedder: OpenClipEmbedder,
                    positive_concepts: list[str], negative_concepts: list[str]) -> dict:
    path=Path(media)
    feat=analyze_scene_visuals(path,start=0,end=max(.2,duration),config=VisualFeatureConfig(fps=4,max_frames=64))
    # The preview itself is represented by several extracted thumbnails. OpenCLIP provides
    # semantic/text/talking-head/title-card rejection while temporal DSP measures motion.
    import subprocess, tempfile
    with tempfile.TemporaryDirectory(prefix='tubeviz-preview-frames-') as td:
        pattern=str(Path(td)/'%03d.jpg')
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(path),'-vf','fps=1,scale=320:-2','-frames:v','12',pattern],check=True)
        frames=sorted(Path(td).glob('*.jpg'))
        ivecs=embedder.encode_images(frames) if frames else np.empty((0,0),dtype=np.float32)
    pvecs=embedder.encode_text(positive_concepts or ['dynamic cinematic footage'])
    nvecs=embedder.encode_text(negative_concepts or list(DEFAULT_NEGATIVES))
    pos=float(np.mean([max(cosine_similarity(v,p) for p in pvecs) for v in ivecs])) if len(ivecs) and len(pvecs) else 0
    neg=float(np.mean([max(cosine_similarity(v,n) for n in nvecs) for v in ivecs])) if len(ivecs) and len(nvecs) else 0
    from .acquisition_quality import analyze_video_quality
    quality=analyze_video_quality(path)
    motion=float(feat.get('motion',0)); motion_entropy=float(feat.get('motion_entropy',0))
    dynamic=float(quality['dynamic'])
    # Theme and aesthetics rank footage only after explicit quality gates. Text,
    # static composition, and face dominance are not allowed to hide inside a
    # blended score.
    score=float(.38*pos + .34*dynamic + .18*quality['aesthetic_score'] + .10*quality['temporal_diversity'] - .32*max(0,neg))
    return {
        "score":score,"semantic":pos,"negative":neg,"dynamic":dynamic,
        "motion":motion,"motion_entropy":motion_entropy,"quality":quality,
        "features":feat,
    }


def summarize_library_coverage(library) -> str:
    try:
        stats=library.stats(); rows=library.list_clips(status="ready",limit=200)
        titles=[str(r.get("title") or "") for r in rows if r.get("title")]
        words={}
        for title in titles:
            for w in re.findall(r"[a-z]{4,}",title.lower()):
                if w in {"video","official","music","youtube","shorts","footage"}: continue
                words[w]=words.get(w,0)+1
        common=sorted(words.items(),key=lambda x:(-x[1],x[0]))[:20]
        return f"ready_clips={stats.get('ready',len(rows))}; common title concepts="+", ".join(f"{w}:{n}" for w,n in common)
    except Exception:
        return ""
