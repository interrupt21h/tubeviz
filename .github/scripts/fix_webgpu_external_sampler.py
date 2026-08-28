#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1))


core = ROOT / "src/tubeviz/static/browser_gpu_core.js"
replace_once(
    core,
    "@group(0) @binding(3) var video3: texture_external;\n@group(0) @binding(4) var<uniform> layers: LayerUniforms;",
    "@group(0) @binding(3) var video3: texture_external;\n@group(0) @binding(4) var layerSampler: sampler;\n@group(0) @binding(5) var<uniform> layers: LayerUniforms;",
)
for i in range(4):
    replace_once(
        core,
        f"textureSampleBaseClampToEdge(video{i},layerUv(",
        f"textureSampleBaseClampToEdge(video{i},layerSampler,layerUv(",
    )
replace_once(
    core,
    "{binding:0,resource:external[0]},{binding:1,resource:external[1]},{binding:2,resource:external[2]},{binding:3,resource:external[3]},{binding:4,resource:{buffer:this.layerUniformBuffer}},",
    "{binding:0,resource:external[0]},{binding:1,resource:external[1]},{binding:2,resource:external[2]},{binding:3,resource:external[3]},{binding:4,resource:this.sampler},{binding:5,resource:{buffer:this.layerUniformBuffer}},",
)

version_paths = [
    "pyproject.toml",
    "src/tubeviz/__init__.py",
    "src/tubeviz/native_src/src/main.cpp",
    "src/tubeviz/static/browser_gpu_worker.js",
    "src/tubeviz/static/browser_gpu.js",
    "src/tubeviz/static/index.html",
    "src/tubeviz/static/browser_source.js",
    "src/tubeviz/static/gui.html",
    "src/tubeviz/static/visualizer.js",
    "tests/test_browser_phase2.py",
]
for rel in version_paths:
    path = ROOT / rel
    text = path.read_text()
    if "0.42.1" not in text:
        raise SystemExit(f"expected 0.42.1 marker missing from {rel}")
    path.write_text(text.replace("0.42.1", "0.42.2"))


test_path = ROOT / "tests/test_browser_phase2.py"
tests = test_path.read_text()
needle = "    assert \"angle+=sin(r*34.0*frequency\" in core\n"
addition = """    assert \"@group(0) @binding(4) var layerSampler: sampler;\" in core\n    assert \"@group(0) @binding(5) var<uniform> layers: LayerUniforms;\" in core\n    for i in range(4):\n        assert f\"textureSampleBaseClampToEdge(video{i},layerSampler,layerUv(\" in core\n        assert f\"textureSampleBaseClampToEdge(video{i},layerUv(\" not in core\n    assert \"{binding:4,resource:this.sampler},{binding:5,resource:{buffer:this.layerUniformBuffer}}\" in core\n"""
if addition.strip() not in tests:
    if needle not in tests:
        raise SystemExit("test insertion point not found")
    tests = tests.replace(needle, needle + addition, 1)
    test_path.write_text(tests)

changelog = ROOT / "CHANGELOG.md"
text = changelog.read_text()
entry = """# 0.42.2 — WebGPU external-texture sampling\n\n- Fix the direct WebGPU layer compositor's WGSL external-texture calls to pass the required sampler to `textureSampleBaseClampToEdge`, resolving Chrome's `no matching call` compilation failure for `texture_external`.\n- Align the layer bind-group contract with the shader by binding the shared linear clamp-to-edge sampler at binding 4 and moving the layer uniform buffer to binding 5.\n- Cache-bust the browser preview module graph for 0.42.2 and add regression assertions covering the external-texture sampler signature and bind-group layout.\n\n"""
if not text.startswith("# 0.42.2"):
    changelog.write_text(entry + text)
