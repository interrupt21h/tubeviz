from tubeviz.acquisition import AcquisitionConfig, plan_acquisition, summarize_library_coverage
from tubeviz.library import ClipLibrary


def test_heuristic_acquisition_plan_has_visual_gates(tmp_path):
    plan=plan_acquisition(AcquisitionConfig(visual_brief="dark futuristic techno",query_count=6))
    assert len(plan.queries)==6
    assert any("dynamic" in x.lower() or "motion" in x.lower() for x in plan.queries)
    assert any("talking" in x.lower() for x in plan.negative_concepts)
    assert plan.roles


def test_library_coverage_summary_empty_library(tmp_path):
    lib=ClipLibrary(tmp_path/'lib'); lib.initialize()
    text=summarize_library_coverage(lib)
    assert "ready_clips=" in text


def test_visual_brief_never_becomes_youtube_paragraph_query():
    brief=("Emotional, euphoric late-night electronic energy. Intimate human moments evolving "
           "into communal release: rainy city streets, trains and tunnels, blurred lights, "
           "reflections, handheld nightlife, underground clubs, dancing silhouettes. "
           "Avoid text, logos, talking heads, tutorials, static shots.")
    plan=plan_acquisition(AcquisitionConfig(visual_brief=brief,query_count=24), progress=lambda _: None)
    assert len(plan.queries) == 24
    assert all(len(q) <= 96 for q in plan.queries)
    assert all(len(q.split()) <= 10 for q in plan.queries)
    assert all("Avoid" not in q and "talking heads" not in q.lower() for q in plan.queries)
    assert all(not q.startswith("Emotional, euphoric late-night electronic energy") for q in plan.queries)


def test_llm_shortfall_is_filled_and_queries_are_sanitized(monkeypatch):
    import json
    import tubeviz.acquisition as acquisition
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def read(self):
            return json.dumps({"choices":[{"message":{"content":json.dumps({
                "queries":["rainy city cinematic no text"],"roles":[],
                "positive_concepts":["rainy city"],"negative_concepts":["logo"]})}}]}).encode()
    monkeypatch.setattr(acquisition.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    plan=plan_acquisition(AcquisitionConfig(visual_brief="rainy city nightlife",query_count=6,llm_base_url="http://x/v1",llm_model="m"), progress=lambda _: None)
    assert len(plan.queries) == 6
    assert all("no text" not in q.lower() for q in plan.queries)

def test_quality_gate_rejects_persistent_text_and_static(tmp_path):
    import cv2, numpy as np
    from tubeviz.acquisition_quality import analyze_video_quality, quality_failures
    p=tmp_path/'text.mp4'
    out=cv2.VideoWriter(str(p),cv2.VideoWriter_fourcc(*'mp4v'),12,(320,180))
    for i in range(36):
        frame=np.full((180,320,3),28,dtype=np.uint8)
        cv2.putText(frame,'BIG TITLE',(35,92),cv2.FONT_HERSHEY_SIMPLEX,1.25,(255,255,255),3,cv2.LINE_AA)
        out.write(frame)
    out.release()
    q=analyze_video_quality(p,max_frames=24)
    failures=quality_failures(q,min_motion_coverage=.20)
    assert failures
    assert q['motion_coverage'] < .20 or q['persistent_text_fraction'] > .01 or q['text_overlay_fraction'] > .05


def test_quality_gate_accepts_broad_motion(tmp_path):
    import cv2, numpy as np
    from tubeviz.acquisition_quality import analyze_video_quality
    p=tmp_path/'motion.mp4'
    out=cv2.VideoWriter(str(p),cv2.VideoWriter_fourcc(*'mp4v'),12,(320,180))
    rng=np.random.default_rng(3)
    base=rng.integers(0,256,(180,420,3),dtype=np.uint8)
    for i in range(36):
        x=(i*3)%90; out.write(base[:,x:x+320])
    out.release()
    q=analyze_video_quality(p,max_frames=24)
    assert q['motion_coverage'] > .20
    assert q['temporal_diversity'] > .12
