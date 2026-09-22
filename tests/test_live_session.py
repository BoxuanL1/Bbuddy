"""Regression tests for task-scoped browser lifetime and recoverable commands."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from blackboard_companion.browser_session import LiveSession, command_loop
from blackboard_companion.captions.hls import SubtitleError


class LiveSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_tab_and_does_not_reload_same_url(self):
        page = SimpleNamespace(url='https://school.test/course', is_closed=lambda: False,
                               goto=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page), on=lambda *args: None)
        with tempfile.TemporaryDirectory() as directory:
            live = LiveSession(context, Path(directory), Path(directory), 'https://school.test')
            live.inspect = AsyncMock(return_value={'revision': 1})
            await live.execute({'action': 'open', 'url': page.url})
            await live.execute({'action': 'open', 'url': page.url})
            context.new_page.assert_awaited_once()
            page.goto.assert_not_awaited()
            page.is_closed = lambda: True
            with self.assertRaises(SubtitleError):
                await live.active_page()
            context.new_page.assert_awaited_once()

    async def test_command_failure_keeps_loop_alive_and_records_error(self):
        with tempfile.TemporaryDirectory() as directory:
            live = SimpleNamespace(output=Path(directory), execute=AsyncMock(side_effect=[
                SubtitleError('stale page'), {'revision': 2}, {'state': 'closed'}]))
            commands = io.StringIO('\n'.join(json.dumps({'action': action})
                                            for action in ('click', 'inspect', 'close')) + '\n')
            output = io.StringIO()
            await command_loop(live, commands, output)
            results = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual([r['ok'] for r in results], [False, True, True])
            self.assertEqual(live.execute.await_count, 3)
            self.assertEqual(len(list((Path(directory) / 'events').glob('*.json'))), 3)

    async def test_malformed_request_and_eof_do_not_relaunch(self):
        with tempfile.TemporaryDirectory() as directory:
            live = SimpleNamespace(output=Path(directory), execute=AsyncMock(return_value={'revision': 1}))
            output = io.StringIO()
            await command_loop(live, io.StringIO('not-json\n[]\n{"action":"inspect"}\n'), output)
            self.assertEqual([json.loads(line)['ok'] for line in output.getvalue().splitlines()], [False, False, True])
            live.execute.assert_awaited_once()

    async def test_error_does_not_expose_private_browser_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            live = SimpleNamespace(output=Path(directory), execute=AsyncMock(side_effect=RuntimeError('https://private.invalid/?credential=SECRET')))
            output = io.StringIO()
            await command_loop(live, io.StringIO('{"action":"inspect"}\n'), output)
            self.assertNotIn('SECRET', output.getvalue())
            self.assertNotIn('SECRET', (Path(directory) / 'events/0001.json').read_text())
