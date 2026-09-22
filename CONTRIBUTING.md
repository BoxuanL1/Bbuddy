# Contributing

Contributions are welcome for deterministic document processing, Blackboard adapters, media adapters, source validation, tutorial quality rules, installation, and documentation.

Keep model-independent processing separate from host-agent analysis. Add LMS or media support behind an adapter rather than coupling it to caption merging.

Public tests and examples must be wholly synthetic. Never commit cookies, browser state, signed URLs, HAR files, private course material, real announcements, or unredacted logs. New evidence behavior should include a synthetic fixture and a meaningful validation assertion.

Before opening a pull request, run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:SOURCE_DATE_EPOCH = '946684800'
.\.venv\Scripts\python.exe -m build --wheel
.\.venv\Scripts\python.exe scripts/build_plugin.py
.\.venv\Scripts\python.exe scripts/audit_public_release.py .
```

Describe the user-visible behavior, the supported environment, and the validation performed. Do not claim compatibility with an LMS deployment or media provider without a reproducible test basis.
