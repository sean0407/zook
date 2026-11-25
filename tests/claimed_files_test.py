# -*- coding: utf-8 -*-
"""#109: a member says it handed over a file that is not there. Zook says so to the user, and the others see it in their next turn."""
import importlib.util, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_claimed', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)


class Store:
    def __init__(self, root): self.dir = Path(root); self.data = {'bots': [], 'knowledge': [], 'memories': [], 'jobs': []}
    def find(self, kind, key): return next((x for x in self.data[kind] if x['id'] == key), None)


class ClaimedFiles(unittest.TestCase):
    def setUp(self):
        m._active['data'] = {'settings': {}, 'rules': []}
        self.temp = tempfile.TemporaryDirectory(); self.store = Store(self.temp.name)
        self.shared = m.group_files_dir(self.store, 'g1'); self.shared.mkdir(parents=True); (self.shared / '預算.xlsx').write_bytes(b'x')

    def tearDown(self): self.temp.cleanup()

    def missing(self, text, given=()): return m.claimed_missing(self.store, 'g1', 'b' * 32, text, set(given))

    def test_a_file_said_to_be_in_the_group_files_but_not_there(self):
        self.assertEqual(self.missing('已完成，檔案：報表.xlsx（群組檔案）'), ['報表.xlsx'])
        self.assertEqual(self.missing('已完成，檔案：預算.xlsx（群組檔案）'), [])  # it is there
        self.assertEqual(self.missing('讀了 名單.csv，結果放在群組檔案：預算.xlsx', given={'名單.csv'}), [])  # the user's own file was only read
        self.assertEqual(self.missing('已完成，檔案：報表.xlsx'), [])  # no claim about the group's files: nothing to check
        (self.shared / 'Q3 報表（專員）.XLSX').write_bytes(b'x')
        self.assertEqual(self.missing('已存到群組檔案：Q3 報表.xlsx、[預算.xlsx](u)'), [])  # a space in the name, Zook's second-version mark, case, brackets
        import time; began = time.time(); self.missing('已存到群組檔案 ' + 'a' * 20000 + '.xlsx'); self.assertLess(time.time() - began, 1)

    def test_a_full_path_that_does_not_exist(self):
        real = Path(self.temp.name) / 'out.pdf'; real.write_bytes(b'x')
        self.assertEqual(self.missing('存在 %s 和 %s/沒有.pdf' % (real, self.temp.name)), ['沒有.pdf'])
        self.assertEqual(self.missing('存在 /somewhere/預算.xlsx'), [])  # by its name it is among the group's files
        self.assertEqual(self.missing('找不到 /x/a.xlsx，請再給我一次'), [])  # it says it could not find one, not that it made one

    def test_the_others_see_it_in_their_next_turn(self):
        host = dict(id='h' * 32, name='主持人'); maker = dict(id='d' * 32, name='專員'); self.store.data['bots'] += [host, maker]
        group = dict(id='g1', name='行銷', botIds=[host['id'], maker['id']], messages=[dict(id='r1', role='assistant', botId=maker['id'], content='做好了 報表.xlsx（群組檔案）', missingFiles=['報表.xlsx'])])
        self.assertIn('Zook 檢查：這則回覆說交了 報表.xlsx，但實際上沒有存成', m.group_prompt(self.store, group, host, False))

    def test_the_turn_checks_and_tells_the_user(self):
        source = (Path(__file__).resolve().parents[1] / 'backend/zook/groups.py').read_text(encoding='utf-8')
        self.assertIn('claimed_missing(store, group_id, bot', source); self.assertIn('可能沒有存成功', source)


if __name__ == '__main__': unittest.main()
