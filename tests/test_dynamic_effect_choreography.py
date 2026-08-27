# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tubeviz.ai_music_director import _director_prompt, semantic_direction
from tubeviz.ai_resources import EFFECT_CATALOG, build_resource_manifest
from tubeviz.analysis_presets import ANALYSIS_PRESETS
from tubeviz.creative_effects import apply_temporal_persistence, promote_hero_effects
from tubeviz.library import ClipLibrary, SceneCandidate
from tubeviz.models import CreativeEffectPlan, SceneSelection, Section, SectionAIDirection, TrackAnalysis, VisualDirection
from tubeviz.scene_selector import SceneSelectorConfig, _composition_mode
from tubeviz.transforms import TransformConfig, plan_transform


def _section(index=0, **kw):
    values=dict(index=index,start=index*6.0,end=(index+1)*6.0,energy=.85,label='peak',vibe='driving',brightness=.55,onset_density=.62,local_tempo_bpm=128,bass_weight=.72,percussive_ratio=.7,tonal_stability=.55,noisiness=.3,spectral_contrast=.5)
    values.update(kw); return Section(**values)


def _selection(i=0, section_index=0, motif='m'):
    c=CreativeEffectPlan(temporal_echo=.55,flow_trails=.45,feedback=.35,abstraction=.7)
    return SceneSelection(section_index=section_index,time=i*5.0,term='x',clip_id=i+1,scene_id=i+1,scene_index=0,source_id=f's{i}',media_file=f'originals/{i}.mp4',media_url=f'/originals/{i}.mp4',start=0,end=5,duration=5,motif_id=motif,direction=VisualDirection(effect_family='hyper',creative=c))


def test_presets_separate_density_from_intensity():
    assert ANALYSIS_PRESETS['high-energy']['parameters']['effect_density'] > ANALYSIS_PRESETS['balanced']['parameters']['effect_density'] > ANALYSIS_PRESETS['relaxed']['parameters']['effect_density']
    assert ANALYSIS_PRESETS['experimental']['parameters']['hero_frequency'] > 1.5
    assert ANALYSIS_PRESETS['dreamy']['parameters']['temporal_persistence'] > ANALYSIS_PRESETS['balanced']['parameters']['temporal_persistence']


def test_high_composition_diversity_admits_dynamic_modes():
    modes={_composition_mode('peak',.9,i,3,'heavy',diversity=1.8) for i in range(12)}
    assert modes.intersection({'split','mosaic','swap'})
    default={_composition_mode('peak',.9,i,3,'heavy') for i in range(6)}
    assert default <= {'flow','luma','strips'}


def test_temporal_persistence_is_controlled_and_disableable():
    plan=[_selection(i) for i in range(6)]
    sections={0:_section(0, ai_direction=SectionAIDirection(continuity=.9, temporal_persistence=2.0))}
    disabled=apply_temporal_persistence(plan,sections,persistence=0.0)
    assert all(s.direction.creative.history_inherit == 0 for s in disabled)
    enabled=apply_temporal_persistence(plan,sections,persistence=2.0)
    assert any(s.direction.creative.history_inherit > 0 for s in enabled[1:])


def test_hero_frequency_zero_and_high_frequency():
    sections={0:_section(0)}
    plan=[_selection(i) for i in range(24)]
    none=promote_hero_effects(plan,sections,track_duration=120,frequency=0)
    assert not any(s.direction.creative.hero_kind for s in none)
    high=promote_hero_effects(plan,sections,track_duration=120,frequency=2.0)
    assert sum(bool(s.direction.creative.hero_kind) for s in high) >= 2


def test_effect_density_increases_visible_legacy_punctuation():
    sec=_section()
    values=[]
    for density in (.45, 2.2):
        count=0
        for i in range(40):
            sel=_selection(i)
            sel=sel.model_copy(update={'scene_id':i+1,'source_id':f's{i}','motif_id':str(i)})
            t=plan_transform(sec,sel,TransformConfig(intensity=1.35,density=density))
            count += sum(getattr(t,k)>.08 for k in ('kaleidoscope','mirror_corridor','mask_wipe','solarize','vortex','posterize','edge','slit_scan','datamosh','block_displace'))
        values.append(count)
    assert values[1] > values[0]


def test_ai_director_knows_density_persistence_composition_and_effect_catalog(tmp_path: Path):
    track=TrackAnalysis(source='x.wav',duration=6,sample_rate=22050,hop_length=512,tempo_bpm=128,beats=[],bars=[],events=[],sections=[_section()])
    prompt=_director_prompt(track,{'renderer':{'effect_catalog':EFFECT_CATALOG}})
    for key in ('effect_density','temporal_persistence','composition_diversity','hero_frequency','preferred_effects'):
        assert key in prompt
    assert 'Native render is the reference output' in prompt
    direction=semantic_direction(_section(audio_semantics={'kinetic':.5,'explosive':.3,'bass_heavy':.2}))
    assert direction.effect_density > 1.0


def test_native_webgpu_parity_contract_is_present_in_source():
    manifest=Path('src/tubeviz/native_render.py').read_text()
    header=Path('src/tubeviz/native_src/include/tubeviz/manifest.hpp').read_text()
    effects=Path('src/tubeviz/native_src/src/effects.cpp').read_text()
    for field in ('posterize','solarize','edge','glitch','block_displace','vhs_tracking','slit_scan','datamosh','slice_recursion'):
        assert f'transform.{field}' in manifest
        assert field in header
    assert 'apply_post_transform_effects' in effects
    assert 'compose_layers' in effects
    for mode in ('split','mosaic','swap'):
        assert f'mode=="{mode}"' in effects
