"""Fail when a prospective public release contains private runtime material."""
from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path


SKIP_DIRS = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist'}
PRIVATE_DIRS = {'.local', 'trial', '.ntu_auth', '.ntu_cache', 'wheelhouse'}
PRIVATE_NAMES = {
    'runtime.json', 'state.json', 'storage_state.json', 'caption-candidates.json',
    'acquisition.json', 'inventory.json', 'selection.json',
}
COURSE_EXTENSIONS = {'.pdf', '.ppt', '.pptx', '.srt', '.vtt', '.png', '.jpg', '.jpeg'}
PATTERNS = {
    'real-course-marker': re.compile(r'AI610[14]|26S1', re.I),
    'local-absolute-path': re.compile(r'(?:[A-Z]:\\(?:Users|Desktop)\\|/Users/|/home/)', re.I),
    'private-user-marker': re.compile(r'李帛宣'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(r'(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}'),
    'openai-token': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'),
    'bearer-token': re.compile(r'Authorization\s*:\s*Bearer\s+\S+', re.I),
    'signed-url': re.compile(r'https?://\S+[?&](?:token|signature|sig|ks|auth|key|expires)=', re.I),
}


def is_synthetic(path: Path) -> bool:
    value = path.as_posix()
    return value.startswith('examples/synthetic') or value.startswith('plugins/bbuddy/examples/synthetic')


def scan_text(text: str, location: str) -> list[str]:
    findings: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(f'{label}: {location}:{number}')
    return findings


def scan_archive(path: Path, relative: Path) -> list[str]:
    findings: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or '..' in member_path.parts:
                    findings.append(f'unsafe-archive-path: {relative.as_posix()}!{member.filename}')
                    continue
                if member.is_dir():
                    continue
                suffix = member_path.suffix.lower()
                if suffix not in {'.py', '.json', '.txt', '.xml', '.rels'} and member_path.name not in {'METADATA', 'entry_points.txt'}:
                    continue
                try:
                    content = archive.read(member).decode('utf-8')
                except (KeyError, UnicodeDecodeError, OSError):
                    continue
                findings.extend(scan_text(content, f'{relative.as_posix()}!{member.filename}'))
    except (zipfile.BadZipFile, OSError):
        findings.append(f'invalid-archive: {relative.as_posix()}')
    return findings


def audit(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if any(part in PRIVATE_DIRS for part in relative.parts):
            findings.append(f'private-path: {relative.as_posix()}')
            continue
        if not path.is_file():
            continue
        if path.name in PRIVATE_NAMES or path.suffix.lower() in {'.har'}:
            findings.append(f'private-file: {relative.as_posix()}')
        if path.suffix.lower() in COURSE_EXTENSIONS and not is_synthetic(relative):
            findings.append(f'non-synthetic-course-asset: {relative.as_posix()}')
        if path.suffix.lower() == '.whl' and not path.name.startswith('blackboard_lecture_companion-'):
            findings.append(f'third-party-wheel: {relative.as_posix()}')
        if path.suffix.lower() in {'.whl', '.pptx'}:
            if path.suffix.lower() == '.whl' and path.name.startswith('blackboard_lecture_companion-'):
                checksum_path = path.parent / 'SHA256SUMS.txt'
                if not checksum_path.is_file():
                    findings.append(f'missing-wheel-checksum: {relative.as_posix()}')
                else:
                    expected = checksum_path.read_text(encoding='utf-8').split()[0].lower()
                    actual = hashlib.sha256(path.read_bytes()).hexdigest()
                    if expected != actual:
                        findings.append(f'wheel-checksum-mismatch: {relative.as_posix()}')
            findings.extend(scan_archive(path, relative))
            continue
        if relative.as_posix() == 'scripts/audit_public_release.py':
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text('\n'.join(lines), relative.as_posix()))
    return sorted(set(findings))


if __name__ == '__main__':
    release_root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
    problems = audit(release_root)
    if problems:
        print('\n'.join(problems))
        raise SystemExit(1)
    print('Public release audit passed: no private runtime paths, real course assets, tokens, or local identity markers found.')
