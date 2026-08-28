#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {text.count(old)}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "src/tubeviz/ai_resources.py",
    '    raw = str(value or "").strip().lower().replace("_", " ").replace("-", " ")\n',
    '    raw = " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())\n',
)
replace_once(
    "src/tubeviz/ai_resources.py",
    '    for name in RASTER_EFFECTS:\n        if name.lower() == raw:\n            return name\n    return None\n',
    '    by_key = {\n        " ".join(name.strip().lower().replace("_", " ").replace("-", " ").split()): name\n        for name in RASTER_EFFECTS\n    }\n    return by_key.get(raw)\n',
)

test_path = ROOT / "tests/test_ai_director_authority.py"
text = test_path.read_text()
addition = '''\n\ndef test_effect_name_normalization_accepts_canonical_hyphenated_names():\n    from tubeviz.ai_resources import normalize_effect_name\n    assert normalize_effect_name("optical-flow warp") == "optical-flow warp"\n    assert normalize_effect_name("optical flow warp") == "optical-flow warp"\n    assert normalize_effect_name("source-preserving color grade") == "source-preserving color grade"\n'''
if "test_effect_name_normalization_accepts_canonical_hyphenated_names" not in text:
    test_path.write_text(text + addition)

print("AI effect normalization patch applied")
