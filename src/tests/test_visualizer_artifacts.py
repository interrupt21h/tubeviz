from pathlib import Path


def test_motif_overlay_is_transient_and_masked():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "visualStrength" in js
    assert "m.visualStrength=(m.visualStrength??0)*.94" in js
    assert "ctx.clip()" in js

    # Regression: this exact full-frame -> square motif thumbnail was persistent
    # because motifObjects are long-lived world memory.
    bad = (
        "ctx.drawImage(videoFx,0,0,width,height,"
        "x-size/2,y-size/2,size,size)"
    )
    assert bad not in js
