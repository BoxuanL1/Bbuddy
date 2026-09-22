"""Synthetic transport fixtures: no real school account or private inputs."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from blackboard_companion.captions.hls import SubtitleError
from blackboard_companion.online import caption_candidates, check_document, collect, fetch_document, read_plan
from blackboard_companion.storage import profile_dir


class Response:
    def __init__(self, status=200, data=b'%PDF-1.7\nfixture', mime='application/pdf'):
        self.status = status
        self.data = data
        self.headers = {'content-type': mime}
        self.disposed = False

    async def body(self):
        return self.data

    async def dispose(self):
        self.disposed = True


class Context:
    def __init__(self, responses):
        self.request = self
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class AcquisitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_and_response_cleanup(self):
        responses = [Response(503), Response()]
        context = Context(responses)
        with patch('blackboard_companion.online.asyncio.sleep', new=AsyncMock()):
            self.assertTrue((await fetch_document(context, 'https://school.test/file', 'pdf')).startswith(b'%PDF-'))
        self.assertTrue(all(response.disposed for response in responses))
        self.assertTrue(all(call['max_redirects'] == 0 for call in context.calls))

    async def test_auth_and_redirect_fail_without_retry(self):
        for status in (401, 403, 302):
            context = Context([Response(status)])
            with self.assertRaises(SubtitleError):
                await fetch_document(context, 'https://school.test/file', 'pdf')
            self.assertEqual(len(context.calls), 1)

    async def test_checkpoint_resume_and_corrupt_cache(self):
        items = [{'id': 'outline', 'kind': 'pdf', 'url': 'https://school.test/file?credential=SECRET'}]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            context = Context([Response(), Response()])
            first = await collect(context, items, output)
            self.assertEqual(first['stage'], 'acquired')
            await collect(context, items, output)
            self.assertEqual(len(context.calls), 1)
            (output / 'raw/outline.pdf').write_bytes(b'corrupt')
            await collect(context, items, output)
            self.assertEqual(len(context.calls), 2)
            self.assertNotIn('SECRET', (output / 'acquisition.json').read_text())

    async def test_failure_does_not_create_fake_document(self):
        items = [{'id': 'slides', 'kind': 'pdf', 'url': 'https://school.test/file'}]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = await collect(Context([Response(data=b'<html>login</html>', mime='text/html')]), items, output)
            self.assertEqual(result['stage'], 'failed')
            self.assertFalse((output / 'raw/slides.pdf').exists())


class SelectionTests(unittest.TestCase):
    def test_caption_candidates_do_not_mix_pages_or_assets(self):
        from types import SimpleNamespace
        page, unrelated = object(), object()
        first = 'https://cdn.test/captionAssetId/english/a.m3u8'
        second = 'https://cdn.test/captionAssetId/chinese/a.m3u8'
        other = 'https://cdn.test/captionAssetId/other/a.m3u8'
        direct = 'https://cdn.test/captionAssetId/english/1.vtt'
        capture = SimpleNamespace(
            candidates={first: ('#EXTM3U', {}), second: ('#EXTM3U', {}),
                        other: ('#EXTM3U', {}), direct: ('WEBVTT', {})},
            source_pages={first: page, second: page, other: unrelated, direct: page})
        self.assertEqual(len(caption_candidates(capture, page, None)), 2)
        self.assertEqual([item[0] for item in caption_candidates(capture, page, 'english')], [first])

    def test_profile_isolation(self):
        self.assertNotEqual(profile_dir('https://a.test', 'alice'), profile_dir('https://a.test', 'bob'))
        self.assertNotEqual(profile_dir('https://a.test', 'alice'), profile_dir('https://b.test', 'alice'))

    def test_unsafe_duplicate_and_reserved_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'selection.json'
            for identifiers in (['../escape'], ['CON'], ['one', 'ONE']):
                path.write_text(json.dumps({'resources': [
                    {'id': identifier, 'kind': 'pdf', 'url': 'https://school.test/file'}
                    for identifier in identifiers]}))
                with self.assertRaises(ValueError):
                    read_plan(path)

    def test_pptx_is_not_any_zip(self):
        for name in ('random.txt', 'ppt/presentation.xml'):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr(name, '<xml/>')
            if name == 'random.txt':
                with self.assertRaises(SubtitleError):
                    check_document(stream.getvalue(), 'pptx', 'application/octet-stream')
            else:
                check_document(stream.getvalue(), 'pptx', 'application/octet-stream')
