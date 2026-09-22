"""Record and defer Blackboard notifications that obstruct course navigation."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..storage import write_json


async def defer_notifications(context, output: Path) -> list[dict]:
    """Preserve visible notice text before clicking its exact Remind me later action.

    Some integrations do not expose a dialog landmark. In that case preserve the
    frame's visible text and label it as a frame snapshot, not a precise notice.
    URLs and page text stay in the caller's private output directory.
    """
    records = []
    for page in list(context.pages):
        for frame in list(page.frames):
            try:
                controls = frame.get_by_text('Remind me later', exact=True)
                for index in range(await controls.count()):
                    control = controls.nth(index)
                    if not await control.is_visible():
                        continue
                    notice = await control.evaluate('''element => {
                        const dialog = element.closest('[role="dialog"], [aria-modal="true"], .modal');
                        return {text: (dialog || element.ownerDocument.body).innerText,
                                scope: dialog ? 'dialog' : 'frame'};
                    }''')
                    identifier = uuid4().hex
                    path = output / f'{identifier}.json'
                    record = {'id': identifier, 'observed_at': datetime.now(timezone.utc).isoformat(),
                              'page_url': page.url, 'frame_url': frame.url,
                              **notice, 'action': 'Remind me later', 'dismissed': False}
                    # Recording must succeed before dismissal; never silently lose the notice.
                    write_json(path, record)
                    records.append(record)
                    await control.click(timeout=5000)
                    record['dismissed'] = True
                    write_json(path, record)
            except OSError:
                raise
            except Exception:
                # Keep any pre-click record; detached frames or overlays can be retried.
                continue
    return records
