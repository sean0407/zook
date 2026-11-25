# -*- coding: utf-8 -*-
"""#143/#153/#184②: the single-Bot chat, second round.
- 換模型重答 says 原本：X／這次：Y (with the model when the CLI reports it); used-up models are marked and go last.
- Attachments: a file gone from the disk is a 404, × deletes an unsent upload, uploads no message names are cleared after a day,
  a drafted file survives a reload, a renamed file is said, and a broken or empty file is said in plain words.
- The usage rings say 已用完 when the CLI has just reported the limit, like the Bot form does."""
import datetime, http.client, importlib.util, json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ROOT / 'frontend/js'
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)
GEMINI = "#!/usr/bin/env python3\nprint('gemini answered')\n"
CODEX = '''#!/usr/bin/env python3
import json, sys
sys.stdin.read()
for e in [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'codex answered'}},
          {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 2}}]: print(json.dumps(e))
'''


def run_node(code):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'h.js'; f.write_text(code, encoding='utf-8')
        out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    if out.returncode != 0: raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


class Live(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name, text in (('gemini', GEMINI), ('codex', CODEX)): cli = self.root / 'bin' / name; cli.write_text(text); cli.chmod(0o755)
        home = self.root / 'codex-home'; home.mkdir(); (home / 'config.toml').write_text('model = "gpt-test-9"\n')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', CODEX_HOME=str(home), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.env = env; self.start()
        self.bot = self.req('POST', '/api/bots', {'name': 'Tester', 'provider': 'gemini'})[1]

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path, body, dict({'Authorization': 'Bearer ' + self.token}, **(headers or {})))
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, data

    def req(self, method, path, body=None):
        status, data = self.raw(method, path, json.dumps(body).encode() if body is not None else None)
        return status, json.loads(data)

    def upload(self, name, data):
        status, out = self.raw('POST', '/api/uploads', data, {'X-File-Name': quote(name), 'Content-Type': 'application/octet-stream'})
        return json.loads(out)

    def wait(self, job_id):
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.2)
        self.fail('no reply')

    def messages(self):
        return next(b for b in self.req('GET', '/api/state?full=1')[1]['bots'] if b['id'] == self.bot['id'])['messages']

    def test_redo_says_who_answered_before_and_now(self):
        sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '週報是什麼'})[1]; self.wait(sent['jobId'])
        status, again = self.req('POST', '/api/chat/redo', {'botId': self.bot['id'], 'mode': 'again', 'provider': 'codex'})
        self.assertEqual(status, 202, again); self.wait(again['jobId'])
        last = self.messages()[-1]
        self.assertEqual(last['content'], 'codex answered')
        self.assertEqual(last['note'], '原本：Gemini／這次：Codex gpt-test-9')   # the model Codex ran, read once it answered

    def test_missing_file_is_404_and_x_deletes_unsent_uploads(self):
        kept, dropped, gone = self.upload('留著.txt', b'a'), self.upload('拿掉.txt', b'b'), self.upload('不見了.png', b'c')
        os.remove(self.root / 'data/uploads' / gone['id'] / 'file')
        self.assertEqual(self.raw('GET', '/api/uploads/' + gone['id'])[0], 404)              # not 500 「處理要求時發生錯誤」
        sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '看附件', 'attachments': [kept['id']]})[1]; self.wait(sent['jobId'])
        self.assertEqual(self.req('DELETE', '/api/uploads/' + dropped['id']), (200, {'removed': True}))
        self.assertFalse((self.root / 'data/uploads' / dropped['id']).exists())
        self.assertEqual(self.req('DELETE', '/api/uploads/' + kept['id']), (200, {'removed': False}))   # a sent message still uses it
        self.assertTrue((self.root / 'data/uploads' / kept['id'] / 'file').exists())

    def test_renamed_name_is_returned(self):
        self.assertEqual(self.upload('a:b.txt', b'x')['name'], 'ab.txt')   # the page compares it with what it sent and says so

    def test_old_uploads_no_message_names_are_cleared(self):
        kept, old, fresh = self.upload('留著.txt', b'a'), self.upload('舊的.txt', b'b'), self.upload('新的.txt', b'c')
        sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '看附件', 'attachments': [kept['id']]})[1]; self.wait(sent['jobId'])
        self.stop()
        day_ago = time.time() - 2 * 86400
        for u in (kept, old): os.utime(self.root / 'data/uploads' / u['id'], (day_ago, day_ago))
        self.start()  # the sweep runs when Zook starts
        self.req('GET', '/api/state')  # answered once the start-up work is done
        end = time.time() + 5
        while (self.root / 'data/uploads' / old['id']).exists() and time.time() < end: time.sleep(0.1)
        self.assertTrue((self.root / 'data/uploads' / kept['id']).exists())
        self.assertFalse((self.root / 'data/uploads' / old['id']).exists())
        self.assertTrue((self.root / 'data/uploads' / fresh['id']).exists())   # a draft from today stays


