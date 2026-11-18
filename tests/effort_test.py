# -*- coding: utf-8 -*-
"""A3: thinking strength."""
import importlib.util, json, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import attachment_test  # same throwaway server with a Codex that records its arguments

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_effort', SERVER); server = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(server)


class EffortArgs(unittest.TestCase):
    def test_each_cli(self):
        self.assertEqual(server.effort_args('codex', 'deep'), ['-c', 'model_reasoning_effort="high"'])
        self.assertEqual(server.effort_args('codex', 'fast'), ['-c', 'model_reasoning_effort="low"'])
        self.assertEqual(server.effort_args('claude', 'deep'), ['--effort', 'high'])
        self.assertEqual(server.effort_args('grok', 'fast'), ['--reasoning-effort', 'low'])
        for kind in ('codex', 'claude', 'grok', 'generic'): self.assertEqual(server.effort_args(kind, 'standard'), [])
        self.assertEqual(server.effort_args('generic', 'deep'), [])


class EffortChat(attachment_test.AttachmentTest):
    test_upload_send_and_read_back = test_limits = test_group_members_all_get_the_file = None

    def args(self): return (self.root / 'bin/codex.args').read_text().splitlines()

    def chat(self, **more):
        status, sent = self.req('POST', '/api/chat', dict({'botId': self.bot['id'], 'content': 'think'}, **more))
        if status != 202: return status, None
        return status, self.wait_job(sent['jobId'])

    def test_message_choice_and_bot_default(self):
        status, job = self.chat(effort='deep')
        self.assertIn('model_reasoning_effort="high"', self.args()); self.assertEqual(job['effort'], 'deep')
        self.assertEqual(next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])['messages'][-1]['effort'], 'deep')
        self.chat()
        self.assertFalse(any('reasoning_effort' in a for a in self.args()))  # 標準 leaves the CLI's own default
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bot['id'], {'effort': 'fast'})[0], 200)
        self.chat()
        self.assertIn('model_reasoning_effort="low"', self.args())
        self.chat(effort='standard')
        self.assertFalse(any('reasoning_effort' in a for a in self.args()))
        self.assertEqual(self.chat(effort='max')[0], 400)
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bot['id'], {'effort': 'max'})[0], 400)


if __name__ == '__main__': unittest.main()
