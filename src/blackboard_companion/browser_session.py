"""One live browser for a task, driven by JSON lines over stdin/stdout.

This is a standalone Playwright backend, not a bridge into an agent's browser.
The agent keeps the process alive between commands; no server port is exposed.
Full snapshots and operation errors go to the private run directory.
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from .adapters.blackboard import defer_notifications
from .adapters.kaltura import Capture
from .captions.hls import SubtitleError
from .online import captions, collect, login, read_plan, require_https, save_state, session
from .storage import write_json


class LiveSession:
    """Retain the active tab, frames, capture listener and UI state between actions."""

    def __init__(self, context, profile: Path, output: Path, site: str):
        self.context = context
        self.profile = profile
        self.output = output
        self.site = site
        self.page = None
        self.revision = 0
        self.snapshot_url = None
        self.frames = []
        self.capture = Capture(context)

    async def active_page(self):
        if self.page is None:
            self.page = await self.context.new_page()
        if self.page.is_closed():
            raise SubtitleError('任务标签页已关闭；会话不会自动重开窗口。')
        return self.page

    async def reset_capture(self):
        tasks = list(self.capture.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.capture.candidates.clear()
        self.capture.source_pages.clear()
        self.capture.requests.clear()

    async def inspect(self) -> dict:
        page = await self.active_page()
        notices = await defer_notifications(self.context, self.output / 'notifications')
        self.frames = list(page.frames)
        snapshots = []
        for index, frame in enumerate(self.frames):
            try:
                snapshots.append({
                    'frame': index, 'url': frame.url,
                    'text': await frame.locator('body').inner_text(timeout=5000),
                    'controls': await frame.locator('a,button,[role="button"]').evaluate_all('''nodes => nodes
                        .filter(node => node.getClientRects().length)
                        .map(node => ({text: node.innerText.trim(), role: node.getAttribute('role') || node.tagName.toLowerCase(),
                                       href: node.href || null}))''')})
            except Exception as exc:
                snapshots.append({'frame': index, 'unavailable': type(exc).__name__})
        self.revision += 1
        self.snapshot_url = page.url
        path = self.output / f'snapshot-{self.revision:04}.json'
        write_json(path, {'revision': self.revision, 'url': page.url,
                         'observed_at': datetime.now(timezone.utc).isoformat(), 'frames': snapshots})
        return {'revision': self.revision, 'snapshot': str(path), 'frames': len(snapshots),
                'notifications_recorded': len(notices)}

    async def execute(self, request: dict) -> dict:
        action = request.get('action')
        if action == 'inspect':
            return await self.inspect()
        if action == 'open':
            url = require_https(request['url'])
            page = await self.active_page()
            if page.url != url:
                await self.reset_capture()
                await page.goto(url, wait_until='domcontentloaded')
            return await self.inspect()
        if action == 'click':
            page = await self.active_page()
            if request.get('revision') != self.revision or page.url != self.snapshot_url:
                raise SubtitleError('页面快照已过期；请先 inspect，再根据当前页面选择。')
            frame = self.frames[request.get('frame', 0)]
            await defer_notifications(self.context, self.output / 'notifications')
            target = frame.get_by_text(request['text'], exact=True)
            if 'occurrence' in request:
                target = target.nth(request['occurrence'])
            await self.reset_capture()
            self.snapshot_url = None
            await target.click(timeout=10000)
            # LTI links must be clicked, preserving POST/SSO flow and the same context.
            return await self.inspect()
        if action == 'tabs':
            path = self.output / 'tabs.json'
            write_json(path, [{'index': i, 'url': page.url, 'active': page == self.page}
                              for i, page in enumerate(self.context.pages)])
            return {'tabs': str(path)}
        if action == 'select-tab':
            self.page = self.context.pages[request['index']]
            return await self.inspect()
        if action == 'login':
            result = await login(self.context, self.profile, self.site, request.get('timeout', 600),
                                 page=await self.active_page())
            return {**result, **await self.inspect()}
        if action == 'collect':
            return await collect(self.context, read_plan(Path(request['selection'])), self.output / 'documents')
        if action == 'captions':
            page = await self.active_page()
            url = require_https(request.get('url', page.url))
            if page.url != url:
                await self.reset_capture()
            options = SimpleNamespace(url=url, name=request['name'], output=self.output / 'captions',
                                      caption_asset=request.get('caption_asset'), timeout=request.get('timeout', 300),
                                      timestamps=request.get('timestamps', 'auto'), mpegts_origin=request.get('mpegts_origin'))
            return await captions(self.context, self.profile, options, page=page, capture=self.capture)
        if action == 'close':
            await save_state(self.context, self.profile)
            return {'state': 'closed'}
        raise SubtitleError('未知会话操作；支持 open/inspect/click/tabs/select-tab/login/collect/captions/close。')

    async def cleanup(self):
        self.context.remove_listener('request', self.capture.on_request)
        self.context.remove_listener('response', self.capture.on_response)
        await self.reset_capture()


async def command_loop(live: LiveSession, input_stream=None, output_stream=None):
    """Command failures are recoverable; only close, EOF or process interruption exits."""
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    sequence = 0
    while True:
        line = await asyncio.to_thread(input_stream.readline)
        if not line:
            return
        sequence += 1
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('Expected an object')
            # Existing acquisition functions print progress; stdout stays JSON-only.
            with redirect_stdout(sys.stderr):
                result = await live.execute(request)
            response = {'sequence': sequence, 'ok': True, 'result': result}
        except Exception as exc:
            response = {'sequence': sequence, 'ok': False, 'error_type': type(exc).__name__,
                        'message': str(exc) if isinstance(exc, SubtitleError) else 'Inspect current page; private error details omitted.'}
        write_json(live.output / 'events' / f'{sequence:04}.json', {
            'at': datetime.now(timezone.utc).isoformat(),
            'action': request.get('action') if isinstance(request, dict) else None, **response})
        print(json.dumps(response, ensure_ascii=False), file=output_stream, flush=True)
        if response['ok'] and request.get('action') == 'close':
            return


async def run_live(args) -> dict:
    async with session(args) as (context, profile):
        live = LiveSession(context, profile, args.output, args.site)
        print(json.dumps({'state': 'ready', 'protocol': 'jsonl', 'close': 'explicit close, EOF or interruption'}), flush=True)
        try:
            await command_loop(live)
        finally:
            await live.cleanup()
    return {'state': 'closed'}
