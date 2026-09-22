"""Verify bundled Markdown references remain inside the plugin and exist."""
import re
import sys
from pathlib import Path


def check(root):
    errors = []
    for doc in (root / 'skills').rglob('*.md'):
        for raw in re.findall(r'\[[^\]]*\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
            target = raw.split('#', 1)[0]
            if not target or '://' in target:
                continue
            path = (doc.parent / target).resolve()
            if not path.is_relative_to(root.resolve()) or not path.exists():
                errors.append(f'{doc.relative_to(root)}: {target}')
    return errors


if __name__ == '__main__':
    problems = check(Path(sys.argv[1]))
    print('\n'.join(problems) if problems else 'All bundled Skill links resolve within the plugin.')
    raise SystemExit(bool(problems))
