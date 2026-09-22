import asyncio
import tempfile
import unittest
from pathlib import Path

from blackboard_companion.captions.hls import (Cue, Segment, SubtitleError, export,
                                               merge_segments, parse_playlist, parse_vtt, timestamp)
from blackboard_companion.adapters.kaltura import Capture, download


def vtt(start, end, text='hello', mapping=''):
    return f'WEBVTT\n{mapping}\n\n{timestamp(start)} --> {timestamp(end)}\n{text}\n'


class SubtitleTests(unittest.TestCase):
    def test_relative_urls_and_durations(self):
        body = '#EXTM3U\n#EXTINF:300,\nfirst.vtt?signature=private\n#EXTINF:20,\n../last.vtt\n#EXT-X-ENDLIST\n'
        segments, _, ended = parse_playlist(body, 'https://example.test/cap/a.m3u8')
        self.assertTrue(ended)
        self.assertEqual(segments[1].start, 300)
        self.assertEqual(segments[1].url, 'https://example.test/last.vtt')

    def test_english_master_selection(self):
        body = '#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,LANGUAGE="zh",NAME="Chinese",URI="zh.m3u8"\n#EXT-X-MEDIA:TYPE=SUBTITLES,LANGUAGE="en",NAME="English",URI="en.m3u8"'
        _, children, _ = parse_playlist(body, 'https://example.test/a.m3u8')
        self.assertTrue(children[0][1].endswith('/en.m3u8'))

    def test_absolute_timeline_and_duplicate_boundary(self):
        bodies = [vtt(298, 302), vtt(298, 302) + '\n00:05:03.000 --> 00:05:04.000\nnext\n']
        cues, report = merge_segments([Segment('', 0, 300), Segment('', 300, 300)], bodies)
        self.assertEqual([c.start for c in cues], [298, 303])
        self.assertEqual(report['duplicates_removed'], 1)

    def test_local_timeline(self):
        cues, _ = merge_segments([Segment('', 0, 300), Segment('', 300, 300)],
                                [vtt(1, 2), vtt(3, 4)])
        self.assertEqual(cues[1].start, 303)

    def test_timestamp_map_absolute_and_local(self):
        first = vtt(1, 2, mapping='X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000')
        for second in (vtt(301, 302, mapping='X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000'),
                       vtt(1, 2, mapping='X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:27900000')):
            cues, _ = merge_segments([Segment('', 0, 300), Segment('', 300, 300)], [first, second])
            self.assertEqual(cues[1].start, 301)

    def test_wrap(self):
        origin = 2 ** 33 - 90000
        bodies = [vtt(0, .5, mapping=f'X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:{origin}'),
                  vtt(0, .5, mapping='X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:90000')]
        cues, _ = merge_segments([Segment('', 0, 2), Segment('', 2, 2)], bodies)
        self.assertAlmostEqual(cues[1].start, 2)

    def test_discontinuity(self):
        bodies = [vtt(1, 2, mapping='X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000'),
                  vtt(1, 2, mapping='X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:0')]
        cues, _ = merge_segments([Segment('', 0, 300), Segment('', 300, 300, True)], bodies)
        self.assertEqual(cues[1].start, 301)

    def test_invalid_vtt_and_unsupported_playlist(self):
        with self.assertRaises(SubtitleError):
            parse_vtt('<html>Login</html>')
        with self.assertRaises(SubtitleError):
            parse_playlist('#EXTM3U\n#EXT-X-BYTERANGE:100@0\n', 'https://example.test/a')

    def test_gap_and_export(self):
        cues, report = merge_segments([Segment('', 0, 300)],
                                     [vtt(0, 1, '<v Teacher>A &amp; B') + '\n00:01:00.000 --> 00:01:01.000\nnext\n'])
        self.assertEqual(len(report['gaps_over_30_seconds']), 1)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            name = export(cues, path, 'Video:one', report)
            self.assertEqual((path / (name + '.vtt')).read_text().count('WEBVTT'), 1)
            self.assertIn('00:00:00,000 --> 00:00:01,000', (path / (name + '.srt')).read_text())
            self.assertIn('A & B', (path / (name + '.txt')).read_text())


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_and_status(self):
        class Response:
            headers = {}
            def __init__(self, status): self.status = status
            async def text(self): return 'WEBVTT\n'
            async def dispose(self): pass
        class Context:
            def __init__(self): self.request = self; self.calls = 0
            async def get(self, *args, **kwargs):
                self.calls += 1
                return Response(503 if self.calls == 1 else 200)
        context = Context()
        self.assertEqual(await download(context, 'https://example.test', {}), 'WEBVTT\n')
        self.assertEqual(context.calls, 2)

    async def test_credentials_not_forwarded_cross_host(self):
        class Context:
            def on(self, *args): pass
        capture = Capture(Context())
        headers = await capture.headers_for('https://cdn.test/s.vtt', 'https://site.test/a.m3u8',
                                            {'authorization': 'private', 'cookie': 'private',
                                             'x-token': 'private', 'referer': 'https://site.test/'})
        self.assertEqual(headers, {'referer': 'https://site.test/'})


if __name__ == '__main__':
    unittest.main()
