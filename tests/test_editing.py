# SPDX-License-Identifier: Apache-2.0
from tubeviz.editing import EditConfig, attach_edit_plan
from tubeviz.models import DirectedTimeline, EventType, MusicalEvent, SceneSelection, Section, TrackAnalysis


def test_video_edit_cues_are_generated_from_music_events():
    section = Section(index=0,start=0,end=8,energy=.9,label="peak",key="F minor",brightness=.7,onset_density=2.0)
    events = [
        MusicalEvent(time=.5,type=EventType.BEAT,strength=.9),
        MusicalEvent(time=1.0,type=EventType.BEAT,strength=.9),
        MusicalEvent(time=2.0,type=EventType.BAR,strength=.8),
        MusicalEvent(time=2.5,type=EventType.ONSET,strength=.9),
        MusicalEvent(time=3.0,type=EventType.HARMONIC_CHANGE,strength=.9),
        MusicalEvent(time=4.0,type=EventType.DROP_CANDIDATE,strength=.9),
    ]
    track=TrackAnalysis(source="x",duration=8,sample_rate=22050,hop_length=512,tempo_bpm=120,beats=[],bars=[],sections=[section],events=events)
    scene=SceneSelection(section_index=0,time=0,term="x",clip_id=1,scene_id=1,scene_index=0,source_id="x",media_file="x.mp4",media_url="/media/x.mp4",start=0,end=8,duration=8)
    out=attach_edit_plan(DirectedTimeline(track=track,cues=[],scene_plan=[scene]), EditConfig(intensity=1.0, density=.35))
    actions={c.action for c in out.cues}
    assert "video_edit_punch" in actions
    assert "video_edit_jump" in actions
    assert "video_edit_slice" not in actions
    assert "video_edit_kaleidoscope" not in actions
    assert "video_edit_datamosh" not in actions
    assert "video_edit_slitscan" not in actions
    assert "video_edit_strobe" not in actions



def test_destructive_edit_cues_require_experimental_density():
    section = Section(index=0,start=0,end=20,energy=.95,label="peak",vibe="fractured",key=None,brightness=.5,onset_density=2.0,percussive_ratio=.9,tonal_stability=.9)
    events=[]
    for i in range(48):
        events.append(MusicalEvent(time=.2+i*.36,type=EventType.BEAT,strength=.97,payload={"accent":.97,"high":.88,"low":.04,"mid":.08,"local_bpm":166}))
    for i in range(10):
        events.append(MusicalEvent(time=.8+i*1.8,type=EventType.BAR,strength=.95))
    track=TrackAnalysis(source="x",duration=20,sample_rate=22050,hop_length=512,tempo_bpm=166,beats=[],bars=[],sections=[section],events=events)
    scene=SceneSelection(section_index=0,time=0,term="x",clip_id=1,scene_id=1,scene_index=0,source_id="x",media_file="x.mp4",media_url="/media/x.mp4",start=0,end=20,duration=20)
    clean=attach_edit_plan(DirectedTimeline(track=track,cues=[],scene_plan=[scene]), EditConfig(intensity=1.2,density=.35))
    experimental=attach_edit_plan(DirectedTimeline(track=track,cues=[],scene_plan=[scene]), EditConfig(intensity=1.2,density=1.8))
    destructive={"video_edit_kaleidoscope","video_edit_datamosh","video_edit_slitscan","video_edit_edge","video_edit_chroma_delay","video_edit_slice_recursion","video_edit_strobe"}
    assert not destructive.intersection({cue.action for cue in clean.cues})
    assert destructive.intersection({cue.action for cue in experimental.cues})

def test_edit_plan_does_nothing_without_video_scene_plan():
    section = Section(index=0,start=0,end=8,energy=.9,label="peak",key=None,brightness=.7,onset_density=2.0)
    track=TrackAnalysis(source="x",duration=8,sample_rate=22050,hop_length=512,tempo_bpm=120,beats=[],bars=[],sections=[section],events=[])
    timeline=DirectedTimeline(track=track,cues=[])
    assert attach_edit_plan(timeline).cues == []
