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
replace_once(
    "src/tubeviz/gui.py",
    '            _flag(command, "--ai-director-strength", o.get("ai_director_strength", .75))\n',
    '            _flag(command, "--ai-director-strength", o.get("ai_director_strength", .95))\n',
)

cache_test = ROOT / "tests/test_browser_phase2.py"
cache_text = cache_test.read_text()
if "0.42.2" not in cache_text:
    raise SystemExit("tests/test_browser_phase2.py: expected 0.42.2 cache assertions")
cache_test.write_text(cache_text.replace("0.42.2", "0.43.0"))

changelog_path = ROOT / "CHANGELOG.md"
changelog = changelog_path.read_text()
entry = '''# 0.43.0 — AI director authority and visible creative intent\n\n- Promote the whole-song LLM from a mostly invisible scalar bias to a bounded creative director that can author section strategies and 1–4 normalized director beats per section.\n- Director beats can steer a concrete source query, composition, effect vocabulary, temporal-history behavior, clean holds and hero treatments while deterministic beat timing and valid media selection remain authoritative.\n- Preserve explicit LLM creative moments instead of blending them back into CLAP; numeric direction now retains at least 70% of the requested authority when the director is enabled, with a director-led default strength of 0.95.\n- Make broad section composition preferences periodic/soft so a single AI `mosaic` recommendation cannot turn into mosaic wallpaper across an entire section.\n- Record whole-song director provenance on every final shot and show the current AI strategy/moment directly in the browser preview HUD.\n- Report LLM-directed section and authored-moment counts in analyze progress/summary output and invalidate old whole-song director caches with the new schema.\n- Normalize canonical effect names consistently so hyphenated catalog names remain valid in AI-authored plans.\n\n'''
if changelog.startswith("# 0.43.0"):
    raise SystemExit("CHANGELOG already contains the staged 0.43.0 entry")
changelog_path.write_text(entry + changelog)

test_path = ROOT / "tests/test_ai_director_authority.py"
text = test_path.read_text()
addition = '''\n\ndef test_effect_name_normalization_accepts_canonical_hyphenated_names():\n    from tubeviz.ai_resources import normalize_effect_name\n    assert normalize_effect_name("optical-flow warp") == "optical-flow warp"\n    assert normalize_effect_name("optical flow warp") == "optical-flow warp"\n    assert normalize_effect_name("source-preserving color grade") == "source-preserving color grade"\n'''
if "test_effect_name_normalization_accepts_canonical_hyphenated_names" not in text:
    test_path.write_text(text + addition)

print("AI effect normalization, Studio default, cache tests and changelog patch applied")
