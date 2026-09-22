"""Versioned source packs and checked host-agent authored tutorials.

No model call occurs here. The host reads the pack and submits analysis.json.
Source existence checks are deterministic; semantic review remains an agent task.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from ..captions import load_captions
from ..documents import extract_document
from ..storage import atomic_bytes, write_json

VERSION = '1.0'
NORMALIZER = '0.2.0'
KINDS = {'.vtt': 'captions', '.srt': 'captions', '.pdf': 'document',
         '.pptx': 'document', '.md': 'text', '.txt': 'text'}


class LearningError(ValueError):
    """User-safe contract error, never containing source text or signed URLs."""


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def check_schema(value, name):
    schema = read_json(Path(__file__).parents[1] / 'schemas' / f'{name}.schema.json')
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        # Do not print schema error messages, which can include source content.
        raise LearningError(f'{name}: {len(errors)} schema error(s); check required fields and types.')


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise LearningError('Artifact path must remain inside its run directory.')
    return path


def state(run: Path, stage: str, status: str, **extra):
    value = {'schema_version': VERSION, 'run_id': run.name, 'stage': stage,
             'status': status, 'updated_at': datetime.now(timezone.utc).isoformat(), **extra}
    write_json(run / 'state.json', value)
    return value


def start(request_path: Path, run: Path):
    request = read_json(request_path)
    check_schema(request, 'request')
    if request.get('input_dir'):
        request['input_dir'] = str((request_path.resolve().parent / request['input_dir']).resolve())
    run = run.resolve()
    if (run / 'request.json').exists() and read_json(run / 'request.json') != request:
        raise LearningError('This run belongs to another request; choose a new output directory.')
    write_json(run / 'request.json', request)
    return normalize(run) if request.get('input_dir') else state(
        run, 'acquisition', 'needs_acquisition', next_action='Use the Skill browser workflow, then attach a scoped input directory with normalize --input.')


def normalize(run: Path, input_dir: Path | None = None):
    run = run.resolve()
    request = read_json(run / 'request.json')
    check_schema(request, 'request')
    if input_dir is not None:
        request['input_dir'] = str(input_dir.resolve())
        write_json(run / 'request.json', request)
    if not request.get('input_dir'):
        return state(run, 'acquisition', 'needs_acquisition', next_action='Collect scoped sources, then normalize --input.')
    root = Path(request['input_dir']).resolve()
    if not root.is_dir() or root == run or root.is_relative_to(run):
        raise LearningError('Input must be an existing directory outside the run directory.')
    # scope.json is an explicit agent-authored acquisition handoff, never inferred
    # from filenames. It may carry identity and missing-resource observations.
    scope = read_json(root / 'scope.json') if (root / 'scope.json').exists() else {
        'schema_version': VERSION, 'course': request['course'], 'scope': request['scope'],
        'basis': 'User selected local source directory; online scope not independently verified.',
        'verified': False, 'missing': [], 'recordings': {}}
    check_schema(scope, 'scope')
    if scope['course'] != request['course'] or scope['scope'] != request['scope']:
        raise LearningError('scope.json does not match the requested course and scope.')
    candidates = sorted(p for p in root.rglob('*') if p.is_file()
                        and p.suffix.lower() in KINDS and not p.resolve().is_relative_to(run)
                        and not any(part.startswith('.') or part in {'output', '__pycache__'}
                                    for part in p.relative_to(root).parts))
    for p in candidates:
        if not p.resolve().is_relative_to(root):
            raise LearningError('Source symlinks must remain inside the input directory.')
    timed = {p.with_suffix('').relative_to(root).as_posix().casefold() for p in candidates
             if p.suffix.lower() in {'.vtt', '.srt'}}
    chosen, seen = [], set()
    for p in sorted(candidates, key=lambda p: (p.relative_to(root).with_suffix('').as_posix(),
                                              {'.vtt': 0, '.srt': 1, '.txt': 2}.get(p.suffix.lower(), 3))):
        stem = p.with_suffix('').relative_to(root).as_posix().casefold()
        if p.suffix.lower() in {'.vtt', '.srt', '.txt'} and stem in timed:
            if stem in seen:
                continue
            seen.add(stem)
        chosen.append(p)
    if not chosen:
        raise LearningError('No supported VTT/SRT/PDF/PPTX/MD/TXT sources in the selected directory.')
    inputs = [{'path': p.relative_to(root).as_posix(), 'sha256': digest(p.read_bytes())} for p in chosen]
    key = fingerprint({'inputs': inputs, 'scope': scope, 'request': request, 'normalizer': NORMALIZER})
    manifest_path = run / 'manifest.json'
    if manifest_path.exists():
        old = read_json(manifest_path)
        if old.get('input_fingerprint') == key and not pack_errors(run, old):
            current = inspect(run)
            current['cache_reused'] = True
            return current
    pack = run / 'packs' / key[:20]
    sources, chunks, warnings = [], [], []
    for p, inp in zip(chosen, inputs):
        sid = 's-' + fingerprint(inp)[:20]
        kind = KINDS[p.suffix.lower()]
        original = pack / 'originals' / (sid + p.suffix.lower())
        atomic_bytes(original, p.read_bytes())
        units = []
        recording = None
        if kind == 'captions':
            recording = 'r-' + fingerprint({'path': inp['path']})[:16]
            cues = load_captions(original)
            previous_end = None
            for i, cue in enumerate(cues, 1):
                start_ms, end_ms = round(cue.start * 1000), round(cue.end * 1000)
                if previous_end is not None and start_ms - previous_end > 30000:
                    warnings.append(f'{sid}: caption gap before cue {i}; not established as silence.')
                previous_end = max(previous_end or 0, end_ms)
                units.append({'id': f'{sid}:c{i:06}', 'source_id': sid, 'recording_id': recording,
                              'type': 'cue', 'start_ms': start_ms, 'end_ms': end_ms, 'text': cue.text})
        elif kind == 'document':
            for page in extract_document(original):
                units.append({'id': f"{sid}:p{page['page']}", 'source_id': sid, 'type': 'page',
                              'page': page['page'], 'text': page['text'],
                              'visual_review_required': len(page['text'].strip()) < 40})
            if any(u['visual_review_required'] for u in units):
                warnings.append(f'{sid}: some pages require visual review.')
        else:
            paragraphs = re.split(r'\n\s*\n', original.read_text(encoding='utf-8-sig').strip())
            units = [{'id': f'{sid}:t{i}', 'source_id': sid, 'type': 'paragraph', 'paragraph': i, 'text': t}
                     for i, t in enumerate(paragraphs, 1) if t.strip()]
        if not units:
            raise LearningError('A source produced no readable units; remove it from selected inputs and record it as missing.')
        index_path = pack / 'units' / f'{sid}.jsonl'
        atomic_bytes(index_path, ('\n'.join(json.dumps(u, ensure_ascii=False) for u in units) + '\n').encode())
        # A single chunk remains bounded by ~8k characters, with long units kept intact.
        batches, batch, size = [], [], 0
        for unit in units:
            if batch and size + len(unit['text']) > 8000:
                batches.append(batch)
                batch, size = [], 0
            batch.append(unit)
            size += len(unit['text'])
        if batch:
            batches.append(batch)
        for i, batch in enumerate(batches, 1):
            cid = f'{sid}:chunk{i}'
            cp = pack / 'chunks' / f'{sid}-{i}.json'
            write_json(cp, batch)
            chunks.append({'id': cid, 'source_id': sid, 'path': cp.relative_to(run).as_posix(),
                           'sha256': digest(cp.read_bytes()), 'unit_ids': [u['id'] for u in batch]})
        identity = scope.get('recordings', {}).get(inp['path'], {}) if recording else {}
        if recording and not identity.get('verified', False):
            warnings.append(f'{sid}: recording identity/language not verified; read scope evidence.')
        sources.append({'id': sid, 'name': inp['path'], 'kind': kind, 'recording_id': recording,
                        'sha256': inp['sha256'], 'path': original.relative_to(run).as_posix(),
                        'units_path': index_path.relative_to(run).as_posix(),
                        'units_sha256': digest(index_path.read_bytes()), 'unit_count': len(units),
                        'identity': identity, 'role': scope.get('roles', {}).get(inp['path'], kind)})
    if not any(s['kind'] == 'captions' for s in sources):
        warnings.append('No timed captions: cannot establish spoken teacher explanations.')
    if not scope['verified']:
        warnings.append('Course/week scope has not been independently verified.')
    manifest = {'schema_version': VERSION, 'normalizer_version': NORMALIZER,
                'input_fingerprint': key, 'scope': scope, 'sources': sources, 'chunks': chunks,
                'warnings': warnings, 'missing': scope['missing']}
    check_schema(manifest, 'manifest')
    write_json(manifest_path, manifest)
    # Never overwrite an existing tutorial or the agent's analysis on refresh.
    write_json(run / 'analysis-template.json', {'schema_version': VERSION, 'input_fingerprint': key,
        'title': '', 'reviewed_chunks': [], 'claims': [], 'sections': [],
        'review': {'teacher_attribution': False, 'scope_coverage': False, 'visual_units': [], 'notes': ''}})
    return state(run, 'analysis', 'awaiting_analysis', warnings=warnings, missing=scope['missing'],
                 artifacts=[str(manifest_path), str(run / 'analysis-template.json')],
                 next_action='Read every manifest chunk, author analysis.json, then render. Do not deliver the template.')


def pack_errors(run, manifest):
    errors = []
    for source in manifest.get('sources', []):
        for path_key, hash_key in [('path', 'sha256'), ('units_path', 'units_sha256')]:
            p = inside(run, source[path_key])
            if not p.is_file() or digest(p.read_bytes()) != source[hash_key]:
                errors.append(f"Source artifact missing or changed: {source['id']} ({path_key})")
    for chunk in manifest.get('chunks', []):
        p = inside(run, chunk['path'])
        if not p.is_file() or digest(p.read_bytes()) != chunk['sha256']:
            errors.append(f"Chunk missing or changed: {chunk['id']}")
    return errors


def load_units(run, manifest):
    return {u['id']: u for s in manifest['sources'] for line in inside(run, s['units_path']).read_text(
        encoding='utf-8').splitlines() if line.strip() for u in [json.loads(line)]}


def analyze_errors(run, manifest, analysis):
    errors = pack_errors(run, manifest)
    if errors:
        return errors
    if analysis['input_fingerprint'] != manifest['input_fingerprint']:
        errors.append('Analysis is stale: input fingerprint differs.')
    chunks = {c['id'] for c in manifest['chunks']}
    if set(analysis['reviewed_chunks']) != chunks:
        errors.append('Every source chunk must be reviewed; unknown chunks are not allowed.')
    units = load_units(run, manifest)
    sources = {s['id']: s for s in manifest['sources']}
    ids = [c['id'] for c in analysis['claims']]
    grounded = [c for c in analysis['claims'] if c['category'] != 'E' and c['unit_ids']]
    if not grounded:
        errors.append('A source-backed tutorial needs grounded course claims, not only AI supplements.')
    covered_recordings = {units[r]['source_id'] for c in grounded for r in c['unit_ids']
                          if r in units and units[r]['type'] == 'cue'}
    if not {s['id'] for s in sources.values() if s['kind'] == 'captions'}.issubset(covered_recordings):
        errors.append('Every selected recording needs at least one grounded claim in the tutorial.')
    if len(ids) != len(set(ids)):
        errors.append('Duplicate claim ID.')
    for claim in analysis['claims']:
        refs = claim['unit_ids']
        if any(r not in units for r in refs):
            errors.append(f"Unknown source unit: {claim['id']}")
            continue
        kinds = {units[r]['type'] for r in refs}
        category = claim['category']
        if category != 'E' and not refs:
            errors.append(f"Missing evidence: {claim['id']}")
        if category in {'B', 'C'} and 'cue' not in kinds:
            errors.append(f"Teacher claim requires caption evidence: {claim['id']}")
        if category == 'A' and 'page' not in kinds:
            errors.append(f"Slide claim requires a page: {claim['id']}")
        if category == 'D' and not ('cue' in kinds or any(
            sources[units[r]['source_id']]['role'] in {'announcement', 'outline', 'schedule'} for r in refs)):
            errors.append(f"Requirement needs a caption or labelled announcement/schedule/outline: {claim['id']}")
        if category == 'C' and not claim.get('uncertainty'):
            errors.append(f"Extension must state checked deck range and uncertainty: {claim['id']}")
        if any(marker in claim['text'] for marker in ['[TODO', '未生成未经证据复核', '待模型或人工复核']):
            errors.append(f"Placeholder claim: {claim['id']}")
    used = [cid for section in analysis['sections'] for cid in section['claim_ids']]
    if set(used) != set(ids):
        errors.append('Sections must reference all and only submitted claims.')
    review = analysis['review']
    if not review['teacher_attribution'] or not review['scope_coverage']:
        errors.append('Agent must complete attribution and scope review.')
    visual = {u['id'] for u in units.values() if u.get('visual_review_required')}
    if not visual.issubset(set(review['visual_units'])):
        errors.append('Low-text pages require visual review before finalizing.')
    if any(u not in units or units[u]['type'] != 'page' for u in review['visual_units']):
        errors.append('Unknown visual review page.')
    return errors


def stamp(ms):
    seconds = ms // 1000
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def render(run: Path, analysis_path: Path):
    run = run.resolve()
    manifest = read_json(run / 'manifest.json')
    check_schema(manifest, 'manifest')
    analysis = read_json(analysis_path)
    check_schema(analysis, 'analysis')
    errors = analyze_errors(run, manifest, analysis)
    quality = {'schema_version': VERSION, 'valid': not errors, 'errors': errors,
               'automated_checks': ['schemas', 'source_hashes', 'unit_references', 'chunk_coverage', 'claim_categories'],
               'agent_review': analysis['review'], 'semantic_truth_automatically_verified': False,
               'warnings': manifest['warnings'], 'missing': manifest['missing']}
    if errors:
        write_json(run / 'quality.json', quality)
        return state(run, 'analysis', 'needs_revision', errors=errors, next_action='Correct analysis and rerun render.')
    units = load_units(run, manifest)
    sources = {s['id']: s for s in manifest['sources']}
    claims = {c['id']: c for c in analysis['claims']}
    labels = {'A': '课件内容', 'B': '老师解释', 'C': '课堂扩展（见核查范围）', 'D': '课程要求/公告', 'E': 'AI 补充'}
    partial = bool(manifest['missing'] or manifest['warnings'])
    lines = [f"# {analysis['title']}", '',
             f"> {'部分完成／存在未验证项' if partial else '已完成来源定位校验和 Agent 复核'}", '',
             f"课程：{manifest['scope']['course']}；范围：{manifest['scope']['scope']}", '',
             f"范围依据：{manifest['scope']['basis']}", '']
    for section in analysis['sections']:
        lines.extend([f"## {section['heading']}", ''])
        for cid in section['claim_ids']:
            claim = claims[cid]
            lines.extend([f"**{labels[claim['category']]}** · {claim['text']}", ''])
            if claim.get('uncertainty'):
                lines.extend([f"核查说明：{claim['uncertainty']}", ''])
            locations = []
            for ref in claim['unit_ids']:
                unit = units[ref]
                source = sources[unit['source_id']]
                location = (f"{stamp(unit['start_ms'])}–{stamp(unit['end_ms'])}" if unit['type'] == 'cue'
                            else f"物理页 {unit['page']}" if unit['type'] == 'page' else f"段落 {unit['paragraph']}")
                locations.append(f"{source['name']} · {location}")
            if locations:
                lines.extend(['来源：' + '；'.join(locations), ''])
    lines.extend(['## 来源索引与覆盖说明', ''])
    from urllib.parse import quote
    for source in manifest['sources']:
        lines.append(f"- [{source['name']}]({quote(source['path'])})：{source['unit_count']} 个来源单元。")
    lines.extend(['', '## 缺失与不确定性', ''])
    lines.extend(['- ' + item for item in manifest['missing'] + manifest['warnings']] or ['未登记缺失；校验不等于自动证明语义正确。'])
    lines.extend(['', '复核说明：' + analysis['review']['notes'], ''])
    text = '\n'.join(lines)
    # Course content could contain a signed URL; never export URL query credentials.
    if re.search(r'https?://[^\s<>]*[?&](?:token|signature|sig|ks|auth|key|expires)=', text, re.I):
        raise LearningError('A potentially signed URL is present in the tutorial; remove URL credentials before rendering.')
    output = run / 'companion.md'
    if output.exists() and output.read_text(encoding='utf-8') != text:
        history = run / 'history' / ('companion-' + digest(output.read_bytes())[:16] + '.md')
        atomic_bytes(history, output.read_bytes())
        # Keep user-edited/default output untouched; new versions are explicit.
        output = run / ('companion-' + fingerprint(analysis)[:12] + '.md')
        if output.exists() and output.read_text(encoding='utf-8') != text:
            output = run / ('companion-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.md')
    atomic_bytes(output, text.encode())
    write_json(run / 'analysis.json', analysis)
    atomic_bytes(run / 'evidence.jsonl', ('\n'.join(json.dumps(c, ensure_ascii=False) for c in analysis['claims']) + '\n').encode())
    quality.update(output=output.name, output_sha256=digest(output.read_bytes()),
                   analysis_sha256=digest((run / 'analysis.json').read_bytes()),
                   evidence_sha256=digest((run / 'evidence.jsonl').read_bytes()),
                   input_fingerprint=manifest['input_fingerprint'])
    write_json(run / 'quality.json', quality)
    return state(run, 'delivered', 'partial' if partial else 'completed',
                 artifacts=[str(output), str(run / 'quality.json')], warnings=manifest['warnings'], missing=manifest['missing'])


def validate(run: Path):
    run = run.resolve()
    try:
        manifest = read_json(run / 'manifest.json')
        check_schema(manifest, 'manifest')
        errors = pack_errors(run, manifest)
        analysis = read_json(run / 'analysis.json')
        check_schema(analysis, 'analysis')
        errors.extend(analyze_errors(run, manifest, analysis))
        quality = read_json(run / 'quality.json')
        for filename, key in [(quality.get('output', 'companion.md'), 'output_sha256'),
                              ('analysis.json', 'analysis_sha256'), ('evidence.jsonl', 'evidence_sha256')]:
            p = inside(run, filename)
            if not p.is_file() or digest(p.read_bytes()) != quality.get(key):
                errors.append(f'Final artifact changed or missing: {filename}')
        if quality.get('input_fingerprint') != manifest['input_fingerprint']:
            errors.append('Quality report is stale.')
        return {'valid': not errors, 'errors': errors, 'semantic_truth_automatically_verified': False}
    except (OSError, ValueError, KeyError, TypeError):
        return {'valid': False, 'errors': ['Missing or invalid source/analysis/quality artifacts; finish analysis and render.']}


def inspect(run: Path):
    run = run.resolve()
    value = read_json(run / 'state.json') if (run / 'state.json').exists() else {'status': 'not_started'}
    if (run / 'manifest.json').exists():
        manifest = read_json(run / 'manifest.json')
        errors = pack_errors(run, manifest)
        if errors:
            return {**value, 'status': 'needs_normalization', 'errors': errors}
        if value.get('stage') == 'delivered':
            report = validate(run)
            if not report['valid']:
                return {**value, 'status': 'needs_revision', 'errors': report['errors']}
    return value
