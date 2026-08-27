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
    old = '    assert a.glitch > 0\n'
    new = (
        '    # Destructive accents may be intentionally absent on ordinary '
        'source-first shots.\n'
        '    assert a.vignette > 0\n'
    )
    if old not in text:
        raise RuntimeError('stale transform assertion not found')
    path.write_text(text.replace(old, new, 1))


if __name__ == '__main__':
    apply_embedded_source_patch()
    update_stale_transform_test()
