# SPDX-License-Identifier: Apache-2.0
import numpy as np

import tubeviz.music_ai as music_ai
from tubeviz.models import Section, TrackAnalysis


def _track():
    return TrackAnalysis(source="song.wav",duration=24,sample_rate=22050,hop_length=512,tempo_bpm=120,
        beats=[],bars=[],events=[],sections=[
            Section(index=0,start=0,end=8,energy=.3,label="drive"),
            Section(index=1,start=8,end=16,energy=.5,label="build"),
            Section(index=2,start=16,end=24,energy=.8,label="peak"),
        ])


def test_attach_music_embeddings_derives_section_novelty(monkeypatch):
    spans=[(0,8),(8,16),(16,24)]
    emb=np.asarray([[1,0,0],[.98,.2,0],[0,0,1]],dtype=np.float32)
    emb=emb/np.linalg.norm(emb,axis=1,keepdims=True)
    monkeypatch.setattr(music_ai,"analyze_music_embeddings",lambda *a,**k:(spans,emb,"cpu",None))
    out=music_ai.attach_music_embeddings(_track(),"song.wav")
    assert out.music_ai_model == "m-a-p/MERT-v1-95M"
    assert out.sections[2].music_embedding_novelty > out.sections[1].music_embedding_novelty
    assert out.sections[1].music_embedding_velocity > 0
