from pathlib import Path

def test_kaleidoscope_uses_drifting_focal_point():
    js = Path("src/tubeviz/static/visualizer.js").read_text()
    start = js.index("function applyKaleidoscope")
    end = js.index("function applyTunnel", start)
    body = js[start:end]

    assert "const baseX=width*(.50+.16*Math.sin" in body
    assert "const baseY=height*(.50+.13*Math.cos" in body
    assert "fx.ellipse(" in body
    assert "cx=width/2,cy=height/2" not in body
