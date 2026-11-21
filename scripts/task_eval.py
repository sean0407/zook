#!/usr/bin/env python3
"""How well 任務引擎 hands out work, as one score. Fixed scenarios on a throwaway Zook with fake CLIs (no quota, same answer every
time): work runs at the same time, waits for what it needs, is checked by another vendor, stops after three misses, waits for the
user's decisions and 「照這個做」, goes to the vendor that does that kind of work better, and helpers stop at two layers. Each
scenario has checks (the score is the share that pass) and counts (model requests, host wakes, seconds).

    python3 scripts/task_eval.py                        run and print
    python3 scripts/task_eval.py --save docs/0.17-eval-baseline.json
    python3 scripts/task_eval.py --compare docs/0.17-eval-baseline.json   exit 1 when the score drops or requests grow
    python3 scripts/task_eval.py --live [--port 8796]   also one real run (Claude host, Claude and Grok members; uses a little quota)
"""
import argparse, json, pathlib, sys, tempfile, time, traceback
from datetime import datetime
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests')); sys.path.insert(0, str(ROOT / 'scripts'))
import task_engine_test as base
from task_engine_test import PLAN, WAKE, SUMMARY, create, done
from task_order_test import after
from task_check_test import CHECK, verdict
from task_plus_test import HELPER, BACK, delegate


class Harness(base.TaskEngineTest):
    def runTest(self): pass

    def tasks(self): return (self.req('GET', '/api/groups/' + self.group['id'])[1]['group'].get('taskRun') or {}).get('tasks') or []

    def mixed(self):
        codex = self.req('POST', '/api/bots', {'name': '丁', 'provider': 'codex'})[1]
        self.group = self.req('POST', '/api/groups', {'name': '混合', 'botIds': [self.bots['主持']['id'], self.bots['甲']['id'], codex['id']], 'hostId': self.bots['主持']['id']})[1]
        return codex


def workers(h): return [r for r in h.runs() if r['match'] not in (PLAN, WAKE) and CHECK not in r['prompt']]


def parallel(h):
    h.engine()
    h.rules([{'match': PLAN, 'calls': [create(1, '甲'), create(2, '乙'), create(3, '丙')], 'reply': '分好了'},
             {'match': '=== 工作', 'calls': [done()], 'sleep': 1}, {'match': WAKE, 'reply': SUMMARY}])
    run = h.send()['taskRun']; work = workers(h)
    together = len(work) == 3 and max(r['began'] for r in work) < min(r['ended'] for r in work)  # one moment when all three were working
    return {'三項都完成': all(t['status'] == 'done' for t in run['tasks']), '三項同時進行': together,
            '主持人只被叫醒一次': run['wakes'] == 1, '只有一個批次': run['batches'] == 1}, dict(wakes=run['wakes'])


def deps(h):
    h.engine()
    h.rules([{'match': PLAN, 'calls': [create(1, '甲'), after(2, '乙', ['1'])], 'reply': '分好了'},
             {'match': '=== 工作 1', 'calls': [done('第一項的結果是 42。')]}, {'match': '=== 工作 2', 'calls': [done()]}, {'match': WAKE, 'reply': SUMMARY}])
    run = h.send()['taskRun']; work = workers(h)
    one = next((r for r in work if '=== 工作 1' in r['prompt']), None); two = next((r for r in work if '=== 工作 2' in r['prompt']), None)
    return {'兩項都完成': [t['status'] for t in run['tasks']] == ['done', 'done'], '第二項在第一項結束後才開始': bool(one and two and two['began'] >= one['ended'] - 0.05),
            '第二項拿到第一項的回報': bool(two and '第一項的結果是 42' in two['prompt'])}, {}


def cross_check(h):
    h.mixed(); h.engine()
    h.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': '改好了', 'calls': [verdict('pass')]},
             {'match': CHECK, 'calls': [verdict('fail', '少了理由')]}, {'match': '這項工作上一次沒有完成', 'calls': [done('改好了，有理由。')]},
             {'match': '=== 工作 1', 'calls': [done('列好了。')]}, {'match': WAKE, 'reply': SUMMARY}])
    task = h.send()['taskRun']['tasks'][0]; checks = [r for r in h.runs() if CHECK in r['prompt']]
    redo = next((r for r in h.runs() if '這項工作上一次沒有完成' in r['prompt']), None)
    work = {r['cli'] for r in workers(h) if '=== 工作 1' in r['prompt']}
    return {'由另一家驗收': bool(checks) and bool(work) and not ({r['cli'] for r in checks} & work), '沒通過的理由交給重做': bool(redo and '少了理由' in redo['prompt']),
            '重做後通過': (task['status'], task['failures']) == ('done', 1)}, {}


