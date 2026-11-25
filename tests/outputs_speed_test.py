# -*- coding: utf-8 -*-
"""#107/#161: 產出 never hangs. At most a few reply streams are open (the browser keeps only about six connections to Zook, so
more would queue every other request); streams of replies not on screen are closed; the panel gives up after 20 seconds with a
way to try again; and the server answers within a few seconds with what it found by then."""
import importlib.util, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zook_outputs_speed', ROOT / 'backend/server.py'); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT / 'backend')); spec.loader.exec_module(m)


class OutputsSpeed(unittest.TestCase):
    def test_the_page_keeps_connections_free(self):
        stream = (ROOT / 'frontend/js/37-stream.js').read_text(encoding='utf-8')
        self.assertIn('STREAM_MOST = 3', stream); self.assertIn('Object.keys(streams).length >= STREAM_MOST', stream)
        self.assertIn('if (!onScreen(state.jobDetails[id] || streams[id].job))', stream)  # a reply no longer on screen lets go of its connection
        self.assertIn('function pollPartial', stream)  # and its words still come, by polling
        pages = (ROOT / 'frontend/js/30-pages.js').read_text(encoding='utf-8') + (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8')
        self.assertEqual(pages.count('pollPartial(j)'), 2)
        panel = (ROOT / 'frontend/js/36-outputs.js').read_text(encoding='utf-8')
        self.assertIn('stop.abort(), 20000', panel); self.assertIn('產出讀取太久', panel)

    def test_the_server_answers_in_time(self):
        with tempfile.TemporaryDirectory() as root:
            store = m.Store(Path(root) / 'data'); m._active['data'] = store.data
            bot = dict(id='b' * 32, name='小幫', access='full'); store.data['bots'].append(bot)
            work = store.dir / 'workspaces' / bot['id']; work.mkdir(parents=True); (work / 'a.txt').write_text('x')
            self.assertEqual([o['name'] for o in m.bot_outputs(store, bot)], ['a.txt'])
            keep = m.OUTPUT_SECONDS
            try:
                m.OUTPUT_SECONDS = -1  # already past: nothing is scanned, and it still answers
                self.assertEqual(m.bot_outputs(store, bot), [])
            finally: m.OUTPUT_SECONDS = keep


if __name__ == '__main__': unittest.main()
