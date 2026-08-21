from pathlib import Path


def test_browser_vectors_use_connected_contours_and_local_flow():
    source = Path("src/tubeviz/static/visualizer.js").read_text()
    assert "orderedComponentPaths" in source
    assert "rdp(points,epsilon)" in source
    assert "chaikin(points,iterations=1)" in source
    assert "stabilizeContourPaths" in source
    assert "updateOpticalFlow" in source
    assert "sampleFlow" in source
    assert "local_optical_flow" not in source  # timeline term belongs to Python director
    assert "tangent=p.angle" not in source


def test_director_limits_visible_vector_stacking():
    source = Path("src/tubeviz/visual_director.py").read_text()
    assert "visible_budget" in source
    assert "clean_shot" in source
    assert "visible + hidden" in source
    assert '"local_optical_flow"' in source
    assert '"connected_video_contours"' in source


def test_native_contours_are_component_paths_not_tangent_hairs():
    source = Path("native/src/effects.cpp").read_text()
    assert "struct Component" in source
    assert "components.push_back" in source
    assert "std::vector<std::pair<int,int>> path" in source
    assert "const double angle=std::atan2(gy,gx)+1.57079632679" not in source
