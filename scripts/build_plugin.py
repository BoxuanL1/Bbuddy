"""Build the reviewed GitHub-distributed plugin from repository sources."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PARENT = ROOT / 'plugins'
PLUGIN = PLUGIN_PARENT / 'bbuddy'
VERSION = '0.2.0'


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    if PLUGIN.resolve() != (ROOT / 'plugins' / 'bbuddy').resolve():
        raise SystemExit('Refusing to build outside the repository plugin directory.')
    if PLUGIN.exists():
        shutil.rmtree(PLUGIN)
    PLUGIN.mkdir(parents=True)

    portable = {
        '$schema': 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
        'name': 'bbuddy', 'version': VERSION,
        'description': 'Create source-backed learning tutorials from authorized Blackboard course materials.',
        'author': {'name': 'BoxuanL1', 'url': 'https://github.com/BoxuanL1'},
        'homepage': 'https://github.com/BoxuanL1/Bbuddy',
        'repository': 'https://github.com/BoxuanL1/Bbuddy',
        'license': 'MIT',
        'keywords': ['blackboard', 'education', 'learning', 'captions'],
    }
    overlay = {
        'name': 'bbuddy', 'version': VERSION,
        'description': portable['description'], 'author': portable['author'],
        'homepage': portable['homepage'], 'repository': portable['repository'],
        'license': 'MIT', 'skills': './skills/',
        'interface': {
            'displayName': 'BBuddy',
            'shortDescription': 'Course week to source-backed tutorial',
            'longDescription': 'Acquire authorized captions and slides locally, then use Codex to create and validate a learning tutorial.',
            'developerName': 'BoxuanL1', 'category': 'Productivity',
            'capabilities': ['Read', 'Write'],
            'defaultPrompt': ['Explain what my selected course covered in a teaching week and create a learning tutorial.'],
        },
    }
    write_json(PLUGIN / 'plugin.json', portable)
    write_json(PLUGIN / '.codex-plugin' / 'plugin.json', overlay)

    shutil.copytree(ROOT / 'skills', PLUGIN / 'skills')
    shutil.copytree(ROOT / 'src' / 'blackboard_companion' / 'schemas', PLUGIN / 'schemas')
    shutil.copytree(ROOT / 'examples' / 'synthetic-week', PLUGIN / 'examples' / 'synthetic-week')
    (PLUGIN / 'docs').mkdir()
    for name in ['browser-session.md', 'online-workflow.md', 'local-testing.md']:
        shutil.copy2(ROOT / 'docs' / name, PLUGIN / 'docs' / name)
    (PLUGIN / 'scripts').mkdir()
    for name in ['setup.ps1', 'invoke-bbuddy.ps1']:
        shutil.copy2(ROOT / 'scripts' / name, PLUGIN / 'scripts' / name)
    for name in ['requirements-runtime.lock', 'LICENSE', 'PRIVACY.md']:
        shutil.copy2(ROOT / name, PLUGIN / name)

    wheels = list((ROOT / 'dist').glob(f'blackboard_lecture_companion-{VERSION}-*.whl'))
    if len(wheels) != 1:
        raise SystemExit(f'Expected one {VERSION} wheel under dist; run python -m build --wheel first.')
    destination = PLUGIN / 'runtime-package' / wheels[0].name
    destination.parent.mkdir()
    shutil.copy2(wheels[0], destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (PLUGIN / 'runtime-package' / 'SHA256SUMS.txt').write_text(f'{digest}  {destination.name}\n', encoding='utf-8')
    print(f'Built {PLUGIN}')


if __name__ == '__main__':
    main()
