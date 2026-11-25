# -*- coding: utf-8 -*-
"""Group screen polish (#106, #130, #132, #223①).

#106: each 討論方式 says what it does in plain words, and 主持人分工 and 自動 say how they differ.
#130: the task board is steps, one card per task with its words one per line, and a 「下一步」 line says who has to act; an older
board (whose run is gone) is drawn as lines too, not one grey run of text.
#132: the member list marks the host, and the permission words are short (the long ones stay in the tooltip).
#223①: an empty group teaches what happens next, and in 自動 explains the task board, 「照這個做」 and the reply estimate."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'


def source(name): return (JS / name).read_text(encoding='utf-8')


def function(text, name):
    """The text of one top-level `function name(` up to the next function at the same indent."""
    start = text.index('function %s(' % name)
    nxt = re.search(r'\n  (?:async )?function |\n  const \w+ = ', text[start + 1:])
    return text[start:start + 1 + nxt.start() if nxt else None]


class ModeWords(unittest.TestCase):
    def test_split_and_auto_say_how_they_differ(self):
        groups, tasks = source('35-groups.js'), source('41-tasks.js')
        split = re.search(r"\{id: 'split', name: '主持人分工', hint: '([^']+)'\}", groups).group(1)
        auto = re.search(r"\{id: 'auto', name: '自動（主持人決定）', hint: '([^']+)'\}", tasks).group(1)
        self.assertIn('一輪', split)  # one pass, in the conversation
        self.assertIn('任務板', auto); self.assertIn('驗收', auto); self.assertIn('好幾輪', auto)
        for mode in ('free', 'turns', 'debate', 'compare'):
            hint = re.search(r"\{id: '%s', name: '[^']+', hint: '([^']+)'\}" % mode, groups).group(1)
            self.assertGreater(len(hint), 14, mode)  # a sentence, not two words

    def test_auto_estimate_is_explained(self):
        groups = source('35-groups.js')
        self.assertIn('預計至少', groups)  # 自動 has no upper bound: 「最多 N」 was wrong there
        self.assertIn('驗收和重做會再多', groups)


class TaskBoard(unittest.TestCase):
    def test_board_is_steps_with_a_next_step(self):
        tasks = source('41-tasks.js')
        board = function(tasks, 'taskBoardView')
        self.assertNotIn("detail.join(' · ')", board)  # each detail on its own line
        self.assertIn('taskStep(', board); self.assertIn('nextLine(taskNextStep(', board)
        self.assertIn('task-next', tasks); self.assertIn('task-step', tasks)
        nxt = function(tasks, 'taskNextStep')
        for words in ('照這個做', '接受結果', '重試', '你不用做什麼', '在下方再送一次訊息'):
            self.assertIn(words, nxt)
        self.assertIn('interrupted', nxt)  # a run Zook's restart cut short says so
        self.assertIn('已交出，等你看結果', tasks)  # #60's words stay

    def test_an_older_board_is_lines(self):
        tasks = source('41-tasks.js')
        self.assertNotIn("return `<div class=\"system-note\">${esc(m.content)}</div>`;  // an older board", tasks)
        old = function(tasks, 'oldBoardView')
        self.assertIn("split('\\n')", old); self.assertIn('taskStep(', old)

    def test_board_styles(self):
        css = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
        for cls in ('.task-next', '.task-step', '.task-num', '.task-acts'):
            self.assertIn(cls, css)


class MemberList(unittest.TestCase):
    def test_host_is_marked_and_permission_is_short(self):
        chat = source('10-chat.js')
        detail = function(chat, 'groupDetail')
        self.assertIn('主持人', detail)
        self.assertNotIn(', permText(b),', detail)  # the long sentence moved to the tooltip
        self.assertIn('title="${esc(permText(b))}"', detail); self.assertIn(', memberAccess(b),', detail)
        groups = source('35-groups.js')
        self.assertIn('危險動作先問你', groups)


class EmptyGroup(unittest.TestCase):
    def test_empty_group_teaches(self):
        chat, groups = source('10-chat.js'), source('35-groups.js')
        self.assertIn('groupEmptyView(g)', function(chat, 'groupChat'))
        view = function(groups, 'groupEmptyView')
        for words in ('任務板', '照這個做', '預計', '@'):
            self.assertIn(words, view)
        self.assertIn('.group-howto', (ROOT / 'frontend/style.css').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
