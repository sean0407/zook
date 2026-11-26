# -*- coding: utf-8 -*-
"""#331 #249: preview pictures and other scratch files a Bot made in its own scratch folder (the one Zook made, #261) are cleared by
Zook when the reply ends, without an approval card, under the same rules as zook_clean_scratch: plain files right in that folder, made
during this reply, never a link, a folder or a hard link, never when the folder is not the one Zook made. A shell rm is still asked."""
import os, sys, time, types, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gate_scratch_test import Base, ROOT, g, scratch_module  # noqa: E402


class Sweep(Base):
    def setUp(self):
        super().setUp(); self.logged = []; self.ns = scratch_module(self.logged)

    def sweep(self, since=None):
        return self.ns['scratch_sweep'](object(), {'name': '小幫手'}, (self.scratch, self.ident, time.time() - 2 if since is None else since))

    def test_files_of_this_reply_are_cleared_and_said_once(self):
        a, b = self.fresh(name='p1.png'), self.fresh(name='頁 2.png')
        self.assertEqual(sorted(self.sweep()), ['p1.png', '頁 2.png'])
        self.assertFalse(os.path.exists(a) or os.path.exists(b))
        self.assertEqual(len(self.logged), 1); self.assertIn('小幫手', self.logged[0][1])
        self.assertEqual(self.sweep(), []); self.assertEqual(len(self.logged), 1)  # nothing left: nothing said

    def test_what_is_not_the_bots_own_is_kept(self):
        user = self.fresh(self.ws, 'user.txt')
        old = self.fresh(name='old.png'); t = time.time() - 3600; os.utime(old, (t, t))
        moved = self.fresh(self.ws, 'report.docx'); os.utime(moved, (t, t)); os.rename(moved, os.path.join(self.scratch, 'report.docx'))
        os.symlink(user, os.path.join(self.scratch, 'link.png'))
        os.mkdir(os.path.join(self.scratch, 'sub')); inner = self.fresh(os.path.join(self.scratch, 'sub'), 'inner.png')
        os.link(user, os.path.join(self.scratch, 'hard.png'))
        hidden = self.fresh(name='.keep')
        self.assertEqual(self.sweep(time.time() - 1800), [])
        for p in (user, old, os.path.join(self.scratch, 'report.docx'), inner, os.path.join(self.scratch, 'hard.png'), hidden):
            self.assertTrue(os.path.exists(p), p)
        self.assertTrue(os.path.lexists(os.path.join(self.scratch, 'link.png')))

    def test_a_replaced_folder_is_left_alone(self):
        p = self.fresh(name='a.png')
        os.rename(self.scratch, self.scratch + '-away'); os.mkdir(self.scratch); q = self.fresh(name='a.png')
        self.assertEqual(self.sweep(), [])
        self.assertTrue(os.path.exists(q) and os.path.exists(self.scratch + '-away/a.png'))
        self.assertEqual(self.ns['scratch_sweep'](object(), {'name': 'B'}, None), [])

    def test_many_files_are_all_cleared(self):
        for i in range(120): self.fresh(name='p%03d.png' % i)
        self.assertEqual(len(self.sweep()), 120); self.assertEqual(os.listdir(self.scratch), [])

    def test_a_shell_rm_there_is_still_asked(self):
        self.asked('rm %s/p1.png' % self.scratch)

    def test_the_notes_say_zook_clears_it(self):
        note = self.ns['scratch_note']((self.scratch, self.ident, 0))
        self.assertIn('Zook 會', note); self.assertIn('預覽圖', note); self.assertIn('不要用 rm', note)
        core = (ROOT / 'backend/zook/core.py').read_text(encoding='utf-8')
        rule = core[core.index('暫存程式和預覽圖'):core.index('用指令寫文字檔時')]
        self.assertIn('Zook 給你的暫存資料夾', rule); self.assertIn('不用自己刪', rule)
        runtime = types.SimpleNamespace(_schema=lambda name, desc, props, req=(), ro=True: {'name': name})
        [(schema, run, need)] = self.ns['scratch_tools'](object(), {'name': 'B'}, runtime, (self.scratch, self.ident, time.time() - 2))
        self.fresh(name='a.py'); self.assertEqual(run({'names': ['a.py']}), {'deleted': ['a.py']})

    def test_the_reply_end_sweeps_only_when_the_bot_is_free(self):
        app = (ROOT / 'backend/zook/app.py').read_text(encoding='utf-8')
        self.assertRegex(app, r"if not busy and locals\(\)\.get\('scratch'\): scratch_sweep\(store, bot, scratch\)")


if __name__ == '__main__': unittest.main()
