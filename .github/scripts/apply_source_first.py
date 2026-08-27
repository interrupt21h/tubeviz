from __future__ import annotations

from pathlib import Path
import textwrap


def apply_embedded_source_patch() -> None:
    workflow_path = Path('.github/workflows/source-first-effects.yml')
    lines = workflow_path.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "python - <<'PY'") + 1
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == 'PY')
    script = textwrap.dedent('\n'.join(lines[start:end]))
    exec(compile(script, 'source-first-effects-embedded.py', 'exec'), {})


def update_stale_transform_test() -> None:
    path = Path('tests/test_transforms.py')
    text = path.read_text()
    old = (
        '    assert a.glitch > 0\n'
        '    assert a.ripple > 0\n'
        '    assert a.posterize > 0\n'
        '    assert a.edge > 0\n'
        '    assert a.strobe > 0\n'
        '    assert a.shutter > 0\n'
    )
    new = (
        '    # Source-first scheduling keeps subtle motion available while destructive\n'
        '    # accents are deliberately absent on many ordinary shots.\n'
        '    assert a.vignette > 0\n'
        '    assert 0.0 <= a.ripple <= 1.0\n'
        '    destructive = (a.glitch, a.posterize, a.edge, a.strobe, a.shutter)\n'
        '    assert not all(value > 0.0 for value in destructive)\n'
    )
    if old not in text:
        raise RuntimeError('stale destructive-effect assertion block not found')
    path.write_text(text.replace(old, new, 1))


if __name__ == '__main__':
    apply_embedded_source_patch()
    update_stale_transform_test()
