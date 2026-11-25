# Schedules: sending each one when its time comes, and keeping its history. Loaded by backend/server.py into one shared namespace.


class Scheduling:
    def run_schedule(self, item, inventory, extra=''):
        """Send a schedule's message now and add it to the schedule's history. Returns None when sent,
        or the reason it could not be. Raises Busy when the Bot or group is working on something else. Lock held."""
        run = dict(kind='group' if item.get('groupId') else 'bot', targetId=item.get('groupId') or item.get('botId'), status='running')
        try:
            if item.get('groupId'):
                group = self.store.find('groups', item['groupId'])
                if not group: raise RuntimeError('找不到這個群組。')
                if group['status'] == 'running': raise Busy('群組正在討論，等討論結束再執行。')
                run['runId'] = self.post_group_message(group, item['content'] + extra, author='排程')
                run['messageId'] = next(m['id'] for m in reversed(group['messages']) if m['role'] == 'user')
            else:
                bot = self.store.find('bots', item.get('botId'))
                if not bot: raise RuntimeError('找不到這個 Bot。')
                run['chatId'] = schedule_chat(bot)
                run['jobId'] = self.send_to_bot(bot, item['content'] + extra + (QUIET_NOTE if item.get('quiet') else ''), inventory, author='排程', chat_id=run['chatId'], origin='trigger' if extra else 'schedule')['id']
                run['messageId'] = next(m['id'] for m in reversed(chat_messages(bot, run['chatId'])) if m['role'] == 'user')
        except Busy: raise
        except (ValueError, RuntimeError) as exc:
            run.update(status='failed', reason=str(exc)[:300])
        schedule_add_run(item, run)
        if run['status'] == 'failed': self.notify_run(run, '失敗：' + run['reason'])
        return run.get('reason')

    def settle_schedule_runs(self):
        """Finish the history entries of schedules whose reply has come in. Lock held."""
        store = self.store
        for item in store.data['schedules']:
            for run in item.get('runs') or []:
                if run.get('status') != 'running': continue
                if run.get('kind') == 'group':
                    group = store.find('groups', run.get('targetId'))
                    if group and group.get('runId') == run.get('runId'): continue  # still discussing
                    messages = (group or {}).get('messages') or []
                    after = next((i for i, m in enumerate(messages) if m['id'] == run.get('messageId')), len(messages))
                    replies = [m for m in messages[after + 1:] if m['role'] == 'assistant' and m.get('status') == 'completed' and m.get('content')]
                    outcome = ('done', '', replies[-1]['content']) if replies else ('failed', '群組沒有產生回覆。', '')
                else:
                    job = store.find('jobs', run.get('jobId'))
                    if job and job['status'] == 'running': continue
                    if job and job['status'] == 'completed': outcome = ('done', '', job.get('content') or '')
                    elif job and job['status'] == 'cancelled': outcome = ('failed', '回覆被停止了。', '')
                    else: outcome = ('failed', (job or {}).get('error') or '找不到這次的回覆。', '')
                if run.get('approvalExpired') and outcome[0] == 'done': outcome = ('done', '有動作等你核准超過 24 小時，視為拒絕。', outcome[2])
                run.update(status=outcome[0], reason=outcome[1], summary=outcome[2][:300], finishedAt=NOW())
                if outcome[0] == 'failed': item.update(lastStatus='failed', lastError=outcome[1])
                if outcome[0] == 'done' and item.get('quiet') and run.get('kind') != 'group' and not outcome[1] and is_quiet_reply(outcome[2]):
                    run['quiet'] = True; store.save(); continue  # nothing new: it is in the history, and nobody is interrupted
                self.notify_run(run, first_sentence(outcome[2]) or '已完成。' if outcome[0] == 'done' else '失敗：' + outcome[1])
                store.save()

    def run_schedules(self, now=None):
        """Send every schedule whose time has come. Runs a few times a minute while Zook is open."""
        now = now or datetime.datetime.now(); store = self.store
        def waiting():
            for item in store.data['schedules']:
                due = item.get('on') and (item.get('trigger') or 'time') == 'time' and schedule_last_due(item, now)
                if due and due.isoformat() > item.get('since', ''): yield item, due
        with store.lock:
            self.settle_schedule_runs()
            if not list(waiting()): return
        inventory = inventory_for(store)
        def handled(item, due, status, error=''):
            item.pop('held', None)
            item.update(since=due.isoformat(), lastAt=NOW(), lastStatus=status, lastError=error)
            if item.get('repeat') == 'once': item.update(on=False, done=True)  # a one-time schedule is finished either way
        with store.lock:
            for item, due in list(waiting()):
                late = (now - due).total_seconds()
                missed = None
                if late > 86400 or (late > 180 and not item.get('catchUp', True) and not item.get('held')): missed = '到時間時 Zook 沒有開著。'
                else:
                    try: problem = self.run_schedule(item, inventory)
                    except Busy:
                        item['held'] = True  # the Bot or group is busy with something else: try again shortly
                        if late > 6 * 3600: missed = '一直在忙，這次沒有執行。'
                        else: continue
                if missed:
                    run = schedule_add_run(item, dict(kind='group' if item.get('groupId') else 'bot', targetId=item.get('groupId') or item.get('botId'), status='missed', reason=missed))
                    self.notify_run(run, '錯過：' + missed)
                    handled(item, due, 'missed', missed); continue
                handled(item, due, 'failed' if problem else 'sent', problem or '')
            store.save()

    def schedule_loop(self):
        wait = float(os.environ.get('ZOOK_SCHEDULE_TICK') or 15)
        while True:
            time.sleep(wait)
            for step in (self.run_schedules, self.run_triggers, self.sync_tick, lambda: live_tidy(self), lambda: bg_sweep(self), lambda: usage_detect_tick(self)):  # 自動偵測使用量: usagewatch.py
                try: step()
                except Exception: pass
            try:
                with self.store.lock:
                    backup_daily(self.store); sweep_uploads(self.store)  # attachments never sent, once an hour even when nothing replies (uploadkeep.py)
                    if time.monotonic() - self.store.__dict__.get('_chat_swept', 0) >= CHAT_SWEEP_EVERY: self.store.save_chats()  # the once-a-minute look happens even when nothing else saves
            except Exception: pass
