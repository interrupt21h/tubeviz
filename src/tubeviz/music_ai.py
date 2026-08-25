# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

import librosa
import numpy as np

from .models import Section, TrackAnalysis
from .torch_device import resolve_torch_device


@dataclass(frozen=True)
class MusicAIConfig:
    model: str = "m-a-p/MERT-v1-95M"
    device: str = "auto"
    window_seconds: float = 8.0
    hop_seconds: float = 4.0
    batch_size: int = 4
    layer: int = -1
    cache_dir: str | None = None
    force: bool = False


def _cache_root(cfg: MusicAIConfig) -> Path:
    if cfg.cache_dir:
        return Path(cfg.cache_dir).expanduser().resolve()
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home()/".cache"))
    return root / "tubeviz" / "music-ai"


def _cache_key(audio: Path, cfg: MusicAIConfig) -> str:
    stat = audio.stat()
    payload = {"path":str(audio.resolve()),"size":stat.st_size,"mtime":stat.st_mtime_ns,
               "model":cfg.model,"window":cfg.window_seconds,"hop":cfg.hop_seconds,"layer":cfg.layer}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def _normalize_rows(values: np.ndarray) -> np.ndarray:
    arr=np.asarray(values,dtype=np.float32)
    norm=np.linalg.norm(arr,axis=1,keepdims=True)
    return arr/np.maximum(norm,1e-12)


class MertMusicAnalyzer:
    def __init__(self, config: MusicAIConfig | None = None):
        self.config=config or MusicAIConfig()
        try:
            import torch
            from transformers import AutoModel, Wav2Vec2FeatureExtractor
        except ImportError as exc:
            raise RuntimeError("MERT music AI requires torch and transformers; install tubeviz[audio-ai]") from exc
        self.torch=torch
        self.device,self.device_warning=resolve_torch_device(torch,self.config.device)
        self.processor=Wav2Vec2FeatureExtractor.from_pretrained(self.config.model,trust_remote_code=True)
        # MERT's current model card uses trust_remote_code=True. Keep this path
        # opt-in because loading repository code has different trust semantics
        # from CLAP's built-in Transformers implementation.
        self.model=AutoModel.from_pretrained(self.config.model,trust_remote_code=True).to(self.device)
        self.model.eval()
        self.sample_rate=int(getattr(self.processor,"sampling_rate",24000))

    def encode(self, audio_windows: list[np.ndarray]) -> np.ndarray:
        if not audio_windows:
            return np.empty((0,0),dtype=np.float32)
        rows=[]
        bs=max(1,self.config.batch_size)
        for i in range(0,len(audio_windows),bs):
            chunk=audio_windows[i:i+bs]
            inputs=self.processor(chunk,sampling_rate=self.sample_rate,padding=True,return_tensors="pt")
            inputs={k:v.to(self.device) if hasattr(v,"to") else v for k,v in inputs.items()}
            with self.torch.inference_mode():
                output=self.model(**inputs,output_hidden_states=True,return_dict=True)
            hidden_states=getattr(output,"hidden_states",None)
            if hidden_states:
                layer=self.config.layer
                hidden=hidden_states[layer]
            else:
                hidden=output.last_hidden_state
            pooled=hidden.float().mean(dim=1).cpu().numpy()
            rows.append(pooled)
        return _normalize_rows(np.concatenate(rows,axis=0))


def analyze_music_embeddings(audio: str | Path, config: MusicAIConfig | None = None, progress=print) -> tuple[list[tuple[float,float]],np.ndarray,str,str|None]:
    cfg=config or MusicAIConfig(); path=Path(audio).expanduser().resolve()
    root=_cache_root(cfg); root.mkdir(parents=True,exist_ok=True); cache=root/f"{_cache_key(path,cfg)}.npz"
    if cache.is_file() and not cfg.force:
        data=np.load(cache,allow_pickle=False)
        spans=[(float(a),float(b)) for a,b in data["spans"]]
        return spans,np.asarray(data["embeddings"]),str(data["resolved_device"]),str(data["warning"]) or None
    analyzer=MertMusicAnalyzer(cfg)
    progress(f"Music AI: loading {path.name} at {analyzer.sample_rate} Hz with {cfg.model} on {analyzer.device}")
    y,sr=librosa.load(path,sr=analyzer.sample_rate,mono=True)
    duration=len(y)/sr
    window=max(.5,cfg.window_seconds); hop=max(.25,cfg.hop_seconds)
    spans=[]; chunks=[]; start=0.0
    while start<duration:
        end=min(duration,start+window)
        a,b=int(round(start*sr)),int(round(end*sr))
        clip=y[a:b]
        if clip.size:
            spans.append((start,end)); chunks.append(clip.astype(np.float32,copy=False))
        if end>=duration: break
        start+=hop
    embeddings=analyzer.encode(chunks)
    tmp=cache.with_suffix('.tmp.npz')
    np.savez_compressed(tmp,spans=np.asarray(spans,dtype=np.float32),embeddings=embeddings,
                        resolved_device=np.asarray(analyzer.device),warning=np.asarray(analyzer.device_warning or ""))
    tmp.replace(cache)
    return spans,embeddings,analyzer.device,analyzer.device_warning


def attach_music_embeddings(track: TrackAnalysis, audio: str | Path, config: MusicAIConfig | None = None, progress=print) -> TrackAnalysis:
    cfg=config or MusicAIConfig()
    spans,embeddings,device,warning=analyze_music_embeddings(audio,cfg,progress)
    if len(spans)==0 or embeddings.size==0:
        return track.model_copy(update={"music_ai_model":cfg.model,"music_ai_device":device})
    section_vectors=[]
    for section in track.sections:
        idx=[i for i,(a,b) in enumerate(spans) if min(section.end,b)-max(section.start,a)>0]
        if not idx:
            section_vectors.append(None); continue
        v=np.mean(embeddings[idx],axis=0); v=v/max(1e-12,float(np.linalg.norm(v))); section_vectors.append(v)
    updated=[]
    for i,section in enumerate(track.sections):
        cur=section_vectors[i]
        if cur is None:
            updated.append(section); continue
        prev=section_vectors[i-1] if i else cur
        nxt=section_vectors[i+1] if i+1<len(section_vectors) else cur
        novelty=0.0 if prev is None else float(np.clip(1.0-np.dot(cur,prev),0,1))
        future=0.0 if nxt is None else float(np.clip(1.0-np.dot(cur,nxt),0,1))
        velocity=float(np.clip(.58*novelty+.42*future,0,1))
        updated.append(section.model_copy(update={"music_embedding_novelty":novelty,"music_embedding_velocity":velocity}))
    return track.model_copy(update={"sections":updated,"music_ai_model":cfg.model,"music_ai_device":device,"music_ai_warning":warning})


def music_ai_doctor(model: str="m-a-p/MERT-v1-95M",device: str="auto") -> dict[str,object]:
    result={"model":model,"requested_device":device,"trust_remote_code":True}
    try:
        import torch, transformers
        resolved,warning=resolve_torch_device(torch,device)
        result.update(available=True,torch=torch.__version__,transformers=transformers.__version__,resolved_device=resolved)
        if warning: result["device_warning"]=warning
    except Exception as exc:
        result.update(available=False,error=str(exc))
    return result