def retry_stop(h):
    h.engine()
    h.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': '=== 工作 1', 'calls': [done('做不到。', 'failed')]}, {'match': WAKE, 'reply': SUMMARY}])
    task = h.send()['taskRun']['tasks'][0]
    return {'三次後停下等你': (task['status'], task['failures'], len(task['attempts'])) == ('stuck', 3, 3)}, {}


def gate(h):
    h.engine()
    ask = {'name': 'zook_task_gate', 'arguments': {'question': '要用哪個方案？', 'options': ['A 方案', 'B 方案'], 'tasks': ['2']}}
    h.rules([{'match': PLAN, 'calls': [create(1, '甲'), create(2, '乙'), ask], 'reply': '分好了'}, {'match': '=== 工作', 'calls': [done()]}, {'match': WAKE, 'reply': SUMMARY}])
    h.req('POST', '/api/groups/%s/messages' % h.group['id'], {'content': '做事', 'mode': 'auto'})
    end, run = time.time() + 20, {}
    while time.time() < end:
        group = h.req('GET', '/api/groups/' + h.group['id'])[1]['group']; run = group.get('taskRun') or {}
        if run.get('awaitingConfirm'): h.confirm(group)
        for t in run.get('tasks') or []:
            if t['status'] == 'review': h.req('POST', '/api/groups/%s/tasks/%s/accept' % (h.group['id'], t['id']), {})
        if run.get('tasks') and run['tasks'][0]['status'] == 'done': break
        time.sleep(0.1)
    held = [t['status'] for t in run.get('tasks') or []] == ['done', 'waiting'] and not [r for r in workers(h) if '=== 工作 2' in r['prompt']]
    pending = [g for g in run.get('gates') or [] if g['status'] == 'pending']
    if pending: h.req('POST', '/api/groups/%s/gates/%s' % (h.group['id'], pending[0]['id']), {'answer': 'B 方案'})
    run = h.wait_group()['taskRun']; two = next((r for r in workers(h) if '=== 工作 2' in r['prompt']), None)
    return {'只有相關的工作等決定': held, '決定交給那項工作': bool(two and '要用哪個方案？ → B 方案' in two['prompt'])}, {}


def confirm(h):
    h.engine(); h.autoconfirm = False
    h.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': '=== 工作', 'calls': [done()]}, {'match': WAKE, 'reply': SUMMARY}])
    h.req('POST', '/api/groups/%s/messages' % h.group['id'], {'content': '做事', 'mode': 'auto'})
    end = time.time() + 15
    while time.time() < end and not (h.req('GET', '/api/groups/' + h.group['id'])[1]['group'].get('taskRun') or {}).get('awaitingConfirm'): time.sleep(0.1)
    time.sleep(1.5); early = not workers(h)
    h.confirm()
    return {'確認前沒有開始': early, '確認後完成': h.wait_group()['taskRun']['tasks'][0]['status'] == 'done'}, {}


def record(h):
    codex = h.mixed(); h.engine()
    h.restart(lambda d: d.update(taskStats={'claude': {'quick': [1, 5]}, 'codex': {'quick': [4, 4]}}))
    h.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': CHECK, 'calls': [verdict('pass')]},
             {'match': '=== 工作 1', 'calls': [done()]}, {'match': WAKE, 'reply': SUMMARY}])
    group = h.send(); task = group['taskRun']['tasks'][0]
    board = [m for m in group['messages'] if m.get('taskBoard')][-1:]
    saved = {}
    h.restart(lambda d: saved.update(d.get('taskStats') or {}))
    return {'改派給紀錄較好的一家': task['assignee'] == codex['id'], '原因寫在任務板上': bool(board) and '依過去的驗收紀錄改派' in board[0]['content'],
            '驗收結果記進紀錄': (saved.get('codex') or {}).get('quick') == [5, 5]}, {}


def helpers(h):
    h.engine()
    h.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': HELPER, 'calls': [delegate('丙'), done('背景查好了。')]},
             {'match': BACK, 'calls': [done('主工作完成。')]}, {'match': '=== 工作 1', 'calls': [delegate('乙')]}, {'match': WAKE, 'reply': SUMMARY}])
    run = h.send()['taskRun']; deeper = next((r for r in h.runs() if HELPER in r['prompt']), None)
    back = next((r for r in h.runs() if BACK in r['prompt']), None)
    return {'助手完成，原工作帶著回報接著做': [t['status'] for t in run['tasks']] == ['done', 'done'] and bool(back and '背景查好了' in back['prompt']),
            '第三層被拒絕': bool(deeper and deeper['answers'] and deeper['answers'][0]['error'] and '最多兩層' in deeper['answers'][0]['text']) and len(run['tasks']) == 2}, {}


