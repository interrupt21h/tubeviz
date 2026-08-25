# SPDX-License-Identifier: Apache-2.0
from tubeviz.choreography import (
    ChoreographyConfig, attach_choreography, effect_compatibility_score,
    shot_trajectory, trajectory_scene_score,
)
from tubeviz.library import SceneCandidate
from tubeviz.models import Section, SectionAIDirection, TrackAnalysis


def track():
    sections = [
        Section(index=0,start=0,end=8,energy=.25,label="drive",onset_density=.18,percussive_ratio=.35,bass_weight=.25,vibe="groove"),
        Section(index=1,start=8,end=16,energy=.45,label="build",onset_density=.36,percussive_ratio=.50,bass_weight=.38,vibe="driving"),
        Section(index=2,start=16,end=24,energy=.66,label="build",onset_density=.56,percussive_ratio=.68,bass_weight=.52,vibe="driving", ai_direction=SectionAIDirection(edit_density=.55, desired_motion=.6, desired_complexity=.55, continuity=.5)),
        Section(index=3,start=24,end=32,energy=.92,label="peak",onset_density=.72,percussive_ratio=.84,bass_weight=.72,vibe="euphoric"),
        Section(index=4,start=32,end=40,energy=.28,label="breakdown",onset_density=.16,percussive_ratio=.28,bass_weight=.22,vibe="ambient"),
    ]
    return TrackAnalysis(source="song.wav",duration=40,sample_rate=22050,hop_length=512,tempo_bpm=128,beats=[],bars=[],sections=sections,events=[])


def candidate(scene_id, motion, complexity, entropy=.5, cut_rate=.15):
    return SceneCandidate(scene_id=scene_id,clip_id=scene_id,scene_index=0,start_time=0,end_time=8,duration=8,
        thumbnail_path=None,source_id=str(scene_id),title="x",description=None,channel=None,
        normalized_path=f"normalized/{scene_id}.mp4",term="x",term_rank=1,
        visual_features={"motion":motion,"complexity":complexity,"visual_entropy":entropy,
                         "brightness":.55,"saturation":.65,"cut_rate":cut_rate})


def test_build_trajectory_anticipates_peak_and_release_falls_after():
    directed = attach_choreography(track())
    build = directed.sections[2].trajectory
    peak = directed.sections[3].trajectory
    release = directed.sections[4].trajectory
    assert build is not None and peak is not None and release is not None
    assert build.build_probability > .5
    assert build.anticipation > 0
    assert peak.drop_probability > .55
    assert release.release_probability > .45
    assert len(directed.visual_arc) == len(directed.sections)


def test_build_progress_increases_motion_and_contrast_then_withholds_at_end():
    section = attach_choreography(track()).sections[2]
    early = shot_trajectory(section, .15)
    late = shot_trajectory(section, .72)
    end = shot_trajectory(section, .98)
    assert late["motion"] >= early["motion"]
    assert late["contrast"] >= early["contrast"]
    assert end["withhold"] >= late["withhold"]


def test_trajectory_scene_score_prefers_motion_matching_build_target():
    section = attach_choreography(track()).sections[2]
    target = shot_trajectory(section, .70)
    matching = candidate(1, target["motion"], target["complexity"])
    mismatch = candidate(2, 0.02, 0.02)
    assert trajectory_scene_score(matching, section, .70) > trajectory_scene_score(mismatch, section, .70)


def test_effect_compatibility_avoids_overloaded_hyper_footage():
    section = Section(index=0,start=0,end=8,energy=.85,label="peak",vibe="driving",
        ai_direction=SectionAIDirection(effect_family="hyper"))
    useful = candidate(1,.72,.55,.55,.12)
    overloaded = candidate(2,1.0,1.0,1.0,1.0)
    assert effect_compatibility_score(useful, section) > effect_compatibility_score(overloaded, section)


def test_trajectory_blends_ai_direction_without_replacing_visual_world():
    t=track()
    before=t.sections[2].ai_direction
    directed=attach_choreography(t, ChoreographyConfig(trajectory_strength=1.0))
    after=directed.sections[2].ai_direction
    assert before is not None and after is not None
    assert after.edit_density >= before.edit_density
    assert "trajectory=" in after.notes


def test_manual_rejection_preference_score_penalizes_similar_visuals():
    from tubeviz.scene_selector import _preference_score
    profile={
        "keys":["motion","complexity","brightness","saturation","visual_entropy","cut_rate"],
        "rejected_centroid":[.1,.1,.5,.3,.2,.05],
        "rejected_scale":[.1,.1,.1,.1,.1,.1],
        "ready_centroid":[.6,.6,.5,.6,.6,.2],
    }
    similar=candidate(10,.1,.1,.2,.05)
    similar.visual_features.update(brightness=.5,saturation=.3)
    different=candidate(11,.7,.7,.7,.2)
    different.visual_features.update(brightness=.55,saturation=.7)
    assert _preference_score(different,profile) > _preference_score(similar,profile)
