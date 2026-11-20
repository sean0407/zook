# 任務引擎, the running part: the host's turns, the members' tasks, and the loop that decides what happens next.
# Loaded by backend/server.py into one shared namespace; mixed into App. The books and the tools are in tasks.py.
#
# One loop per run, woken by events (a report, a finished reply, an answer), never by asking the CLIs. Every task is an ordinary
# group reply of the member it was given to: same model choice, 主動性, access, approvals, origin and shared files as any other.
class TaskRuns:
    def task_poke(self, group_id):
        event = self.__dict__.setdefault('task_events', {}).get(group_id)
        if event: event.set()

    def run_task_engine(self, group_id, run_id):
        """The whole run. Called from run_group, which marks the group idle when this returns."""
        store = self.store
        event = self.__dict__.setdefault('task_events', {})[group_id] = threading.Event()  # this run's own; a run stopped a moment ago keeps its old one
        with store.lock:
            group = store.find('groups', group_id)
            if not group or group.get('runId') != run_id: return
            host = group_closer(store, group)
            host_bot = store.find('bots', host) if host else None
            others = [x for x in group['botIds'] if x != host and store.find('bots', x) and not task_member_ok(store, store.find('bots', x))]
            problem = '沒有主持人' if not host_bot else task_member_ok(store, host_bot) or ('' if others else '沒有其他能接工作的成員')
            if problem:
                group['messages'].append(dict(id=ID(), role='system', content='任務引擎這次不能用（%s），改用「分工」。' % problem, createdAt=NOW()))
                store.save()
            else:
                starter = next((m for m in reversed(group['messages']) if m.get('role') == 'user'), {})
                origin = 'schedule' if starter.get('author') == '排程' else 'bot' if starter.get('author') else 'user'
                run = task_new_run(starter.get('content'), host, origin); run['groupRunId'] = run_id; run['goalId'] = starter.get('id')
                group['taskRun'] = run
                group['messages'].append(dict(id=ID(), role='system', taskBoard=run['id'], content=task_board_text(store, run), createdAt=NOW()))
                store.save()
        if problem: return self._run_steps(group_id, run_id, group_steps(store, group, 'split'), group_limit(store, group))
        threads, ended, pause = {}, 'done', 1.0
        threads['host'] = self._task_thread(self._task_host, group_id, run_id, 'plan')
        try:
            while True:
                event.wait(pause); event.clear()
                with store.lock:
                    group = store.find('groups', group_id)
                    if not group or group.get('runId') != run_id: ended = 'stopped'; break
                    run = group['taskRun']
                    for key in [k for k, th in threads.items() if not th.is_alive()]: threads.pop(key)
                    plan = self._task_next(store, group, run, 'host' in threads)
                    if plan['finish']: break
                    if plan['stop']:
                        ended = 'stopped'; group['messages'].append(dict(id=ID(), role='system', content=plan['stop'], createdAt=NOW()))
                        for job in [j for j in (store.find('jobs', x) for x in group.get('activeJobIds') or []) if j]: self.cancel_job(job)
                        break
                    store.save()
                for task_id in plan['start']: threads[task_id] = self._task_thread(self._task_worker, group_id, run_id, task_id)
                pause = 0.3 if plan.get('soon') else 1.0
                if plan['wake']: threads['host'] = self._task_thread(self._task_host, group_id, run_id, 'wake')
        finally:
            with store.lock:
                group = store.find('groups', group_id)
                run = (group or {}).get('taskRun')
                if run and run['id'] == (group.get('taskRun') or {}).get('id') and run.get('groupRunId') == run_id:
                    run['status'] = 'done' if ended == 'done' else 'stopped'
                    for t in run['tasks']:
                        if t['status'] not in TASK_SETTLED: t['status'] = 'cancelled'
                    task_board_update(store, group); store.save()
            if self.__dict__.get('task_events', {}).get(group_id) is event: self.task_events.pop(group_id, None)

    def _task_thread(self, target, *args):
        th = threading.Thread(target=target, args=args, daemon=True); th.start()
        return th

    def _task_next(self, store, group, run, host_busy):
        """Lock held. What the loop does now: which tasks start, whether the host is woken, whether the run is over.
        Tasks are chosen first and only committed when the run goes on, so a stop never counts attempts that did not start."""
        out = dict(start=[], wake=False, finish=False, stop='')
        if run.get('hostMissed', 0) >= 2:
            out['stop'] = '主持人連續兩次沒有完成，任務先停在這裡。'
            return out
        task_resolve_deps(run)
        running = [t for t in run['tasks'] if t['status'] == 'running']
        ready = [t for t in run['tasks'] if t['status'] == 'ready']
        if ready and run['attempts'] >= TASK_ATTEMPTS:
            for t in ready: t['status'] = 'failed'; t.setdefault('note', '這個目標的嘗試次數已到上限 %d 次。' % TASK_ATTEMPTS)
            ready = []
        delivered = set(run.get('delivered') or [])
        if not host_busy and not running and not ready:
            # Nothing else can happen: a question or block the host was told about and left unanswered ends that task here,
            # and the host hears about it (and about what waited for it) at one last wake.
            for t in run['tasks']:
                if t['status'] in ('asked', 'blocked') and task_key(t) in delivered: t['status'] = 'failed'; t.setdefault('note', '主持人沒有回答，這項工作停在這裡。')
            task_resolve_deps(run)
        chosen = self._task_choose(store, run, running, ready)
        news = [t for t in run['tasks'] if t['status'] in TASK_SETTLED + ('asked', 'blocked') and task_key(t) not in delivered]
        busy = running or chosen
        if not host_busy and news and (any(t['status'] in ('asked', 'blocked') for t in news) or not busy):
            if run['wakes'] >= TASK_WAKES:
                out['stop'] = '主持人已經被叫醒 %d 次，任務先停在這裡，避免一直派工下去。' % TASK_WAKES
                return out
            run['wakes'] += 1; run['wakeFor'] = [t['id'] for t in news]; run['delivered'] = sorted(delivered | {task_key(t) for t in news})
            out['wake'] = True
        if chosen:
            if not running and not news: run['batches'] += 1  # a new wave: nothing is running and the host has heard about everything before it
            for t, lane, use in chosen:
                t['status'] = 'running'; run['attempts'] += 1; out['start'].append(t['id'])
                run.setdefault('lanes', {})[t['id']] = list(lane)
                if use: run.setdefault('use', {})[t['id']] = list(use)
                else: run.get('use', {}).pop(t['id'], None)
            out['soon'] = any(t['status'] == 'ready' for t in run['tasks'])  # more could start: look again shortly, not all in one go
        if not out['wake'] and not host_busy and not running and not chosen and not [t for t in run['tasks'] if t['status'] == 'ready']:
            for t in run['tasks']:
                if t['status'] == 'pending': t['status'] = 'failed'; t.setdefault('note', '前面的工作沒有完成，這項沒有開始。')
            out['finish'] = True
        task_board_update(store, group)
        return out

    def _task_choose(self, store, run, running, ready):
        """Lock held. [(task, (CLI, account), model to use or None)] that may start now: within the group's limit and each CLI's
        (counted by the model each running task really uses, backups included), a few at a time, one task per member at a time."""
        most, per_cli = task_limits(store)
        lanes = {}
        for t in running:
            lane = task_running_lane(store, run, t)
            lanes[lane] = lanes.get(lane, 0) + 1
        working = {j['botId'] for j in store.data['jobs'] if j.get('status') == 'running'}
        room = min(most - len(running), TASK_ATTEMPTS - run['attempts'], TASK_START_EVERY)
        chosen = []
        for t in ready:
            if len(chosen) >= room: break
            if t['assignee'] in working: continue  # it waits for its member instead of holding a place another task could use
            bot = store.find('bots', t['assignee']) or {}
            lane, use = task_lane(store, bot), None
            if lane[0] == AUTO:  # 自動選擇: pick its model now, among the CLIs that still have room
                try: options = pick_auto(store, t['spec'], bot=bot)[0]
                except ValueError as exc: t['status'] = 'failed'; t['note'] = str(exc)[:200]; continue
                fit = next(((p, m) for p, m in options if lanes.get((p, ''), 0) < per_cli.get(p, TASK_PER_CLI)), None)
                if not fit: continue
                lane, use = (fit[0], ''), fit
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
        step = dict(waitBusy=True, job=dict(dict(taskRole='host', taskRunId=run_ref), **({'origin': origin} if origin else {})), attachIds=[run.get('goalId')],
                    promptFor=lambda bot, writable: task_host_prompt(store, store.find('groups', group_id), store.find('groups', group_id)['taskRun'], bot, kind))
        turn = self._task_turn(group_id, run_id, host, step)
        if turn: self._group_job(group_id, turn)
        with store.lock:
            group = store.find('groups', group_id)
            if not group: return
            run = group.get('taskRun') or {}
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
            if not task: return
            attempt = dict(id=ID(), n=len(task['attempts']) + 1, jobId=None, state='starting', followUp=bool(task.get('answer')), startedAt=NOW())
            task['attempts'].append(attempt)  # counted in run['attempts'] when it was picked
            assignee, label = task['assignee'], '%d. %s' % (task['n'], task['title'])
            store.save()
        # A task is the host's instructions, not the user's: the member's reply counts as started by a Bot (or by whatever started the run).
        use = (run.get('use') or {}).get(task_id)
        step = dict(waitBusy=True, **({'use': use} if use else {}), job=dict(taskRole='worker', taskRunId=run['id'], taskId=task_id, taskTitle=label, origin=run['origin'] if run['origin'] != 'user' else 'bot'),
                    msg=dict(taskId=task_id), attachIds=[run.get('goalId')],
                    promptFor=lambda bot, writable: task_worker_prompt(store, store.find('groups', group_id), store.find('groups', group_id)['taskRun'], task, bot, writable))
        turn = self._task_turn(group_id, run_id, assignee, step)
        with store.lock:
            if not turn:
                attempt.update(state='failed', summary='這位成員這次不能接工作（被移出群組或沒有可用的模型）。', endedAt=NOW())
                if turn is None: task['status'] = 'failed'
                store.save(); self.task_poke(group_id); return
            attempt.update(jobId=turn['job']['id'], state='running')
            store.save()
        self._group_job(group_id, turn)
        with store.lock:
            group = store.find('groups', group_id)
            if group:
                group['activeJobIds'] = [x for x in group.get('activeJobIds') or [] if x != turn['job']['id']]; group['activeJobId'] = (group['activeJobIds'] or [None])[0]
            job = turn['job']
            said = attempt.get('summary') if attempt['state'] == 'reported' else task.get('question') if attempt['state'] == 'asked' else attempt.get('reason') if attempt['state'] == 'blocked' else ''
            if said and job['status'] == 'completed' and not (job.get('content') or '').strip():
                store.finish_message(job, said, 'completed')  # it reported and ended without words, as it was told to: its report is the reply
            if attempt['state'] == 'reported' and job['status'] == 'failed':
                # The CLI failed after the report: its files may not have reached the group. The task did not finish.
                attempt.update(state='failed', outcome='failed', summary=('回報後 CLI 出錯：%s。原本的回報：%s' % ((job.get('error') or '')[:150], attempt.get('summary') or ''))[:600])
            if attempt['state'] == 'running':  # the reply ended without a report
                why = job.get('error') or ('回覆被停止' if job['status'] == 'cancelled' else '沒有用 zook_task_done 回報就結束了')
                attempt.update(state='failed', outcome='failed', summary=why[:300], endedAt=NOW())
            if task['status'] == 'running':
                task['status'] = {'reported': 'done' if attempt.get('outcome') == 'succeeded' else 'failed', 'asked': 'asked', 'blocked': 'blocked'}.get(attempt['state'], 'failed')
                if job['status'] == 'cancelled' and attempt['state'] == 'failed': task['status'] = 'cancelled'
            if group: task_board_update(store, group)
            store.save()
        self.task_poke(group_id)


def task_key(task):
    """What the host has been told about a task: its attempt and state."""
    return '%s:%d:%s' % (task['id'], len(task['attempts']), task['status'])