SCENARIOS = [('同時進行', parallel), ('先後順序', deps), ('交叉驗收', cross_check), ('三次後停下', retry_stop), ('決策關卡', gate),
             ('先問我', confirm), ('依紀錄派工', record), ('助手兩層', helpers)]


def fake():
    out = {}
    for name, scenario in SCENARIOS:
        h = Harness(); began = time.time()
        try:
            h.setUp()
            try: checks, counts = scenario(h)
            except Exception as exc: checks, counts = {'沒有出錯': False}, {'error': (str(exc) or type(exc).__name__)[:200]}
            counts.update(requests=len(h.runs()), seconds=round(time.time() - began, 1))
        finally:
            try: h.tearDown()
            except Exception: traceback.print_exc()
        out[name] = dict(checks=checks, **counts)
        print('%-8s %s  請求 %d  %.1f 秒' % (name, ' '.join(('✓' if ok else '✗') + k for k, ok in checks.items()), counts['requests'], counts['seconds']), flush=True)
    passed = sum(ok for s in out.values() for ok in s['checks'].values()); total = sum(len(s['checks']) for s in out.values())
    return dict(score=round(100 * passed / total, 1), passed=passed, total=total, requests=sum(s['requests'] for s in out.values()), scenarios=out)


LIVE_GOAL = ('請分工完成，一項一個工作：\n1. 小柯：算出 17 × 23。\n2. 小克：用第 1 項的結果寫一句 20 字以內的話，要等第 1 項做完再寫。\n3. 小克：列出三個台灣的直轄市（和第 1 項同時做）。')
LIVE_HELPER = ('只建立一項工作，交給小克：寫一句 30 字以內介紹台北 101 的話，裡面要有它的高度（公尺）。'
               '在工作說明裡要求小克先用 zook_task_delegate 派小柯當助手查出台北 101 的高度（changes 寫 none），等助手回報後再寫。')


def live(port):
    return dict(平行與驗收=live_one(port, LIVE_GOAL, False), 派助手=live_one(port, LIVE_HELPER, True))


