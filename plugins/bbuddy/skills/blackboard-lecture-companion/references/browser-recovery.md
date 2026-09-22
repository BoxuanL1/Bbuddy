# Recover navigation without losing the session

Read this when a course click, folder expansion, media launch or file visit does
not produce the intended resource. These rules describe observed failure patterns,
not a fixed NTU course ID, recording ID, folder order or guaranteed page layout.

## Inspect before retrying

Keep the current tab open and obtain fresh visible state. Check for notifications,
loading content, collapsed
folders, ambiguous controls and changed frames. A timeout alone does not establish
which of these caused it. In the Python session use `inspect`, then use the new
revision/frame information; do not reuse a stale click command.

| Observed result | Recovery |
|---|---|
| A course entry has `javascript:void(0)` or another UI-only target | Click its observed control in the current course list; do not navigate to that value as a URL. |
| A role/name locator fails | Inspect the rendered title and accessible controls, then select an unambiguous observed target. Do not invent selectors or blindly retry. |
| Course Contents opens but no files appear | Check whether another folder, such as Lecture Note, is still collapsed. Expand only what the current page shows. |
| A feedback/notification overlay offers Remind me later | Save its visible text, source and observation time, click that exact control, record the outcome, then inspect the underlying page. |
| Direct Media Gallery navigation shows `NoSuchKey` or an invalid launch page | Return to the retained course page and click its actual Media Gallery/LTI entry to preserve the normal launch flow. |
| A direct replay URL shows Access Denied | Check the course's media launch path in the same browser session. Course authentication does not prove media authentication. If the authorized launch still fails, report access failure; do not bypass it. |
| A slide link opens a viewer | Treat that as a source page, not the downloaded file. Use a download control or actual file URL exposed by the viewer, through the chosen browser's supported tools. Verify downloaded content. |
| Outline/schedule is inline text rather than a file | Preserve visible source text, URL and capture time. Do not manufacture a PDF or assert that an absent download means the outline is missing. |

When a popup is opened by the normal flow, retain it in the same browser session;
use the supported tab-selection API. Do not create another browser just to follow it.
Background integration-frame text alone is not evidence of a visible blocking notice.

## Confirm success at the resource level

Browser navigation or a command exit code can succeed while the page says Access
Denied, NoSuchKey or Login. Confirm the selected course, recording title and actual
resource before reporting acquisition. Preserve source dates even when they appear
inconsistent, and flag the inconsistency; do not silently rewrite deadlines.
Week numbers do not establish lecture-note numbers, and a related deck is not a
verified cue-to-page mapping. Final reports must retain these distinctions.