def load_server(name):
    spec = importlib.util.spec_from_file_location(name, SERVER)
    m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)
    return m


class UploadSweep(unittest.TestCase):
    def setUp(self):
        self.m = load_server('zook_server_for_upload_sweep'); self.temp = tempfile.TemporaryDirectory()
        self.store = self.m.Store(Path(self.temp.name) / 'data')

    def tearDown(self): self.temp.cleanup()

    def make(self, uid, old=True):
        folder = self.store.dir / 'uploads' / uid; folder.mkdir(parents=True)
        (folder / 'file').write_bytes(b'x'); (folder / 'meta.json').write_text(json.dumps({'id': uid, 'name': 'a.txt'}))
        if old: t = time.time() - 2 * 86400; os.utime(folder, (t, t))
        return folder

    def test_uploads_still_named_anywhere_stay(self):
        ids = {k: k[0] * 32 for k in ('a', 'b', 'c', 'd')}  # queued, deleted Bot, group message, nothing
        bot = self.store.data['bots'][0]; bot['queue'] = [{'id': 'q', 'content': 'x', 'attachments': [ids['a']]}]
        self.store.data['deletedBots'] = [{'id': 'gone', 'name': '舊', 'messages': [{'role': 'user', 'attachments': [{'id': ids['b']}]}]}]
        self.store.data.setdefault('groups', []).append({'id': 'g', 'messages': [{'role': 'user', 'attachments': [{'id': ids['c']}]}]})
        folders = {k: self.make(v) for k, v in ids.items()}
        self.assertEqual(self.m.sweep_uploads(self.store, force=True), 1)
        self.assertEqual({k: f.exists() for k, f in folders.items()}, {'a': True, 'b': True, 'c': True, 'd': False})
        for k in ('a', 'b', 'c'): self.assertFalse(self.m.upload_drop(self.store, ids[k]))

    def test_nothing_is_deleted_through_a_linked_uploads_folder(self):
        elsewhere = Path(self.temp.name) / 'elsewhere' / ('e' * 32); elsewhere.mkdir(parents=True)
        (elsewhere / 'file').write_bytes(b'keep'); (elsewhere / 'meta.json').write_text(json.dumps({'id': 'e' * 32, 'name': 'a'}))
        t = time.time() - 2 * 86400; os.utime(elsewhere, (t, t))
        self.store.dir.mkdir(parents=True, exist_ok=True); (self.store.dir / 'uploads').symlink_to(elsewhere.parent)
        self.assertEqual(self.m.sweep_uploads(self.store, force=True), 0)
        self.assertFalse(self.m.upload_drop(self.store, 'e' * 32))
        self.assertTrue((elsewhere / 'file').exists())


class Rings(unittest.TestCase):
    def test_ring_is_empty_when_the_limit_was_just_reached(self):
        spec = importlib.util.spec_from_file_location('zook_server_for_polish_rings', SERVER)
        m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            store = m.Store(Path(d) / 'data')
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            store.data['quota'] = {'grok': {'updatedAt': now, 'limitReached': 'usage_limit_reached', 'windows': [{'label': '每週', 'usedPercent': 0}]},
                                   'codex': {'updatedAt': now, 'windows': [{'label': '每週', 'usedPercent': 30}]}}
            rings = {r['id']: r for r in m.usage_rings(store)}
        self.assertEqual((rings['grok']['left'], rings['grok']['week'], rings['grok']['out']), (0.0, 0.0, True))
        self.assertEqual((rings['codex']['left'], rings['codex']['out']), (70.0, False))


REDO = r"""
const document = {addEventListener() {}};
const state = {data: {settings: {provider: 'codex', model: ''}}, quota: {providers: [
  {id: 'codex', quota: {windows: [{usedPercent: 20}]}}, {id: 'grok', quota: {limitReached: 'usage_limit_reached', updatedAt: new Date().toISOString(), windows: []}},
  {id: 'antigravity', quota: {windows: [{usedPercent: 10}]}}]},
  providers: [{id: 'grok', name: 'Grok'}, {id: 'antigravity', name: 'Antigravity'}, {id: 'codex', name: 'Codex（OpenAI）'}, {id: 'cursor', name: 'Cursor', installed: false}]};
const esc = s => String(s);
__CODE__
const opts = redoModelOptions({provider: 'antigravity'});
console.log(JSON.stringify({ids: opts.map(o => o.id), names: opts.map(o => o.name), hints: opts.map(o => o.hint),
  pick: (opts.find(o => !o.current && !o.out) || {}).id, line: redoModelLine('antigravity'), dflt: (state.data.settings.model = 'gpt-9', redoModelLine('codex'))}));
"""

