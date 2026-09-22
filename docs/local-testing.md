# Local testing

BBuddy 0.2.0 packages a Codex Skill, a local Python runtime, multi-recording source normalization, host-agent tutorial writing, and deterministic reference checks.

## Install from GitHub

```powershell
codex plugin marketplace add BoxuanL1/Bbuddy
codex plugin add bbuddy@bbuddy
```

Start a new Codex task so the new Skill is loaded. On first use, Codex can run the bundled `scripts/setup.ps1` after showing the command for review. Setup requires network access to install the pinned Python dependencies and creates an isolated runtime under `%LOCALAPPDATA%\bbuddy` by default.

Use this synthetic request first:

> Use BBuddy with its bundled synthetic-week materials and create a Chinese learning tutorial.

For an authorized online test:

> Use BBuddy to explain what COURSE-CODE covered in TERM teaching Week N and create a learning tutorial.

The user completes SSO/MFA in the visible browser. BBuddy must not request a password or transfer cookies from another browser profile.

## Expected result

The final artifact is a readable `companion.md` or a versioned companion file. `manifest.json`, `analysis.json`, `evidence.jsonl`, and `quality.json` are supporting artifacts.

The tutorial should include actual teaching content, source locations, scope coverage, missing evidence, and clear teacher/AI attribution. A source inventory, download report, or `awaiting_analysis` state is not the final deliverable.

## Development checks

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[browser,documents,test]"
.\.venv\Scripts\python.exe -m pytest -q
$env:BBCOMPANION_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_browser_integration.py -q
$env:SOURCE_DATE_EPOCH = '946684800'
.\.venv\Scripts\python.exe -m build --wheel
.\.venv\Scripts\python.exe scripts/build_plugin.py
.\.venv\Scripts\python.exe scripts/audit_public_release.py .
```

The opt-in browser test uses a synthetic local HTTP server. It does not log in to a real institution.

## Current limits

- Online login detection currently targets NTU Blackboard.
- Kaltura caption acquisition is implemented; other media providers require adapters.
- Course discovery is agent-directed and does not claim a complete catalog from one link snapshot.
- Recording identity and language must be checked against the selected page and available evidence.
- Markdown is the tested output. PDF delivery depends on a host PDF workflow and separate rendering checks.
- Automated validation verifies structure and source locations, not semantic truth.
- BBuddy's Python runtime does not call a model API, but the host model processes selected course text.
