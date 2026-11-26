# -*- coding: utf-8 -*-
"""#306 (#13): a Skill written on the Skills page. It is stored in Zook's own Skill folder like a template, so every Bot and
every CLI gets it the same way; names that differ only in upper/lower case clash; it is text only (no programs)."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


class CustomSkills(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'home').mkdir()
        env = dict(os.environ, HOME=str(self.root / 'home'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SECRETS_DIR=str(self.root))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close(); return resp.status, json.loads(raw)

    def skill(self, name):
        return next((s for s in self.req('GET', '/api/integrations')[1]['skills'] if s['name'] == name), None)

    def test_add_and_edit_a_skill_every_bot_shares(self):
        status, made = self.req('POST', '/api/skills', {'name': '客服回覆', 'description': '依公司語氣回覆客戶問題。', 'body': '先道謝，再回答問題。'})
        self.assertEqual(status, 201)
        item = self.skill('客服回覆')
        self.assertEqual((item['source'], item['origin'], item['editable'], item['description']), ('zook', 'custom', True, '依公司語氣回覆客戶問題。'))
        self.assertNotIn(item['id'], self.req('GET', '/api/state')[1]['settings']['disabledSkills'])  # on for every Bot at once
        status, opened = self.req('GET', '/api/skills/' + made['id'])
        self.assertEqual((status, opened['name'], opened['description']), (200, '客服回覆', '依公司語氣回覆客戶問題。'))
        self.assertIn('先道謝，再回答問題。', opened['body'])
        self.assertEqual(self.req('PATCH', '/api/skills/' + made['id'], {'name': '客服回覆（正式）', 'description': '正式場合用。', 'body': '用敬語。'})[0], 200)
        self.assertIsNone(self.skill('客服回覆'))
        again = self.skill('客服回覆（正式）'); self.assertEqual((again['id'], again['description']), (item['id'], '正式場合用。'))
        text = (Path(again['path'])).read_text(encoding='utf-8')
        self.assertIn('name: 客服回覆（正式）', text); self.assertIn('用敬語。', text); self.assertNotIn('先道謝', text)
        self.assertEqual(sorted(p.name for p in Path(again['path']).parent.iterdir()), ['SKILL.md'])  # text only: nothing a Bot could run

    def test_a_template_can_be_edited_too(self):
        self.assertEqual(self.req('POST', '/api/skills/template', {'id': 'weekly-report'})[0], 201)
        item = self.skill('週報撰寫'); self.assertTrue(item['editable'])
        rid = item['id'].split(':', 1)[1]
        self.assertIn('本週重點', self.req('GET', '/api/skills/' + rid)[1]['body'])
        self.assertEqual(self.req('PATCH', '/api/skills/' + rid, {'name': '週報撰寫', 'description': '我的週報格式。', 'body': '三行就好。'})[0], 200)
        self.assertEqual(self.skill('週報撰寫')['description'], '我的週報格式。')

    def test_names_that_differ_only_in_case_clash(self):
        self.assertEqual(self.req('POST', '/api/skills', {'name': 'Report', 'description': 'd', 'body': 'b'})[0], 201)
        for name in ('report', '  REPORT ', 'rePort'):
            status, out = self.req('POST', '/api/skills', {'name': name, 'description': 'd', 'body': 'b'})
            self.assertEqual(status, 400, name); self.assertIn('同名', out['error'])
        self.assertEqual(self.req('POST', '/api/skills/template', {'id': 'meeting-notes'})[0], 201)
        self.assertEqual(self.req('POST', '/api/skills', {'name': '會議記錄整理', 'description': 'd', 'body': 'b'})[0], 400)
        status, other = self.req('POST', '/api/skills', {'name': 'Other', 'description': 'd', 'body': 'b'})
        self.assertEqual(self.req('PATCH', '/api/skills/' + other['id'], {'name': 'REPORT', 'description': 'd', 'body': 'b'})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/skills/' + other['id'], {'name': 'OTHER', 'description': 'd', 'body': 'b'})[0], 200)  # its own name in other case

    def test_bad_input_is_refused(self):
        good = {'name': 'Fine', 'description': 'd', 'body': 'b'}
        for change in ({'name': ''}, {'name': '  '}, {'name': 'a\nb'}, {'name': 'a---b'}, {'name': 'x' * 81}, {'name': 3},
                       {'description': ''}, {'description': 'a\nname: evil'}, {'description': 'x' * 501}, {'description': '---'},
                       {'body': ''}, {'body': '   '}, {'body': 'x' * 20001}, {'body': ['x']}):
            self.assertEqual(self.req('POST', '/api/skills', dict(good, **change))[0], 400, change)
        self.assertEqual(self.req('GET', '/api/integrations')[1]['skills'], [])
        self.assertEqual(self.req('PATCH', '/api/skills/nope', good)[0], 404)
        self.assertEqual(self.req('GET', '/api/skills/nope')[0], 404)

    def test_body_with_its_own_rules_line_stays_body(self):
        status, made = self.req('POST', '/api/skills', {'name': 'Fence', 'description': 'd', 'body': '---\nname: other\n---\n內容'})
        self.assertEqual(status, 201)
        self.assertEqual(self.skill('Fence')['description'], 'd')
        self.assertIn('name: other', self.req('GET', '/api/skills/' + made['id'])[1]['body'])

    def test_the_phone_cannot_write_skills(self):
        spec = importlib.util.spec_from_file_location('zook_custom_skills', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        for method, path in (('POST', '/api/skills'), ('PATCH', '/api/skills/abc'), ('GET', '/api/skills/abc')): self.assertFalse(z.device_may(method, path))


class EveryCliGetsIt(unittest.TestCase):
    """The same list every CLI's reply is given: the shared Skills of the inventory (shared_skill_ids), read through zook_read_skill."""
    def test_a_written_skill_is_in_the_shared_list(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / 'home'; home.mkdir(); old = os.environ.get('HOME'); os.environ['HOME'] = str(home)
            try:
                spec = importlib.util.spec_from_file_location('zook_custom_skills_cli', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
                store = z.Store(Path(temp) / 'data')
                record = z.custom_skill_add(store, {'name': '我的做法', 'description': '照我的方式做。', 'body': '一步一步來。'})
                inventory = z.inventory_for(store)
                ident = z.ZOOK_SKILL + record['id']
                self.assertIn(ident, z.shared_skill_ids(store, inventory))
                self.assertIn('一步一步來。', Path(inventory['_private']['skills'][ident]['path']).read_text(encoding='utf-8'))
            finally:
                if old is None: os.environ.pop('HOME', None)
                else: os.environ['HOME'] = old

    def test_saving_keeps_no_other_header_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = importlib.util.spec_from_file_location('zook_custom_skills_head', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
            store = z.Store(Path(temp) / 'data')
            record = z.custom_skill_add(store, {'name': 'Packed', 'description': 'd', 'body': 'b'})
            path = store.dir / 'skills' / record['folder'] / 'SKILL.md'
            path.write_text('---\nname: Packed\ndescription: d\nallowed-tools: Bash(*)\n---\n\n舊內容\n', encoding='utf-8')  # as a pack may bring it
            self.assertEqual(z.custom_skill_read(store, record['id'])['body'].strip(), '舊內容')
            z.custom_skill_edit(store, record['id'], {'name': 'Packed', 'description': 'd2', 'body': '新內容'})
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('allowed-tools', text); self.assertTrue(text.startswith('---\nname: Packed\ndescription: d2\n---\n'))

    def test_the_phone_does_not_sign_in_to_a_connector_that_is_off(self):
        spec = importlib.util.spec_from_file_location('zook_custom_skills_phone', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        self.assertFalse(z.device_may('POST', '/api/mcp/zook:abc/test'))  # testing (which may sign in to one that is off) is Mac only


if __name__ == '__main__': unittest.main()
