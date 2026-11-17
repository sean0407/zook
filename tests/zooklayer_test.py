import base64
import http.client
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
MCP = r'''
import json, os, sys
for line in sys.stdin:
    m = json.loads(line)
    if 'id' not in m: continue
    if m['method'] == 'initialize': r = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 'fake', 'version': '1'}}
    elif m['method'] == 'tools/list': r = {'tools': [{'name': 'keys_%s_%s_%s' % (os.environ.get('FAKE_TOKEN', 'none')[-1], os.environ.get('OTHER_SECRET', 'none')[-1], os.environ.get('MODE', 'none')), 'description': 'x', 'inputSchema': {'type': 'object'}}]}
    else: r = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': r})); sys.stdout.flush()
'''


def skill(folder, name, body='Do the thing.'):
    folder.mkdir(parents=True); (folder / 'SKILL.md').write_text('---\nname: %s\ndescription: about %s\n---\n%s\n' % (name, name, body))


class ZookLayerTest(unittest.TestCase):
    """Skills and connectors that live in other tools can be brought into Zook, and moved to another Mac as one file."""
    def start(self, name):
        root = self.root / name; (root / 'home').mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, HOME=str(root / 'home'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(root))
        proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(root / 'data'), '--assets', str(self.root / 'assets')],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(proc.stdout.readline()); self.procs.append(proc)
        return ready['port'], ready['token']

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.procs = []
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'mcp.py').write_text(MCP)
        home = self.root / 'one/home'; home.mkdir(parents=True)
        skill(home / '.claude/skills/report', 'weekly-report', 'Use mcp__claude_ai_Gmail__create_draft, mcp__Notion__search and mcp__fake__keys, then AskUserQuestion.')
        (home / '.claude/skills/report/helper.py').write_text('print(1)')
        (home / '.claude/skills/report/node_modules').mkdir(); (home / '.claude/skills/report/node_modules/x.js').write_text('x')
        skill(home / '.codex/skills/report', 'Weekly-Report'); skill(home / '.codex/skills/other', 'other-skill')
        (home / '.claude.json').write_text(json.dumps({'mcpServers': {
            'fake': {'command': sys.executable, 'args': [str(self.root / 'mcp.py')], 'env': {'FAKE_TOKEN': 'token-value-1', 'OTHER_SECRET': 'secret-value-2', 'MODE': 'copied'}},
            'basic': {'type': 'http', 'url': 'https://example.com/mcp', 'headers': {'Authorization': 'Basic abcdefgh'}}}}))
        self.one = self.start('one')

    def tearDown(self):
        for proc in self.procs:
            proc.terminate(); proc.wait(timeout=5); proc.stdout.close(); proc.stderr.close()
        self.temp.cleanup()

    def req(self, server, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', server[0], timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + server[1]})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def skills(self, server=None): return self.req(server or self.one, 'GET', '/api/integrations')[1]['skills']
    def connectors(self, server=None): return self.req(server or self.one, 'GET', '/api/integrations')[1]['mcp']

    def test_import_copy_and_move(self):
        before = self.skills()
        report = next(s for s in before if s['name'] == 'weekly-report')
        self.assertEqual(len(report['notes']), 3)  # one connector Zook lacks, two that are off, and a Claude-only tool
        self.assertIn('Notion', report['notes'][0]); self.assertNotIn('fake', report['notes'][0])
        self.assertIn('Gmail', report['notes'][1]); self.assertIn('fake', report['notes'][1]); self.assertIn('AskUserQuestion', report['notes'][2])
        self.req(self.one, 'PATCH', '/api/settings', {'disabledSkills': [next(s['id'] for s in before if s['name'] == 'other-skill')]})

        status, made = self.req(self.one, 'POST', '/api/skills/import', {'ids': [s['id'] for s in before]})
        self.assertEqual((status, sorted(made['imported']), made['failed']), (200, ['other-skill', 'weekly-report'], []))
        self.assertEqual(len(made['skipped']), 1)  # the same Skill under another tool is kept once
        after = self.skills(); mine = [s for s in after if s['source'] == 'zook']
        self.assertEqual(len(mine), 2); self.assertTrue(all(s.get('imported') for s in after if s['source'] != 'zook'))
        data = self.root / 'one/data'
        folder = next(p for p in (data / 'skills').iterdir() if (p / 'helper.py').is_file())
        self.assertFalse((folder / 'node_modules').exists())
        state = self.req(self.one, 'GET', '/api/state')[1]
        self.assertIn(next(s['id'] for s in mine if s['name'] == 'other-skill'), state['settings']['disabledSkills'])  # stayed off
        self.assertEqual(self.req(self.one, 'POST', '/api/skills/import', {'ids': [s['id'] for s in before]})[1]['imported'], [])

        # The original changes later: Zook offers to refresh its copy.
        report = next(s for s in mine if s['name'] == 'weekly-report'); self.assertFalse(report['canUpdate'])
        (self.root / 'one/home/.claude/skills/report/SKILL.md').write_text('---\nname: weekly-report\ndescription: newer\n---\nx\n')
        self.assertTrue(next(s for s in self.skills() if s['id'] == report['id'])['canUpdate'])
        self.assertEqual(self.req(self.one, 'POST', '/api/skills/%s/update' % report['id'].split(':')[1], {})[0], 200)
        fresh = next(s for s in self.skills() if s['id'] == report['id'])
        self.assertEqual((fresh['description'], fresh['canUpdate']), ('newer', False))

        # Connectors: one copies with both of its keys, one uses sign-in Zook cannot carry.
        fake, basic = (next(m for m in self.connectors() if m['name'] == n) for n in ('fake', 'basic'))
        self.assertTrue(fake['copyable'])
        self.req(self.one, 'PATCH', '/api/settings', {'sharedMcp': [fake['id']]})
        self.assertEqual(self.req(self.one, 'POST', '/api/connector-copy', {'id': basic['id']})[0], 400)
        status, copy = self.req(self.one, 'POST', '/api/connector-copy', {'id': fake['id']})
        self.assertEqual((status, copy['on']), (201, True))
        self.assertEqual(self.req(self.one, 'POST', '/api/connector-copy', {'id': fake['id']})[0], 404)
        state = self.req(self.one, 'GET', '/api/state')[1]
        self.assertEqual(state['settings']['sharedMcp'], [copy['id']])
        listed = self.connectors(); self.assertTrue(next(m for m in listed if m['id'] == fake['id'])['copied'])
        mine = next(m for m in listed if m['id'] == copy['id'])
        self.assertEqual((mine['config']['env'], mine['config']['secretName'], mine['config']['moreSecrets'], mine['needsKey']), ({'MODE': 'copied'}, 'FAKE_TOKEN', [{'name': 'OTHER_SECRET', 'saved': True}], False))
        everything = json.dumps(state) + json.dumps(listed) + (data / 'swarmr.json').read_text()
        self.assertNotIn('token-value-1', everything); self.assertNotIn('secret-value-2', everything)
        self.assertEqual(self.req(self.one, 'POST', '/api/mcp/' + copy['id'] + '/test', {})[1]['tools'][0]['name'], 'keys_1_2_copied')

        # Move everything to another Mac: Skills arrive, connectors arrive without their keys and wait for them.
        status, pack = self.req(self.one, 'GET', '/api/pack')
        self.assertEqual((status, pack['skills'], pack['connectors']), (200, 2, 1))
        raw = base64.b64decode(pack['data'])
        self.assertNotIn(b'token-value-1', raw); self.assertNotIn(b'secret-value-2', raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as z: self.assertNotIn(b'token-value-1', b''.join(z.read(n) for n in z.namelist()))
        two = self.start('two')
        status, result = self.req(two, 'POST', '/api/pack', {'data': pack['data']})
        self.assertEqual((status, sorted(result['skills']), result['connectors'], result['needKeys'], result['skipped']), (200, ['other-skill', 'weekly-report'], ['fake'], ['fake'], []))
        moved = self.skills(two)
        self.assertEqual(sorted(s['name'] for s in moved), ['other-skill', 'weekly-report'])
        self.assertIn(next(s['id'] for s in moved if s['name'] == 'other-skill'), self.req(two, 'GET', '/api/state')[1]['settings']['disabledSkills'])
        arrived = next(m for m in self.connectors(two) if m['source'] == 'zook')
        self.assertTrue(arrived['needsKey']); self.assertEqual(self.req(two, 'GET', '/api/state')[1]['settings'].get('sharedMcp') or [], [])
        ident = arrived['id'].split(':')[1]
        self.assertEqual(self.req(two, 'PATCH', '/api/connectors/' + ident, {'secret': 'token-value-9', 'moreSecrets': {'OTHER_SECRET': 'secret-value-9', 'NOT_MINE': 'zzzzzzzzzz'}})[0], 200)
        self.assertFalse(next(m for m in self.connectors(two) if m['id'] == arrived['id'])['needsKey'])
        self.assertEqual(self.req(two, 'POST', '/api/mcp/' + arrived['id'] + '/test', {})[1]['tools'][0]['name'], 'keys_9_9_copied')
        self.assertEqual(self.req(two, 'POST', '/api/pack', {'data': pack['data']})[1]['skills'], [])  # importing twice adds nothing

        # Removing Zook's copy brings the original back.
        self.assertEqual(self.req(self.one, 'DELETE', '/api/skills/' + report['id'].split(':')[1])[0], 200)
        self.assertFalse(next(s for s in self.skills() if s['name'] == 'weekly-report' and s['source'] == 'claude').get('imported'))

    def test_pack_rejects_unsafe_files(self):
        def pack(files, manifest=None):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as z:
                z.writestr('zook.json', json.dumps(manifest or {'format': 'zook-pack', 'version': 1, 'skills': [{'name': 'evil', 'folder': 'evil'}], 'connectors': []}))
                for name, content in files.items(): z.writestr(name, content)
            return {'data': base64.b64encode(buffer.getvalue()).decode()}
        self.assertEqual(self.req(self.one, 'POST', '/api/pack', {'data': base64.b64encode(b'not a zip').decode()})[0], 400)
        self.assertEqual(self.req(self.one, 'POST', '/api/pack', pack({}, {'format': 'other'}))[0], 400)
        self.assertEqual(self.req(self.one, 'POST', '/api/pack', pack({}, {'format': 'zook-pack', 'version': 2, 'skills': [], 'connectors': []}))[0], 400)
        for files in ({'skills/evil/SKILL.md': 'x', 'skills/evil/../../escape.txt': 'x'}, {'skills/evil/readme.txt': 'no skill file'}):
            status, result = self.req(self.one, 'POST', '/api/pack', pack(files))
            self.assertEqual((status, result['skills'], result['skipped']), (200, [], ['evil']), files)
        self.assertFalse((self.root / 'one/data/escape.txt').exists()); self.assertFalse((self.root / 'one/escape.txt').exists())
        self.assertEqual([p.name for p in (self.root / 'one/data/skills').iterdir()], [])
        bad = {'format': 'zook-pack', 'version': 1, 'skills': [], 'connectors': [{'name': 'x', 'transport': 'http', 'url': 'https://example.com/mcp', 'headers': {'Authorization': 'Bearer abc'}}]}
        self.assertEqual(self.req(self.one, 'POST', '/api/pack', pack({}, bad))[1], {'skills': [], 'connectors': [], 'skipped': ['x'], 'needKeys': []})


if __name__ == '__main__':
    unittest.main()
