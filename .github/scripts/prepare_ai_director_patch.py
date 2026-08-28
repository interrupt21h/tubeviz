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
path.write_text(text.replace(old, "", 1))
print("AI director patch harness adjusted for current GUI command builder")
