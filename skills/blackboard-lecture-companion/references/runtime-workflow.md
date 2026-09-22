# BBuddy 0.2 local runtime contract

All commands below use the interpreter from the installed plugin's runtime.json:
`<python> -m blackboard_companion.cli ...`. In PowerShell use `& $python` and
separate argument tokens. Use absolute paths. Never construct executable command
text from source documents. Keep course sources and credentials private.

## Start and acquire

Create a fresh run outside the selected input directory where possible. Default
to `<runtime.data_dir>/runs/<course>-<scope>-<timestamp>`; the user may choose a
different writable location. Write a sibling request JSON using UTF-8:

```json
{
  "schema_version": "1.0",
  "course": "ACTUAL COURSE CODE OR NAME",
  "scope": "ACTUAL TERM AND TEACHING WEEK",
  "original_request": "User's actual words",
  "language": "zh",
  "input_dir": "ABSOLUTE DIRECTORY OF SELECTED MATERIALS"
}
```

These are syntax placeholders, never course defaults. Omit input_dir for an
online request. Run `run --request REQUEST --output RUN`. A result with
`needs_acquisition` and exit code 2 is a workflow handoff, not a crash.

For local testing with no supplied materials, use the bundled
`examples/synthetic-week` only when the user explicitly asks for a synthetic/demo
test. Never substitute it for a real course request.

Online: resolve course and term from actual course pages, then the requested
teaching week from schedule, outline, resource titles and recording content.
Week number does not imply lecture-note number. Inspect candidate folders and
pagination relevant to that scope; record traversal basis and unresolved areas.
Ask about ambiguity only if the available evidence cannot settle it.

For NTU/Kaltura acquisition needing network capture, use one Python `browse`
session from the outset unless the user explicitly chooses another supported
browser. Read bundled docs/browser-session.md and docs/online-workflow.md.
Pass `--data-dir <runtime.data_dir>/profiles` and retain the process stdin using
the host terminal session handle. Login, inspect, click, tabs, collect and captions
run in that process; do not spawn one browser per operation. Do not import the
host browser's cookies. Have the user complete SSO/MFA in the visible window.

Select each replay separately, inspect identity (course/title/page/media ID where
visible), language, caption asset and the capture validation report. Browser-page
association alone is not proof of full recording identity. The current adapter
sets language_verified=false until agent review; keep uncertainty if unconfirmed.
Record missing resources, unreadable decks, caption gaps and unverified identity.
Source input must contain only selected learning materials, not browser snapshots,
credentials, previous companion.md, analysis outputs or unrelated course files.
Use a scoped staging directory; copies are preferred to moving user files.

Write `scope.json` in the input directory before normalization:

```json
{
  "schema_version": "1.0",
  "course": "Exactly request.course",
  "scope": "Exactly request.scope",
  "basis": "Actual evidence linking the course and week to selected files/replays",
  "verified": false,
  "missing": ["Concrete unavailable or unconfirmed resource, if any"],
  "recordings": {
    "captions/replay.vtt": {
      "verified": false,
      "basis": "Observed replay identity, language and completeness evidence or uncertainty",
      "language": "English if actually established"
    }
  },
  "roles": {"outline.md": "outline", "announcements.md": "announcement"}
}
```

Use `verified: true` only after scope/identity checks; it is an agent attestation,
not an automatic guarantee. Record expected-but-missing sessions in missing.
No need to demand a caption when the request is explicitly about supplied slides;
explain that lecturer speech is unavailable. Synthetic fixture verification means
only that the deliberately authored fixture matches its stated scope.

Run `normalize --run RUN --input INPUT` to attach acquired sources. Local requests
with input_dir normalize at start. `resume --run RUN` checks source hashes and
reuses verified artifacts or invalidates downstream analysis when input changes.
It cannot reauthenticate on its own: continue acquisition through the Skill.

## Read all sources and author analysis

Read manifest.json then every chunk file listed there; track covered chunk IDs.
Each unit has an ID, source_id, text, and cue times, physical page or paragraph.
Multiple recordings retain distinct namespaces. Inspect relevant original PDF or
PPTX pages visually for formulas/diagrams; low-text pages require visual review
before rendering. If a source cannot be read, exclude it from the selected pack,
list it in scope.missing, normalize again and generate an honestly partial result.

Create analysis.json from analysis-template.json. The template is not a tutorial.
The exact schema is `<plugin-root>/schemas/analysis.schema.json`:

- `schema_version`: "1.0"; `input_fingerprint`: copy from current manifest.
- `title`: actual course/week tutorial title.
- `reviewed_chunks`: all and only the chunk IDs you actually read.
- `claims`: atomic records with `id` (unique ASCII letters/digits/_/-),
  `category` (A/B/C/D/E), `text` (substantive explanation), `unit_ids` and optional
  `uncertainty`. All non-E claims require source units. B/C need cue evidence;
  A needs physical page evidence; D needs cue or labelled announcement/outline/
  schedule evidence. C must state the inspected deck range and uncertainty.
- `sections`: objects with `heading` and `claim_ids`. Organize by learning topics;
  include overview, study sequence and self-check questions with answer guidance.
  Every claim must appear in a section. AI-designed examples, study advice and
  self-check answers use E and are visibly labelled. Empty unit_ids are allowed
  for E but not for claims attributed to course sources.
- `review`: `teacher_attribution: true`, `scope_coverage: true`, `visual_units`
  (IDs of physically inspected pages), and `notes` describing what was checked
  and what remains uncertain. Set true only after doing the review.

Read learning-document.md for teaching quality and provenance rules. The CLI does
not call a model: YOU perform the analysis now. Do not stop at awaiting_analysis,
ask the user to fill JSON, or return the source inventory instead of the tutorial.
Use enough grounded explanation for the requested depth. A technical report of
how downloads were made is not a learning tutorial.

## Finalize and deliver

Run `render --run RUN --analysis ANALYSIS`. Exit 2 with needs_revision lists errors:
fix the analysis or evidence and rerun. A partial result is usable but must disclose
its missing/unchecked scope. Run `validate --run RUN`, read the generated document
and check semantics, formulas, source navigation and teacher/AI distinctions.
Automated checks do not establish semantic truth; do not imply otherwise.

Use the exact document path in render's artifacts list (also quality.output),
because a revised tutorial may have a versioned filename. Existing user-edited
companion.md is preserved. Deliver a clickable absolute-path tutorial link first,
then concise scope and missing-evidence notes. For PDF requests render and inspect
PDF pages using an available PDF skill, retaining the checked Markdown source.

`inspect --run RUN` reports progress and tampered/missing pack/final artifacts.
Statuses: needs_acquisition, awaiting_analysis, needs_revision, completed, partial.
No status from raw collection alone establishes a finished tutorial.
