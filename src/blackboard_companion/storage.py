"""Private profile paths and atomic checkpoint writes."""
import hashlib
import json
import os
import tempfile
from pathlib import Path


def profile_dir(site: str, account: str, root: Path | None = None) -> Path:
    base = root or Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'bbcompanion'
    key = hashlib.sha256(f'{site.rstrip("/")}\0{account}'.encode()).hexdigest()[:24]
    return base / key


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.partial-')
    temp = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))
