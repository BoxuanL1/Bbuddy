# Browser continuity

The old workflow repeatedly invoked short-lived scripts. Each script launched
Edge, created a context from saved auth state, navigated, then closed the browser.
Cookies were reused, but live UI state and session storage were not. Recreated
pages could trigger feedback notices again. Persistent interaction reduces those
restarts; it cannot promise that Blackboard will never show a new notice.

## Choose a surface

Use the host agent's supported browser for interactive navigation when available.
In Codex, the in-app Browser is supported by its own skill and can keep a tab
across turns with a handoff mark. It is not controlled by the Python package.
Do not export cookies from it to make Python work. The current in-app API exposes
UI and asset operations; this project has not established equivalent Kaltura
network-response capture through that API.

The standalone backend below is for agents using the Python acquisition tools.
It retains one Playwright browser/context and active tab across operations. It
does not connect to, automate, or inspect the host agent's browser profile.

## Start once, send multiple commands

```powershell
bbcompanion browse --account personal --data-dir .local/profiles --output .local/current-run
```

Keep this process and its stdin open. An interactive terminal accepts one JSON
object per line. An agent uses its process/session handle to send another line;
do not rerun the command for every operation. Responses are JSON lines; acquisition
progress goes to stderr. URLs/text and operation records are saved privately.

```json
{"action":"login"}
{"action":"open","url":"https://ntulearn.ntu.edu.sg/ultra/course"}
{"action":"inspect"}
```

Read the returned snapshot. Its `revision` is needed for a click, and frame indexes
come from that same snapshot. Use the exact observed text. For duplicate controls,
`occurrence` selects a zero-based match after the agent has inspected the page.

```json
{"action":"click","revision":3,"frame":0,"text":"Course Contents"}
{"action":"inspect"}
{"action":"tabs"}
{"action":"select-tab","index":1}
{"action":"collect","selection":".local/selection.json"}
{"action":"captions","name":"week6-thursday","caption_asset":"VERIFIED_ASSET_ID"}
{"action":"close"}
```

These are examples, not a fixed click sequence. A loading SPA may need a later
`inspect`; an empty first snapshot is not proof of missing content. Clicks retain
the same tab; popups remain in the same context and can be selected explicitly.
`captions` defaults to the current page and uses a listener registered when the
session started, before navigation. A successful capture does not close the
browser. All previous export and provenance limitations still apply.

`open` on the current exact URL only inspects; it does not reload. A failed command
returns `ok: false` and keeps the window open. A closed tab is reported rather than
silently replaced; use `tabs`/`select-tab` for another existing page. Only explicit
`close`, stdin EOF or process interruption exits the session. Do not pipe a single
command then close stdin if you want a live session across agent turns.

This is a foreground worker, not a daemon: no TCP port, background installer or
auto-relaunch mechanism is created. Auth state is saved by login, successful
caption acquisition and explicit close. A crash is not guaranteed to save the
latest state. The browser must be launched once per new worker process.

## Verification

Unit tests check same-URL reuse, closed-page behavior, malformed commands, private
error redaction and recovery after failure. The opt-in local Edge test opens a
synthetic course folder, inspects and opens the same URL again, verifies one page
and one server navigation, and confirms the folder remains expanded after an error.
No production site or visible browser window is needed for this regression test.
