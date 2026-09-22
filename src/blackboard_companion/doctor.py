"""Local environment diagnostics without reading credentials."""
import importlib.metadata
import os
import platform
import sys
import tempfile
from pathlib import Path

from . import __version__


def diagnose(data_dir: Path | None = None):
    checks = {}
    checks['python'] = {'ok': sys.version_info >= (3, 11), 'version': platform.python_version(), 'path': sys.executable}
    for package in ['jsonschema', 'playwright', 'pypdf', 'python-pptx']:
        try:
            checks[package] = {'ok': True, 'version': importlib.metadata.version(package)}
        except importlib.metadata.PackageNotFoundError:
            checks[package] = {'ok': False, 'fix': 'Run the bundled setup.ps1 to install the locked runtime.'}
    edge_paths = [Path(os.environ.get(key, 'C:/Program Files')) / 'Microsoft/Edge/Application/msedge.exe'
                  for key in ['PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA']]
    checks['edge'] = {'ok': any(p.is_file() for p in edge_paths),
                      'fix': 'Install Microsoft Edge, or install Playwright Chromium and select --browser chromium.'}
    directory = data_dir or Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'bbuddy'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
        checks['data_directory'] = {'ok': True, 'path': str(directory.resolve())}
    except OSError:
        checks['data_directory'] = {'ok': False, 'fix': 'Choose a writable --data-dir.'}
    return {'version': __version__, 'contract_version': '1.0', 'checks': checks,
            'valid': all(c['ok'] for key, c in checks.items() if key != 'edge'),
            'online_ready': all(c['ok'] for c in checks.values()),
            'authentication': 'not_checked; SSO/MFA is performed in a visible browser'}
