"""Notification deferral must preserve text before clicking."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from blackboard_companion.adapters.blackboard import defer_notifications


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_before_dismissal(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            class Control:
                async def is_visible(self):
                    return True

                async def evaluate(self, script):
                    return {'text': 'Quiz announcement\nRemind me later', 'scope': 'dialog'}

                async def click(self, **kwargs):
                    files = list(output.glob('*.json'))
                    assert len(files) == 1
                    record = json.loads(files[0].read_text())
                    assert record['text'].startswith('Quiz announcement')
                    assert record['dismissed'] is False

            class Controls:
                async def count(self):
                    return 1

                def nth(self, index):
                    return Control()

            frame = SimpleNamespace(url='https://school.test/course',
                                    get_by_text=lambda *args, **kwargs: Controls())
            context = SimpleNamespace(pages=[SimpleNamespace(url=frame.url, frames=[frame])])
            records = await defer_notifications(context, output)
            self.assertTrue(records[0]['dismissed'])
            self.assertTrue(json.loads(next(output.glob('*.json')).read_text())['dismissed'])
            with patch('blackboard_companion.adapters.blackboard.write_json', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    await defer_notifications(context, output)
