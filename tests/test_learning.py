import copy
import json
from pathlib import Path

import pytest

from blackboard_companion.pipeline.learning import (
    LearningError, start, normalize, render, validate, read_json, load_units, inspect,
)
from blackboard_companion.storage import write_json


@pytest.fixture
def course(tmp_path):
    root = tmp_path / '课程 with spaces'
    root.mkdir()
    for name, text in [('first/lecture', 'Gradient descent uses the negative gradient direction.'),
                       ('second/lecture', 'Newton uses curvature and requires solving a linear system.')]:
        p = root / (name + '.vtt')
        p.parent.mkdir()
        p.write_text('WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n' + text, encoding='utf-8')
    (root / 'first/lecture.srt').write_text('1\n00:00:01,000 --> 00:00:04,000\nDuplicate representation.', encoding='utf-8')
    (root / 'outline.md').write_text('Week 3: gradient descent and Newton.\n\nPrerequisite: derivatives.', encoding='utf-8')
    write_json(root / 'scope.json', {'schema_version': '1.0', 'course': 'TEST101', 'scope': 'Week 3',
        'basis': 'Synthetic test fixture schedule', 'verified': True, 'missing': [],
        'recordings': {name + '/lecture.vtt': {'verified': True, 'basis': 'Synthetic recording', 'language': 'English'}
                       for name in ['first', 'second']}, 'roles': {'outline.md': 'outline'}})
    req = tmp_path / 'request.json'
    write_json(req, {'schema_version': '1.0', 'course': 'TEST101', 'scope': 'Week 3', 'input_dir': str(root)})
    run = tmp_path / 'run'
    start(req, run)
    return root, run


def analysis(run):
    m = read_json(run / 'manifest.json')
    units = load_units(run, m)
    claims = [{'id': f'claim{i}', 'category': 'B', 'text': u['text'], 'unit_ids': [u['id']]}
              for i, u in enumerate(units.values()) if u['type'] == 'cue']
    value = {'schema_version': '1.0', 'input_fingerprint': m['input_fingerprint'],
             'title': 'Optimization learning tutorial', 'claims': claims,
             'reviewed_chunks': [c['id'] for c in m['chunks']],
             'sections': [{'heading': 'Concepts', 'claim_ids': [c['id'] for c in claims]}],
             'review': {'teacher_attribution': True, 'scope_coverage': True, 'visual_units': [],
                        'notes': 'Reviewed synthetic source claims and full fixture scope.'}}
    return value


def submit(run, value):
    path = run / 'draft.json'
    write_json(path, value)
    return render(run, path)


def test_multi_recording_and_cache(course):
    root, run = course
    m = read_json(run / 'manifest.json')
    captions = [s for s in m['sources'] if s['kind'] == 'captions']
    assert len(captions) == 2
    assert len({s['recording_id'] for s in captions}) == 2
    units = load_units(run, m)
    assert len(units) == 4
    assert normalize(run)['cache_reused']
    assert not (run / 'companion.md').exists()
    assert submit(run, analysis(run))['status'] == 'completed'
    assert validate(run)['valid']


@pytest.mark.parametrize('mutate', [
    lambda a: a['claims'][0]['unit_ids'].append('s-unknown:c000001'),
    lambda a: a['claims'][0].update(category='A'),
    lambda a: a['reviewed_chunks'].pop(),
    lambda a: a.update(input_fingerprint='stale'),
    lambda a: a['review'].update(teacher_attribution=False),
    lambda a: a['claims'].append(copy.deepcopy(a['claims'][0])),
    lambda a: a['sections'][0]['claim_ids'].append('invented'),
])
def test_reject_bad_evidence(course, mutate):
    _, run = course
    value = analysis(run)
    mutate(value)
    assert submit(run, value)['status'] == 'needs_revision'
    assert not (run / 'companion.md').exists()


def test_stale_sources_and_preserve_user_tutorial(course):
    root, run = course
    value = analysis(run)
    submit(run, value)
    output = run / 'companion.md'
    output.write_text('My personal edited notes.', encoding='utf-8')
    assert not validate(run)['valid']
    assert inspect(run)['status'] == 'needs_revision'
    result = submit(run, value)
    assert Path(result['artifacts'][0]).name != 'companion.md'
    assert output.read_text() == 'My personal edited notes.'
    assert validate(run)['valid']
    (root / 'first/lecture.vtt').write_text('WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nChanged lecture content.', encoding='utf-8')
    assert normalize(run)['status'] == 'awaiting_analysis'
    assert submit(run, value)['status'] == 'needs_revision'


def test_tampered_pack_is_rebuilt(course):
    _, run = course
    m = read_json(run / 'manifest.json')
    (run / m['sources'][0]['units_path']).write_text('corrupt', encoding='utf-8')
    assert inspect(run)['status'] == 'needs_normalization'
    assert normalize(run)['status'] == 'awaiting_analysis'
    assert submit(run, analysis(run))['status'] == 'completed'


def test_partial_and_scope_mismatch(course):
    root, run = course
    scope = read_json(root / 'scope.json')
    scope['missing'] = ['Second slide deck unavailable.']
    write_json(root / 'scope.json', scope)
    normalize(run)
    assert submit(run, analysis(run))['status'] == 'partial'
    assert 'Second slide deck unavailable.' in (run / 'companion.md').read_text(encoding='utf-8')
    scope['course'] = 'WRONG101'
    write_json(root / 'scope.json', scope)
    with pytest.raises(LearningError):
        normalize(run)


def test_online_handoff_and_wrong_request(tmp_path, course):
    request = tmp_path / 'online.json'
    write_json(request, {'schema_version': '1.0', 'course': 'TEST101', 'scope': 'Week 3'})
    assert start(request, tmp_path / 'online')['status'] == 'needs_acquisition'
    _, run = course
    with pytest.raises(LearningError):
        start(request, run)


def test_reject_ai_only_and_omitted_recording(course):
    _, run = course
    value = analysis(run)
    for claim in value['claims']:
        claim['category'] = 'E'
    assert submit(run, value)['status'] == 'needs_revision'
    value = analysis(run)
    value['claims'] = value['claims'][:1]
    value['sections'][0]['claim_ids'] = [value['claims'][0]['id']]
    assert submit(run, value)['status'] == 'needs_revision'


def test_pdf_page_and_low_text_review(course):
    from pypdf import PdfWriter
    root, run = course
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with (root / 'slides.pdf').open('wb') as f:
        writer.write(f)
    normalize(run)
    value = analysis(run)
    assert submit(run, value)['status'] == 'needs_revision'
    m = read_json(run / 'manifest.json')
    units = load_units(run, m)
    page = next(u['id'] for u in units.values() if u['type'] == 'page')
    value['review']['visual_units'] = [page]
    value['claims'].append({'id': 'page', 'category': 'A', 'text': 'This synthetic page is intentionally blank.', 'unit_ids': [page]})
    value['sections'][0]['claim_ids'].append('page')
    assert submit(run, value)['status'] == 'partial'
    value['claims'][-1]['unit_ids'] = [page + '999']
    assert submit(run, value)['status'] == 'needs_revision'
