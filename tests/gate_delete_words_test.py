# -*- coding: utf-8 -*-
"""#54①: an approval card names what is really deleted: 2>/dev/null is not a file called 「2」, and a variable is shown as a
variable, never glued to the folder the command runs in. Deleting is still asked about, scratch files too (an earlier security
review asked for that; changing it is the user's call, see loop/decisions.md)."""
import os, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import zook_gate as g  # noqa: E402


def deletes(command): return [t for k, t in g.command_boundaries(command) if k == 'delete']


class DeleteWords(unittest.TestCase):
    def setUp(self): self.cwd = g._CWD[0]; g._CWD[0] = '/Users/someone/work'

    def tearDown(self): g._CWD[0] = self.cwd

    def test_an_output_stream_is_not_a_file(self):
        said = deletes('rm -f a.txt 2>/dev/null; echo ok')
        self.assertEqual(len(said), 1); self.assertIn('work/a.txt', said[0]); self.assertNotIn('/2', said[0]); self.assertNotIn('、', said[0])
        self.assertEqual(deletes('rm -f a.txt 2> /dev/null'), deletes('rm -f a.txt'))
        self.assertIn('work/2', deletes('rm 2 > out')[0]); self.assertIn('work/5', deletes('rm 5 </dev/null')[0])  # with a space it is a file called 2

    def test_a_variable_reads_as_a_variable(self):
        said = deletes('rm -rf "$OUT/x"')
        self.assertEqual(len(said), 1); self.assertIn('「x」（位置由指令裡的變數決定）', said[0]); self.assertNotIn('$', said[0])  # #234: said plainly, no $; self.assertNotIn('/Users/someone/work/$', said[0])

    def test_deleting_is_still_asked_about(self):  # scratch files too: an earlier security review asked for that (gate_test)
        for command in ('rm -rf /tmp/x', 'd=$(mktemp -d); rm -rf "$d"', 'rm -f /tmp/x ~/報告.xlsx'):
            self.assertTrue(deletes(command), command)

if __name__ == '__main__': unittest.main()
