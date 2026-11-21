#!/usr/bin/env python3
"""One fixed piece of group work, timed: how long it takes, how many model requests it makes and how many tokens they use.
Runs on a throwaway Zook with real CLIs (uses a little quota). Compares the group modes, e.g. 分工 against the task engine.

    python3 scripts/task_bench.py --mode split [--save docs/0.17-bench-split.json]
    python3 scripts/task_bench.py --mode auto  [--save …]   (turns 任務引擎 on in the throwaway Zook)
"""
import argparse, json, os, pathlib, sys, tempfile, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import acceptance as acc

TOPIC = ('請大家分工完成，最後交給我一份整理好的結果：\n'
         '1. 列出台北 3 個適合下雨天的室內景點，各一句理由。\n'
         '2. 寫一段 50 字以內的週末出遊邀請文案。\n'
         '3. 估算 4 個人一天搭台北捷運的交通費（每人來回 4 段，每段 25 元）。')


def run(mode, port, keep):
    folder = pathlib.Path(tempfile.mkdtemp(prefix='zook-bench-'))
    z = acc.Zook(folder, port)
    try:
        z.req('PATCH', 'settings', dict(permissionMode='auto', **({'taskEngine': True} if mode == 'auto' else {})))
        host = z.req('POST', 'bots', dict(name='統籌', provider='claude', jobTitle='統籌'))
        a = z.req('POST', 'bots', dict(name='小柯', provider='codex', jobTitle='研究'))
        b = z.req('POST', 'bots', dict(name='小克', provider='claude', jobTitle='文案'))
        group = z.req('POST', 'groups', dict(name='出遊小組', botIds=[host['id'], a['id'], b['id']], hostId=host['id'], mode=mode, turnLimit=16))
        if 'id' not in group: raise SystemExit('建立群組失敗：%s' % group)
        began = time.time()
        sent = z.req('POST', 'groups/%s/messages' % group['id'], dict(content=TOPIC, mode=mode))
        if sent.get('httpStatus'): raise SystemExit('送出失敗：%s' % sent)
        end = began + 900
        while time.time() < end:
            state = z.req('GET', 'groups/%s' % group['id'])
            g = state.get('group') or state
            run = g.get('taskRun') or {}
            if run.get('awaitingConfirm'):  # press 「照這個做」 for what the card shows
                z.req('POST', 'groups/%s/tasks/confirm' % group['id'], {'tasks': [t['id'] for t in run['tasks'] if t.get('confirmed') is False and t['status'] in ('pending', 'ready', 'waiting')]})
            if g.get('status') != 'running' and time.time() - began > 3: break
            time.sleep(2)
        took = time.time() - began
        data = json.loads((folder / 'data' / 'swarmr.json').read_text(encoding='utf-8'))
        jobs = [j for j in data.get('jobs') or [] if j.get('groupId') == group['id']]
        tokens = sum(int((j.get('usage') or {}).get('input') or 0) + int((j.get('usage') or {}).get('output') or 0) for j in jobs)
        g = next(x for x in data['groups'] if x['id'] == group['id'])
        result = dict(mode=mode, seconds=round(took, 1), requests=len(jobs), tokens=tokens,
                      failed=sum(1 for j in jobs if j.get('status') != 'completed'), errors=[(j.get('taskRole'), j.get('status'), (j.get('error') or '')[:200]) for j in jobs if j.get('status') != 'completed'],
                      wakes=(g.get('taskRun') or {}).get('wakes'), batches=(g.get('taskRun') or {}).get('batches'),
                      tasks=[(t['title'], t['status']) for t in (g.get('taskRun') or {}).get('tasks') or []])
        return result
    finally:
        z.close()
        if not keep:
            import shutil; shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--mode', default='split'); parser.add_argument('--port', type=int, default=8796)
    parser.add_argument('--save'); parser.add_argument('--keep', action='store_true')
    args = parser.parse_args()
    out = run(args.mode, args.port, args.keep)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.save: pathlib.Path(args.save).write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
