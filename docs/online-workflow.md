# Online acquisition contract

## Responsibilities

For multi-step work use the host agent's retained browser tab, or the standalone
[live session](browser-session.md). A saved cookie file is not a live browser
session. Do not repeatedly launch one-shot scripts just to inspect the next page.

The agent navigates the authorized course, identifies the requested Week/Lecture, selects the outline, schedule, slides and replays, and explains uncertain associations. The CLI provides acquisition primitives. The user completes SSO/MFA in the CLI browser and may enable CC. No course mapping is inferred from matching numbers alone.

`discover` reports visible anchors from the supplied page and its frames. Dynamic buttons, unopened folders, pagination and blob downloads are not fully covered. A nonempty snapshot is not proof that a page is authenticated or the resource list is complete. Review the labels and URLs before selecting. If the agent has browser tools, use them for those interactive steps; their session does not share cookies with CLI processes.

## Selection file

Store this JSON under `.local/` or outside the repository. Replace URLs with actual file download URLs discovered in the user's course. A page describing a file is not necessarily a download URL.

```json
{
  "course_id": "course-example",
  "scope": "Week 6",
  "resources": [
    {
      "id": "course-outline",
      "kind": "pdf",
      "role": "outline",
      "url": "https://school.example.edu/files/outline.pdf"
    },
    {
      "id": "lecture5-slides",
      "kind": "pptx",
      "role": "slides",
      "url": "https://school.example.edu/files/lecture5.pptx"
    }
  ]
}
```

Top-level course/scope fields are agent context, not interpreted by the current downloader. Resource IDs must be unique ASCII letters/digits/underscores/hyphens, up to 80 characters, and not Windows device names. Downloaded names are derived from IDs, not remote filenames. Text/HTML course outlines, legacy `.ppt`, browser-triggered downloads and redirect resolution need further work. File format checks inspect PDF headers/PPTX containers; they do not guarantee that an entire document can render.

`collect` writes `raw/<id>.<kind>` and `acquisition.json`. A failed resource leaves an explicit failed entry and the command exits with status 1. A previous file can remain after a failed refresh; the manifest status is authoritative. Resume skips only identical selections whose local SHA-256 still matches. It does not perform conditional remote freshness checks yet.

## Caption selection and provenance

`captions` accepts the selected replay page. It registers listeners before navigation and filters results to that page (including iframe requests). Popups are observed by the adapter but are not automatically accepted by the current command. Open the final replay page directly if playback launches a popup.

Kaltura playlist URLs must expose a `captionAssetId`; a single candidate is processed. Multiple candidates produce a private `caption-candidates.json` containing asset IDs. The agent must verify the appropriate track and rerun with `--caption-asset`. The command does not ask the user for F12/cURL. Direct VTT tracks and other media suppliers remain future adapter work.

Complete HLS requires ENDLIST and successful retrieval of every segment. Encrypted, byte-range and initialization-segment formats are rejected. Timestamp origin assumptions, gaps and reordering warnings are retained in `.validation.json`. Gaps do not establish silence. A chosen page/asset is current provenance, not a verified mapping to an LMS recording ID; this remains a release blocker.

## Current test boundary

During navigation, preserve notification contents, page URL and timestamp before
clicking an exact `Remind me later` control. The handler stores a private JSON
record and marks whether the click succeeded. If no dialog landmark is available,
it retains frame text with an explicit scope label. Report notices to the user;
do not replace postponement with settings changes or feedback submission.

Synthetic tests exercise request retries, cookie/header reuse, redirect rejection, HTML rejection, download resume and HLS timelines. The local Edge integration covers real browser capture, authenticated segment downloads and auth-state reload. No real NTU SSO or current course page has been tested in this implementation turn. Use one authorized replay plus an outline and one slide deck for the next acceptance run.
