# 任務引擎, the running part: the host's turns, the members' tasks, and the loop that decides what happens next.
# Loaded by backend/server.py into one shared namespace; mixed into App. The books and the tools are in tasks.py.
#
# One loop per run, woken by events (a report, a finished reply, an answer), never by asking the CLIs. Every task is an ordinary
# group reply of the member it was given to: same model choice, 主動性, access, approvals, origin and shared files as any other.
class TaskRuns:
    def task_poke(self, group_id):
        event = self.__dict__.setdefault('task_events', {}).get(group_id)
        if event: event.set()

    def run_task_engine(self, group_id, run_id, resume=False):
        """The whole run. Called from run_group, which marks the group idle when this returns; resume=True carries on a run whose
        loop had ended (a task the user asked to retry), without planning again."""
        store = self.store
        event = self.__dict__.setdefault('task_events', {})[group_id] = threading.Event()  # this run's own; a run stopped a moment ago keeps its old one
        problem = ''
        with store.lock:
            if not resume:
                group = store.find('groups', group_id)
                if not group or group.get('runId') != run_id: return
                host = group_closer(store, group)
                host_bot = store.find('bots', host) if host else None
                others = [x for x in group['botIds'] if x != host and store.find('bots', x) and not task_member_ok(store, store.find('bots', x))]
                problem = '沒有主持人' if not host_bot else task_member_ok(store, host_bot) or ('' if others else '沒有其他能接工作的成員')
                if problem:  # nothing starts by itself instead: the user chooses 分工 if they want it
                    group['messages'].append(dict(id=ID(), role='system', content='任務引擎這次不能用（%s）。要分工的話，把討論方式改成「分工」再送一次。' % problem, createdAt=NOW()))
                    store.save()
                else:
                    starter = next((m for m in reversed(group['messages']) if m.get('role') == 'user' and not m.get('interjected')), {})  # 插話 is never the goal
                    origin = 'schedule' if starter.get('author') == '排程' else 'bot' if starter.get('author') else 'user'
                    run = task_new_run(starter.get('content'), host, origin); run['groupRunId'] = run_id; run['goalId'] = starter.get('id')
                    group['taskRun'] = run
                    group['messages'].append(dict(id=ID(), role='system', taskBoard=run['id'], content=task_board_text(store, run), createdAt=NOW()))
                    store.save()
        if problem: return
        threads, ended, pause = {}, 'done', 1.0
        if not resume: threads['host'] = self._task_thread(self._task_host, group_id, run_id, 'plan')
        try:
            while True:
                event.wait(pause); event.clear()
                with store.lock:
                    group = store.find('groups', group_id)
                    if not group or group.get('runId') != run_id: ended = 'stopped'; break
                    run = group['taskRun']
                    for key in [k for k, th in threads.items() if not th.is_alive()]: threads.pop(key)
                    before = json.dumps(run, sort_keys=True, default=str)
                    plan = self._task_next(store, group, run, 'host' in threads)
                    if plan['finish']: break
                    if plan['stop']:
                        ended = 'stopped'; group['messages'].append(dict(id=ID(), role='system', content=plan['stop'], createdAt=NOW()))
                        for job in [j for j in (store.find('jobs', x) for x in group.get('activeJobIds') or []) if j]: self.cancel_job(job)
                        break
                    if json.dumps(run, sort_keys=True, default=str) != before: store.save()
                    idle = not threads and not plan['start'] and not plan.get('verify') and not plan['wake']
                for task_id in plan['start']: threads[task_id] = self._task_thread(self._task_worker, group_id, run_id, task_id)
                for task_id in plan.get('verify') or []: threads['v:' + task_id] = self._task_thread(self._task_verify, group_id, run_id, task_id)
                pause = 0.3 if plan.get('soon') else 3.0 if idle else 1.0  # only waiting for the user: look now and then; any event wakes it at once
                if plan['wake']: threads['host'] = self._task_thread(self._task_host, group_id, run_id, 'wake')
        finally:
            with store.lock:
                group = store.find('groups', group_id)
                run = (group or {}).get('taskRun')
                if run and run['id'] == (group.get('taskRun') or {}).get('id') and run.get('groupRunId') == run_id:
                    run['status'] = 'done' if ended == 'done' else 'stopped'
                    for t in run['tasks']:
                        if t.get('parent') and t.get('staged'): task_handoff_abort(run, t['parent'])
                    for t in run['tasks']:
                        if t['status'] not in TASK_SETTLED: t['status'] = 'cancelled'
                    task_board_update(store, group); store.save()
            if self.__dict__.get('task_events', {}).get(group_id) is event: self.task_events.pop(group_id, None)

    def _task_thread(self, target, *args):
        def guarded():
            try: target(*args)
            except Exception as exc:  # whatever went wrong, the task does not stay 'running' and the loop hears about it
                if target == self._task_host:
                    with self.store.lock:
                        group = self.store.find('groups', args[0]); run = (group or {}).get('taskRun') or {}
                        for t in run.get('tasks') or []:
                            if not t.get('parent'): t.pop('staged', None)  # a helper waits for its own member's turn
                        run['hostMissed'] = run.get('hostMissed', 0) + 1
                        if group: group['messages'].append(dict(id=ID(), role='system', content='主持人這一輪出錯了：%s' % str(exc)[:150], createdAt=NOW()))
                        self.store.save()
                elif len(args) == 3:
                    with self.store.lock:
                        group = self.store.find('groups', args[0]); run = (group or {}).get('taskRun') or {}
                        for t in run.get('tasks') or []:
                            if t['id'] == args[2] and t['status'] in ('running', 'verifying'): t['status'] = 'stuck'; t['note'] = 'Zook 內部錯誤：%s' % str(exc)[:150]
                        if run.get('tasks'): task_handoff_orphans(run)
                        self.store.save()
                self.task_poke(args[0])
        th = threading.Thread(target=guarded, daemon=True); th.start()
        return th

    def _task_next(self, store, group, run, host_busy):
        """Lock held. What the loop does now: which tasks start, whether the host is woken, whether the run is over.
        Tasks are chosen first and only committed when the run goes on, so a stop never counts attempts that did not start."""
        out = dict(start=[], wake=False, finish=False, stop='', verify=[])
        if run.get('hostMissed', 0) >= 2:
            out['stop'] = '主持人連續兩次沒有完成，任務先停在這裡。'
            return out
        if not task_on(store) and (run.get('awaitingConfirm') or any(g.get('status') == 'pending' for g in run.get('gates') or []) or any(t['status'] == 'review' for t in run['tasks'])):
            out['stop'] = '任務引擎已關閉，等你確認或決定的工作不會開始。'
            return out
        task_resolve_deps(run)
        for t in run['tasks']:  # finished work nobody of another vendor can check waits for the user (等你看結果), before anything waiting for it is looked at
            if t['status'] == 'verifying' and (t.get('verify') or {}).get('state') == 'waiting' and task_pick_verifier(store, group, run, t, set()) == 'none':
                t['verify']['state'] = 'none'; t['status'] = 'review'; t['reviewSince'] = time.time(); t['note'] = '沒有其他家的模型可以驗收這項。看過結果後按「接受結果」。'
        now = time.time()
        for t in run['tasks']:  # a result nobody looked at in time stops there
            if t['status'] == 'review' and now - t.get('reviewSince', now) > task_wait_limit(run): t['status'] = 'stuck'; t['note'] = '沒有等到你看結果，停下來等你決定。'
        for g in run.get('gates') or []:  # a decision nobody made in time: what waited for it does not start
            if g['status'] == 'pending' and now - g.get('since', now) > task_wait_limit(run):
                g['status'] = 'timeout'
                for t in run['tasks']:
                    if t.get('gate') == g['id'] and t['status'] == 'waiting': t['status'] = 'failed'; t['note'] = '沒有等到你的決定。'
        task_resolve_deps(run)
        unconfirmed = [t for t in run['tasks'] if not t.get('confirmed', True) and t['status'] in ('pending', 'ready', 'waiting') and not t.get('staged')]
        run['awaitingConfirm'] = bool(unconfirmed) and not host_busy  # shown once the host has finished planning
        if run['awaitingConfirm']:
            if not run.get('confirmSince'):
                run['confirmSince'] = now
                if run.get('origin') != 'user': self.notify(group['name'], '任務引擎排好了 %d 項工作，等你確認後才開始。' % len(unconfirmed), 'group', group['id'], '', always=True)
            elif now - run['confirmSince'] > task_wait_limit(run):
                out['stop'] = '沒有等到你確認分工，任務停在這裡。'
                return out
        else: run.pop('confirmSince', None)
        task_handoff_orphans(run)
        running = [t for t in run['tasks'] if t['status'] == 'running']
        ready = [t for t in run['tasks'] if t['status'] == 'ready' and t.get('confirmed', True) and not t.get('staged')]
        if ready and run['attempts'] >= task_limit(run, 'attempts'):
            for t in ready: t['status'] = 'failed'; t.setdefault('note', '這個目標的嘗試次數已到上限 %d 次。' % task_limit(run, 'attempts'))
            ready = []
        delivered = set(run.get('delivered') or [])
        if not host_busy and not running and not ready:
            # Nothing else can happen: a question or block the host was told about and left unanswered ends that task here,
            # and the host hears about it (and about what waited for it) at one last wake.
            for t in run['tasks']:
                if t['status'] in ('asked', 'blocked') and task_key(t) in delivered: t['status'] = 'failed'; t.setdefault('note', '主持人沒有回答，這項工作停在這裡。')
            task_resolve_deps(run)
        chosen = self._task_choose(store, run, running, ready)
        working = {j['botId'] for j in store.data['jobs'] if j.get('status') == 'running'} | {t['assignee'] for t, _, _ in chosen}
        most, per_cli = task_limits(store); lanes = task_busy_lanes(store)
        for _, lane, _ in chosen: lanes[tuple(lane)] = lanes.get(tuple(lane), 0) + 1
        active = len(running) + len(chosen) + len([x for x in run['tasks'] if x['status'] == 'verifying' and (x.get('verify') or {}).get('state') == 'running'])
        for t in run['tasks']:  # a finished task waiting for its check: a member of another vendor checks it
            check = t.get('verify') or {}
            if t['status'] != 'verifying' or check.get('state') != 'waiting': continue
            pick = task_pick_verifier(store, group, run, t, working)
            if pick == 'wait': continue
            if pick != 'none':
                checker = store.find('bots', pick[0]) or {}
                lane = task_lane(store, checker) if task_lane(store, checker)[0] != AUTO else (pick[1][0], pick[1][2] if len(pick[1]) > 2 else '')
                if active >= most or lanes.get(tuple(lane), 0) >= per_cli.get(lane[0], TASK_PER_CLI): continue  # no room now: check a little later
                lanes[tuple(lane)] = lanes.get(tuple(lane), 0) + 1; active += 1; check['lane'] = list(lane)
            if pick == 'none': check['state'] = 'none'; t['status'] = 'review'; t['reviewSince'] = time.time(); t['note'] = '沒有其他家的模型可以驗收這項。看過結果後按「接受結果」。'; continue
            check.update(state='running', bot=pick[0], use=pick[1]); working.add(pick[0]); out['verify'].append(t['id'])
        news = [t for t in run['tasks'] if t['status'] in TASK_SETTLED + ('asked', 'blocked') and task_key(t) not in delivered]
        checking = [t for t in run['tasks'] if t['status'] in ('verifying', 'review')]  # a result still being checked or looked at belongs to this batch
        busy = running or chosen or checking
        if not host_busy and news and (any(t['status'] in ('asked', 'blocked') for t in news) or not busy):
            if run['wakes'] >= task_limit(run, 'wakes'):
                out['stop'] = '主持人已經被叫醒 %d 次，任務先停在這裡，避免一直派工下去。' % run['wakes']
                return out
            run['wakes'] += 1; run['wakeFor'] = [t['id'] for t in news]; run['delivered'] = sorted(delivered | {task_key(t) for t in news})
            out['wake'] = True
        if chosen:
            if not running and not checking and not news: run['batches'] += 1  # a new wave: nothing is running and the host has heard about everything before it
            for t, lane, use in chosen:
                t['status'] = 'running'; run['attempts'] += 1; out['start'].append(t['id'])
                run.setdefault('lanes', {})[t['id']] = list(lane)
                if use: run.setdefault('use', {})[t['id']] = list(use)
                else: run.get('use', {}).pop(t['id'], None)
            out['soon'] = any(t['status'] == 'ready' for t in run['tasks'])  # more could start: look again shortly, not all in one go
        held = unconfirmed or [t for t in run['tasks'] if t['status'] in ('waiting', 'review') or t.get('staged')]  # waiting for the user: the run is not over
        if not out['wake'] and not host_busy and not running and not chosen and not checking and not held and not [t for t in run['tasks'] if t['status'] == 'ready']:
            for t in run['tasks']:
                if t['status'] == 'pending': t['status'] = 'failed'; t.setdefault('note', '前面的工作沒有完成，這項沒有開始。')
            out['finish'] = True
        task_board_update(store, group)
        return out

    def _task_choose(self, store, run, running, ready):
        """Lock held. [(task, (CLI, account), model to use or None)] that may start now: within the group's limit and each CLI's
        (counted by the model each running task really uses, backups included), a few at a time, one task per member at a time."""
        most, per_cli = task_limits(store)
        lanes = task_busy_lanes(store)  # every group's running tasks and checks, by the model they really use
        checking = [t for t in run['tasks'] if t['status'] == 'verifying' and (t.get('verify') or {}).get('state') == 'running']
        working = {j['botId'] for j in store.data['jobs'] if j.get('status') == 'running'}
        room = min(most - len(running) - len(checking), task_limit(run, 'attempts') - run['attempts'], TASK_START_EVERY)
        chosen = []
        for t in ready:
            if len(chosen) >= room: break
            if t['assignee'] in working: continue  # it waits for its member instead of holding a place another task could use
            bot = store.find('bots', t['assignee']) or {}
            lane, use = task_lane(store, bot), None
            if lane[0] == AUTO:  # 自動選擇: pick its model now, among the CLIs that still have room
                try: options = pick_auto(store, t['spec'], plan=t.get('changes') == 'none', bot=bot)[0]
                except ValueError as exc: t['status'] = 'failed'; t['note'] = str(exc)[:200]; continue
                fit = next((x for x in options if lanes.get((x[0], x[2] if len(x) > 2 else ''), 0) < per_cli.get(x[0], TASK_PER_CLI)), None)
                if not fit: continue
                lane, use = (fit[0], fit[2] if len(fit) > 2 else ''), fit  # an option may name one of the CLI's extra accounts
            elif lanes.get(lane, 0) >= per_cli.get(lane[0], TASK_PER_CLI): continue  # this CLI (this account of it) is full
            lanes[lane] = lanes.get(lane, 0) + 1; working.add(t['assignee']); chosen.append((t, lane, use))
        return chosen

    def _task_turn(self, group_id, run_id, bot_id, step):
        """A turn that waits while the Bot is busy in another conversation. Returns the turn, None when skipped, False when the run ended."""
        while True:
            turn = self._group_turn(group_id, run_id, bot_id, False, None, False, False, step)
            if turn != 'busy': return turn
            time.sleep(2)

    def _task_host(self, group_id, run_id, kind):
        store = self.store
        with store.lock:
            group = store.find('groups', group_id); run = (group or {}).get('taskRun')
            if not run: return
            host, run_ref = run['hostId'], run['id']
        origin = run['origin'] if run['origin'] != 'user' else 'bot' if kind == 'wake' else None  # a wake answers reports a Bot wrote
        step = dict(waitBusy=True, readonly=True, job=dict(dict(taskRole='host', taskRunId=run_ref), **({'origin': origin} if origin else {})), attachIds=[run.get('goalId')],
                    promptFor=lambda bot, writable: task_host_prompt(store, store.find('groups', group_id), store.find('groups', group_id)['taskRun'], bot, kind))
        turn = self._task_turn(group_id, run_id, host, step)
        if turn: self._group_job(group_id, turn)
        with store.lock:
            group = store.find('groups', group_id)
            if not group: return
            run = group.get('taskRun') or {}
            if run.get('id') == run_ref:
                for t in run.get('tasks') or []:
                    if not t.get('parent'): t.pop('staged', None)  # the host's turn is over: what it planned may start (or be confirmed); a helper waits for its member's turn
            if run.get('id') == run_ref and (not turn or turn['job']['status'] != 'completed'):
                run['hostMissed'] = run.get('hostMissed', 0) + 1
                if kind == 'wake':  # the host did not get the reports: they are news again
                    told = set(run.get('wakeFor') or [])
                    run['delivered'] = [k for k in run.get('delivered') or [] if k.split(':')[0] not in told]
                group['messages'].append(dict(id=ID(), role='system', content='主持人%s沒有完成這一輪。' % ('' if turn else '這次不能回覆，'), createdAt=NOW()))
            else: run['hostMissed'] = 0
            if not turn: store.save(); self.task_poke(group_id); return
            group['activeJobIds'] = [x for x in group.get('activeJobIds') or [] if x != turn['job']['id']]; group['activeJobId'] = (group['activeJobIds'] or [None])[0]
            run = group.get('taskRun') or {}
            if turn['job']['status'] == 'completed' and run.get('tasks') and all(t['status'] in TASK_SETTLED for t in run['tasks']):
                card = group_card(turn['job'].get('content'))
                if card: turn['msg']['card'] = card
            store.save()
        self.task_poke(group_id)

    def _task_worker(self, group_id, run_id, task_id):
        store = self.store
        with store.lock:
            group = store.find('groups', group_id); run = (group or {}).get('taskRun')
            task = next((t for t in (run or {}).get('tasks') or [] if t['id'] == task_id), None)
            if not task or group.get('runId') != run_id or task['status'] != 'running' or (task['attempts'] and task['attempts'][-1].get('state') in ('starting', 'running')): return
            before = task['attempts'][-1] if task['attempts'] else {}
            attempt = dict(id=ID(), n=len(task['attempts']) + 1, jobId=None, state='starting', followUp=bool(task.get('answer')), startedAt=NOW(),
                           retryOf=before.get('id') if task.get('failures') else None)
            task['attempts'].append(attempt)  # counted in run['attempts'] when it was picked
            assignee, label = task['assignee'], '%d. %s' % (task['n'], task['title'])
            store.save()
        # A task is the host's instructions, not the user's: the member's reply counts as started by a Bot (or by whatever started the run).
        use = (run.get('use') or {}).get(task_id)
        # A task that changes nothing runs in a reply that may only read, so it really changes nothing.
        step = dict(waitBusy=True, readonly=task.get('changes') == 'none', **({'use': use} if use else {}), job=dict(taskRole='worker', taskRunId=run['id'], taskId=task_id, taskTitle=label, origin=run['origin'] if run['origin'] != 'user' else 'bot'),
                    msg=dict(taskId=task_id), attachIds=[run.get('goalId')],
                    promptFor=lambda bot, writable: task_worker_prompt(store, store.find('groups', group_id), store.find('groups', group_id)['taskRun'], task, bot, writable))
        turn = self._task_turn(group_id, run_id, assignee, step)
        with store.lock:
            if not turn:
                attempt.update(state='failed', summary='這位成員這次不能接工作（被移出群組或沒有可用的模型）。', endedAt=NOW())
                if turn is None: task_failed_attempt(task, attempt['summary'])
                store.save(); self.task_poke(group_id); return
            attempt.update(jobId=turn['job']['id'], state='running')
            store.save()
        self._group_job(group_id, turn)
        with store.lock: task.pop('resumed', None)  # told once (resume.py)
        with store.lock:
            group = store.find('groups', group_id)
            if group:
                group['activeJobIds'] = [x for x in group.get('activeJobIds') or [] if x != turn['job']['id']]; group['activeJobId'] = (group['activeJobIds'] or [None])[0]
            if not group or group.get('runId') != run_id or not task['attempts'] or task['attempts'][-1] is not attempt:  # old news: leave the newer try alone
                store.save(); return
            job = turn['job']
            said = attempt.get('summary') if attempt['state'] == 'reported' else task.get('question') if attempt['state'] == 'asked' else attempt.get('reason') if attempt['state'] == 'blocked' else \
                '派了助手，等它的回報再接著做。' if attempt['state'] == 'delegated' else ''
            if said and job['status'] == 'completed' and not (job.get('content') or '').strip():
                store.finish_message(job, said, 'completed')  # it reported and ended without words, as it was told to: its report is the reply
            attempt['cli'] = task_job_cli(store, job, store.find('bots', task['assignee']))  # what a checker must not be
            if attempt['state'] == 'reported' and job['status'] in ('failed', 'cancelled'):
                # The CLI failed after the report: its files may not have reached the group. The task did not finish.
                attempt.update(state='failed', outcome='failed', summary=('回報後 CLI 出錯：%s。原本的回報：%s' % ((job.get('error') or '')[:150], attempt.get('summary') or ''))[:600])
            if attempt['state'] == 'running':  # the reply ended without a report
                why = job.get('error') or ('回覆被停止' if job['status'] == 'cancelled' else '沒有用 zook_task_done 回報就結束了')
                attempt.update(state='failed', outcome='failed', summary=why[:300], endedAt=NOW())
            if task['status'] == 'running':
                if job['status'] == 'cancelled' and attempt['state'] == 'failed': task['status'] = 'cancelled'
                elif attempt['state'] in ('asked', 'blocked'): task['status'] = attempt['state']
                elif attempt['state'] == 'delegated': task_handoff_end(task, run, job, turn.get('published', True))
                elif attempt['state'] == 'reported' and attempt.get('outcome') == 'succeeded':
                    task['status'] = 'verifying'; task['verify'] = dict(state='waiting')  # checked by a member of another vendor next
                else: task_failed_attempt(task, attempt.get('summary') or '沒有完成', job)
            if group: task_board_update(store, group)
            store.save()
        self.task_poke(group_id)


def task_key(task):
    """What the host has been told about a task: its attempt and state."""
    return '%s:%d:%s' % (task['id'], len(task['attempts']), task['status'])
