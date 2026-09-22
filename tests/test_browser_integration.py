"""Local end-to-end test with real Edge and cookie-protected HTTP fixtures."""
import os
import asyncio
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from blackboard_companion.adapters.kaltura import Capture, resolve_playlist
from blackboard_companion.captions.hls import merge_segments, export


class Handler(BaseHTTPRequestHandler):
    retries = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Set-Cookie', 'fixture=logged-in; Path=/')
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<title>Fixture replay</title><script>fetch("/serveWebVTT/a.m3u8", {headers:{"X-Fixture":"yes"}})</script>')
            return
        if 'fixture=logged-in' not in self.headers.get('Cookie', '') or self.headers.get('X-Fixture') != 'yes':
            self.send_response(403)
            self.end_headers()
            return
        if self.path == '/serveWebVTT/a.m3u8':
            body = '#EXTM3U\n#EXTINF:300,\n1.vtt\n#EXTINF:300,\n2.vtt\n#EXT-X-ENDLIST\n'
        elif self.path == '/serveWebVTT/1.vtt':
            body = 'WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\n00:00:01.000 --> 00:00:02.000\nfirst\n'
        elif self.path == '/serveWebVTT/2.vtt':
            Handler.retries += 1
            if Handler.retries == 1:
                self.send_response(503)
                self.end_headers()
                return
            body = 'WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:27900000\n\n00:00:01.000 --> 00:00:02.000\nsecond\n'
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/vnd.apple.mpegurl' if '.m3u8' in self.path else 'text/vtt')
        self.end_headers()
        self.wfile.write(body.encode())


@unittest.skipUnless(os.environ.get('BBCOMPANION_BROWSER_TESTS') == '1', 'opt-in local Edge integration')
class BrowserTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_commands_preserve_one_page_and_folder_state(self):
        from playwright.async_api import async_playwright
        from blackboard_companion.browser_session import LiveSession

        class CourseHandler(BaseHTTPRequestHandler):
            visits = 0

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == '/course':
                    CourseHandler.visits += 1
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<details id="folder"><summary>Lecture Note</summary><p>Week 6</p></details>')

        server = ThreadingHTTPServer(('127.0.0.1', 0), CourseHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(channel='msedge', headless=True)
                    try:
                        context = await browser.new_context()
                        live = LiveSession(context, Path(temporary), Path(temporary), 'https://school.test')
                        try:
                            # Only this synthetic test permits localhost HTTP; production remains HTTPS.
                            with patch('blackboard_companion.browser_session.require_https', side_effect=lambda url: url):
                                url = f'http://127.0.0.1:{server.server_port}/course'
                                first = await live.execute({'action': 'open', 'url': url})
                                page = live.page
                                await live.execute({'action': 'click', 'text': 'Lecture Note', 'revision': first['revision']})
                                await live.execute({'action': 'open', 'url': url})
                                self.assertIs(live.page, page)
                                self.assertEqual(len(context.pages), 1)
                                self.assertEqual(CourseHandler.visits, 1)
                                self.assertEqual(await page.locator('#folder[open]').count(), 1)
                                with self.assertRaises(Exception):
                                    await live.execute({'action': 'click', 'text': 'Lecture Note', 'revision': -1})
                                await live.execute({'action': 'inspect'})
                                self.assertTrue(browser.is_connected())
                        finally:
                            await live.cleanup()
                    finally:
                        await browser.close()
        finally:
            server.shutdown()
            server.server_close()

    async def test_capture_cookie_reuse_retry_merge_export_and_reload_auth(self):
        from playwright.async_api import async_playwright
        Handler.retries = 0
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                async with async_playwright() as p:
                    browser = await p.chromium.launch(channel='msedge', headless=True)
                    try:
                        context = await browser.new_context()
                        capture = Capture(context)
                        page = await context.new_page()
                        base = f'http://127.0.0.1:{server.server_port}'
                        await page.goto(base)
                        for _ in range(50):
                            if capture.candidates:
                                break
                            await asyncio.sleep(.1)
                        self.assertEqual(len(capture.candidates), 1)
                        url, (body, headers) = next(iter(capture.candidates.items()))
                        segments, bodies = await resolve_playlist(context, capture, url, body, headers, root / 'cache')
                        cues, report = merge_segments(segments, bodies)
                        self.assertEqual([c.start for c in cues], [1, 301])
                        self.assertEqual(Handler.retries, 2)
                        name = export(cues, root, 'fixture', report)
                        self.assertTrue((root / (name + '.srt')).exists())
                        auth = root / 'state.json'
                        await context.storage_state(path=str(auth), indexed_db=True)
                        restored = await browser.new_context(storage_state=str(auth))
                        response = await restored.request.get(base + '/serveWebVTT/1.vtt', headers={'X-Fixture': 'yes'})
                        self.assertEqual(response.status, 200)
                        await response.dispose()
                    finally:
                        await browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
