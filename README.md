# BBuddy

BBuddy turns an authorized Blackboard course week into a source-backed learning tutorial. It combines lecture captions, PDF/PPTX slides, outlines, schedules, and announcements while keeping teacher statements, course materials, and AI-authored explanations clearly separated.

The current online adapter targets NTU Blackboard with Kaltura captions. Local source processing works with timed VTT/SRT captions, PDF/PPTX documents, and Markdown/TXT context files.

> BBuddy is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by Nanyang Technological University, Blackboard, Anthology, or Kaltura.

## What it produces

A request such as:

> Use BBuddy to explain what COURSE-CODE covered in teaching Week N and create a Chinese learning tutorial.

can produce a Markdown companion containing:

- the verified course and week scope;
- a slide and recording reading map;
- source-backed lecturer explanations;
- clearly labelled AI supplements;
- assignments or announcements only when supported by evidence;
- a suggested study sequence and self-check questions;
- source locations, missing materials, and unresolved uncertainty.

Python performs acquisition, normalization, hashing, checkpointing, and deterministic reference checks. Codex reads the source pack and writes the tutorial. The Python runtime does not call a separate model API.

## Requirements

- Windows x64
- Python 3.11
- Microsoft Edge
- Codex or another compatible skill-capable host
- Authorized access to the course materials you request

Users complete SSO/MFA in a visible browser. BBuddy does not request passwords in chat or import cookies from another browser profile.

## Install in Codex from GitHub

Add this repository as a marketplace and install the plugin:

```powershell
codex plugin marketplace add BoxuanL1/Bbuddy
codex plugin add bbuddy@bbuddy
```

Start a new Codex task, select BBuddy, and ask it to run the bundled setup when prompted. The setup script creates a dedicated runtime under `%LOCALAPPDATA%\bbuddy` and installs the pinned Python dependencies. It does not store course files in the Git repository.

For a no-login demonstration, ask:

> Use BBuddy with its bundled synthetic-week materials and create a Chinese learning tutorial.

The synthetic example contains two short optimization lectures and generated slides. It is not real course material.

## Develop locally

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[browser,documents,test]"
.\.venv\Scripts\python.exe -m pytest -q
```

The opt-in browser tests use only a synthetic local HTTP server:

```powershell
$env:BBCOMPANION_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_browser_integration.py -q
```

Build the distributable plugin after tests pass:

```powershell
$env:SOURCE_DATE_EPOCH = '946684800'
.\.venv\Scripts\python.exe -m build --wheel
.\.venv\Scripts\python.exe scripts/build_plugin.py
.\.venv\Scripts\python.exe scripts/audit_public_release.py .
```

## Privacy and boundaries

- Course files, captions, browser profiles, authentication state, signed URLs, inventories, and generated tutorials are private runtime data and are excluded from this repository.
- Local processing does not mean offline model inference: Codex may process the selected source text to write the requested tutorial.
- A successful file download does not prove a complete course inventory or a complete transcript.
- Automated validation checks source hashes and reference locations; it does not independently prove the semantic truth of an explanation.
- Users must access only materials they are authorized to use and must follow their institution's policies and applicable law.

See [security guidance](SECURITY.md), [privacy details](PRIVACY.md), [supported workflow](docs/local-testing.md), and [architecture](docs/architecture.md).

## Project status

Version 0.2.0 is a local-test release. Multi-recording normalization, source namespaces, tutorial rendering, cache invalidation, evidence validation, and synthetic browser integration tests are implemented. Real Blackboard layouts and Kaltura behavior can change, so online course and recording identity must still be verified during each run.

## License

MIT. See [LICENSE](LICENSE).
