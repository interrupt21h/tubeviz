#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).with_name("apply_ai_director_authority.py")
text = path.read_text()
old = '''regex_once(
    "src/tubeviz/gui.py",
    r'(["\\']ai_director_strength["\\']\\s*:\\s*)0\\.75',
    r'\\g<1>0.95',
)
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one obsolete gui.py harness edit, found {text.count(old)}")
text = text.replace(old, "", 1)
start_marker = 'changelog = read("CHANGELOG.md")\n'
end_marker = '# ---------------------------------------------------------------------------\n# Regression coverage.\n'
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("expected obsolete CHANGELOG staging block was not found")
text = text[:start] + text[end:]
path.write_text(text)
print("AI director patch harness adjusted for current GUI and changelog layout")