PENDING = r"""
const store = {};
const sessionStorage = {getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; }, removeItem: k => { delete store[k]; }};
const document = {addEventListener() {}}, deleted = [];
const api = (path, o) => { deleted.push([path, o && o.method]); return Promise.resolve({}); };
const state = {selected: 'b1', data: {bots: [{id: 'b1', chatId: 'c1'}]}};
const activeGroup = () => null, effortKey = () => 'b1', esc = s => String(s), render = () => {}, toast = () => {};
__CODE__
pendingList().push({key: 'k1', id: 'a'.repeat(32), name: '報告.pdf', size: 10, kind: 'file', uploading: false, url: ''},
                   {key: 'k2', id: 'b'.repeat(32), name: '圖.png', size: 5, kind: 'image', uploading: false, url: 'blob:x'},
                   {key: 'k3', name: '上傳中.txt', size: 1, uploading: true});
keepPending();
state.pendingBy = restorePending();
const back = pendingList().map(f => [f.name, f.url]);
dropPending('k1');
setTimeout(() => console.log(JSON.stringify({back, after: pendingList().map(f => f.name), deleted, kept: JSON.parse(store['zook-pending-files'])})), 10);
"""

PREVIEW = r"""
const esc = s => String(s), markdown = s => s, pdfFrame = (u) => 'PDF:' + u;
class Blob { constructor(parts) { this.data = parts.join(''); this.size = this.data.length; } slice(a, b) { return new Blob([this.data.slice(a, b)]); } async text() { return this.data; } }
const files = {'/gone': null, '/empty': '', '/fake.pdf': 'not a pdf', '/real.pdf': '%PDF-1.7 ...', '/bad.png': 'xx', '/a.txt': 'hello'};
const fetch = async url => files[url] === null ? {ok: false, status: 404, json: async () => ({})} : {ok: true, status: 200, blob: async () => new Blob([files[url]])};
const URL = {createObjectURL: b => 'blob:' + b.data};
class Image { set src(v) { setTimeout(() => v === 'blob:xx' ? this.onerror() : (this.naturalWidth = 1, this.onload()), 0); } }
__CODE__
(async () => {
  const out = {};
  for (const [u, k] of [['/gone', 'image'], ['/empty', 'text'], ['/fake.pdf', 'pdf'], ['/real.pdf', 'pdf'], ['/bad.png', 'image'], ['/a.txt', 'text']]) out[u] = await previewBody(u, k, 'x');
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(NODE, 'needs node to run the page code')
class Page(unittest.TestCase):
    def test_redo_choices_mark_used_up_models(self):
        cards = (JS / '32b-cards.js').read_text(encoding='utf-8'); models = (JS / '20-models.js').read_text(encoding='utf-8')
        helpers = models[models.index('const quotaFor'):models.index('function botUsageSection')] + cards[cards.index('const cliShort'):cards.index('function quotaWarnText')]
        helpers = helpers.replace('fmtReset(', '(x => x)(').replace('resetClock(', '(x => x)(')
        out = run_node(REDO.replace('__CODE__', helpers + 'const windowLeft = w => 100 - w.usedPercent;\n' + (JS / '40b-redo.js').read_text(encoding='utf-8')))
        self.assertEqual(out['ids'], ['antigravity', 'codex', 'grok'])                      # used up last; not installed left out
        self.assertEqual(out['names'], ['Antigravity', 'Codex', 'Grok（已用完）'])
        self.assertIn('這個 Bot 目前用的', out['hints'][0]); self.assertIn('已用完', out['hints'][2])
        self.assertEqual(out['pick'], 'codex')                                               # not the Bot's own, not a used-up one
        self.assertIn('Antigravity 預設的型號', out['line']); self.assertEqual(out['dflt'], '用 Codex 的 gpt-9 回答')

    def test_drafted_files_survive_a_reload_and_x_deletes(self):
        pages = (JS / '30-pages.js').read_text(encoding='utf-8')
        out = run_node(PENDING.replace('__CODE__', pages[:pages.index('  function pendingFiles()')]))
        self.assertEqual(out['back'], [['報告.pdf', ''], ['圖.png', '/api/uploads/' + 'b' * 32]])   # the one still uploading is not kept
        self.assertEqual(out['after'], ['圖.png'])
        self.assertEqual(out['deleted'], [['uploads/' + 'a' * 32, 'DELETE']])
        self.assertEqual([f['name'] for f in out['kept']['b1:c1']], ['圖.png'])

    def test_preview_says_gone_empty_and_broken(self):
        outputs = (JS / '36-outputs.js').read_text(encoding='utf-8')
        code = outputs[outputs.index('  const UNREADABLE'):outputs.index('  async function openOutput')]
        out = run_node(PREVIEW.replace('__CODE__', code))
        self.assertTrue(out['/gone']['missing']); self.assertIn('找不到這個檔案', out['/gone']['body'])
        self.assertIn('是空的', out['/empty']['body'])
        for broken in ('/fake.pdf', '/bad.png'): self.assertIn('這個檔案打不開', out[broken]['body']); self.assertFalse(out[broken].get('missing'))
        self.assertEqual(out['/real.pdf']['body'], 'PDF:/real.pdf')
        self.assertIn('hello', out['/a.txt']['body'])


if __name__ == '__main__':
    unittest.main()