def live_one(port, goal, helper):
    import acceptance as acc
    folder = pathlib.Path(tempfile.mkdtemp(prefix='zook-eval-'))
    z = acc.Zook(folder, port)
    try:
        z.req('PATCH', 'settings', dict(permissionMode='auto', taskEngine=True))
        host = z.req('POST', 'bots', dict(name='統籌', provider='claude'))
        a = z.req('POST', 'bots', dict(name='小柯', provider='grok', jobTitle='研究'))
        b = z.req('POST', 'bots', dict(name='小克', provider='claude', jobTitle='文案'))
        g = z.req('POST', 'groups', dict(name='小組', botIds=[host['id'], a['id'], b['id']], hostId=host['id'], mode='auto'))
        began = time.time(); z.req('POST', 'groups/%s/messages' % g['id'], dict(content=goal))
        finished = False
        while time.time() - began < 900:
            st = z.req('GET', 'groups/' + g['id'])['group']; run = st.get('taskRun') or {}
            if run.get('awaitingConfirm'): z.req('POST', 'groups/%s/tasks/confirm' % g['id'], {'tasks': [t['id'] for t in run['tasks'] if t.get('confirmed') is False and t['status'] in ('pending', 'ready', 'waiting')]})
            for t in run.get('tasks') or []:
                if t['status'] == 'review': z.req('POST', 'groups/%s/tasks/%s/accept' % (g['id'], t['id']), {})
            if st['status'] != 'running' and time.time() - began > 3: finished = True; break
            time.sleep(2)
        took = time.time() - began
        data = json.loads((folder / 'data/swarmr.json').read_text(encoding='utf-8'))
        run = next(x for x in data['groups'] if x['id'] == g['id'])['taskRun']; jobs = {j['id']: j for j in data['jobs']}
        mine = [j for j in data['jobs'] if j.get('groupId') == g['id']]
        def vendor(job_id): return ((jobs.get(job_id) or {}).get('ranOn') or ((jobs.get(job_id) or {}).get('usage') or {}).get('provider') or '')
        crossed = [t for t in run['tasks'] if (t.get('verify') or {}).get('verdict') == 'pass']
        def span(t):
            job = jobs.get((t['attempts'] or [{}])[0].get('jobId')) or {}
            return datetime.fromisoformat(job['createdAt']).timestamp() if job.get('createdAt') else 0, datetime.fromisoformat(job['finishedAt']).timestamp() if job.get('finishedAt') else 0
        checks = {'在時限內結束': finished, '全部完成': bool(run['tasks']) and all(t['status'] == 'done' for t in run['tasks']),
                  '每項由另一家驗收': all(vendor(t['verify'].get('jobId')) != vendor(t['attempts'][-1].get('jobId')) for t in crossed) and len(crossed) == len(run['tasks']),
                  '主持人叫醒次數不超過批次加一': run['wakes'] <= run['batches'] + 1, '沒有超過兩層': all((t.get('depth') or 1) <= 2 for t in run['tasks'])}
        if helper:
            kids = [t for t in run['tasks'] if t.get('depth') == 2]
            parent = next((t for t in run['tasks'] if kids and t['n'] == kids[0].get('parent')), None)
            reported = [a.get('endedAt') or '' for a in kids[0]['attempts'] if a.get('state') == 'reported'] if kids else []
            later = parent and len(parent['attempts']) >= 2 and parent['attempts'][0].get('state') == 'delegated' and kids[0]['n'] in (parent.get('deps') or []) and \
                bool(reported) and (parent['attempts'][1].get('startedAt') or '') >= max(reported)
            checks['派了助手，原工作在助手回報後才接著做'] = bool(kids and later)
        else:
            who = {b['id']: b['name'] for b in data['bots']}
            calc = [t for t in run['tasks'] if who.get(t['assignee']) == '小柯' and not t.get('deps')]
            line = [t for t in run['tasks'] if who.get(t['assignee']) == '小克' and calc and t.get('deps') == [calc[0]['n']]]
            cities = [t for t in run['tasks'] if who.get(t['assignee']) == '小克' and not t.get('deps')]
            checks['三項工作、那句話接在計算之後'] = len(run['tasks']) == 3 and len(calc) == 1 and len(line) == 1 and len(cities) == 1
            checks['計算和列城市同時進行'] = bool(calc and cities) and max(span(calc[0])[0], span(cities[0])[0]) < min(span(calc[0])[1], span(cities[0])[1])
        tokens = sum(int((j.get('usage') or {}).get('input') or 0) + int((j.get('usage') or {}).get('output') or 0) for j in mine)
        out = dict(checks=checks, seconds=round(took), requests=len(mine), tokens=tokens, wakes=run['wakes'], batches=run['batches'], tasks=len(run['tasks']))
        print('實機%s  %s  請求 %d  %d 秒  token %d' % ('（助手）' if helper else '', ' '.join(('✓' if ok else '✗') + k for k, ok in checks.items()), len(mine), took, tokens))
        return out
    finally:
        z.close()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--save'); ap.add_argument('--compare'); ap.add_argument('--live', action='store_true'); ap.add_argument('--port', type=int, default=8796)
    args = ap.parse_args()
    if args.save and args.compare and pathlib.Path(args.save).resolve() == pathlib.Path(args.compare).resolve(): raise SystemExit('--save 和 --compare 不能是同一個檔案：會先蓋掉要比較的基準。')
    before = json.loads(pathlib.Path(args.compare).read_text(encoding='utf-8')) if args.compare else None
    result = dict(at=time.strftime('%Y-%m-%d %H:%M'), **fake())
    if args.live: result['live'] = live(args.port)
    print('分數 %.1f（%d／%d 項通過），模型請求 %d 次' % (result['score'], result['passed'], result['total'], result['requests']))
    if args.save: pathlib.Path(args.save).write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8'); print('已存到', args.save)
    if args.compare:
        worse = []
        if result['score'] < before['score']: worse.append('分數 %.1f → %.1f' % (before['score'], result['score']))
        if result['requests'] > before['requests']: worse.append('模型請求 %d → %d' % (before['requests'], result['requests']))
        for name, s in before.get('scenarios', {}).items():
            lost = [k for k, ok in s['checks'].items() if ok and not result['scenarios'].get(name, {}).get('checks', {}).get(k)]
            if lost: worse.append('%s 不再通過：%s' % (name, '、'.join(lost)))
        if args.live:  # a real run that misses something counts, also when the reference had no real run
            for name, s in (result.get('live') or {}).items():
                missed = [k for k, ok in s['checks'].items() if not ok]
                if missed: worse.append('實機「%s」沒有通過：%s' % (name, '、'.join(missed)))
        print('和基準比：' + ('；'.join(worse) if worse else '沒有變差'))
        if worse: sys.exit(1)


if __name__ == '__main__': main()
