import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_marketplace_points_to_plugin():
    marketplace = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text(encoding='utf-8'))
    assert marketplace['name'] == 'bbuddy'
    assert marketplace['plugins'][0]['name'] == 'bbuddy'
    assert marketplace['plugins'][0]['source'] == {'source': 'local', 'path': './plugins/bbuddy'}


def test_plugin_manifests_are_consistent():
    portable = json.loads((ROOT / 'plugins/bbuddy/plugin.json').read_text(encoding='utf-8'))
    overlay = json.loads((ROOT / 'plugins/bbuddy/.codex-plugin/plugin.json').read_text(encoding='utf-8'))
    assert portable['name'] == overlay['name'] == 'bbuddy'
    assert portable['version'] == overlay['version'] == '0.2.0'
    assert portable['license'] == overlay['license'] == 'MIT'


def test_plugin_skill_links_stay_in_package():
    import re
    plugin = ROOT / 'plugins/bbuddy'
    for document in (plugin / 'skills').rglob('*.md'):
        for raw in re.findall(r'\[[^\]]*\]\(([^)]+)\)', document.read_text(encoding='utf-8')):
            target = raw.split('#', 1)[0]
            if not target or '://' in target:
                continue
            resolved = (document.parent / target).resolve()
            assert resolved.is_relative_to(plugin.resolve())
            assert resolved.exists(), f'{document}: {target}'
