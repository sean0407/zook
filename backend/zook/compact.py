# Conversations that have grown too long for a model to read: the earlier part is turned into a summary and the CLI starts a fresh
# conversation from it. Loaded by backend/server.py into one shared namespace.
#
# Every message stays on screen and in the data file; only what is handed to the model changes. Two things start it:
#   - the CLI says the conversation is too long (any CLI): tidy up and try that reply once more;
#   - two replies in a row report more input than the limit (CLIs that do not tidy their own conversations).
# Claude and Codex shorten their own long conversations, so Zook leaves those alone unless they report the error.
COMPACT_LIMITS = dict(antigravity=600000)
COMPACT_DEFAULT = 150000
COMPACT_SELF = ('claude', 'codex')
SUMMARY_ASK = ('把下面這段對話整理成一份摘要，給之後接手這段對話的你自己看。保留：使用者的目標與偏好、已經決定的事、重要的事實、數字、名稱與檔案路徑、還沒完成的事。'
               '不要加入對話裡沒有的內容，不要使用任何工具，只輸出摘要本身，不超過八百字。\n\n對話：\n')


def compact_on(store): return store.data['settings'].get('autoCompact') is not False


def compact_limit(kind):
    try: return int(os.environ['ZOOK_COMPACT_AT'])
    except (KeyError, ValueError): return COMPACT_LIMITS.get(kind, COMPACT_DEFAULT)


def can_compact(store, job):
    """A direct conversation with a Bot, with the setting on. Group discussions and Zook's own helper runs are left out."""
    return compact_on(store) and bool(job.get('chatId')) and not job.get('groupId') and not job.get('internal')


def chat_record(bot, chat_id): return next((c for c in bot.get('chats') or [] if c['id'] == chat_id), None)


def chat_context(bot, chat_id, messages):
    """The saved conversation as it is handed to a CLI that starts fresh: the summary of the earlier part, if there is one, then what came after it."""
    summary = (chat_record(bot, chat_id) or {}).get('summary')
    at = next((i for i, m in enumerate(messages) if m.get('id') == summary.get('upTo')), None) if summary else None
    if at is None: return conversation_context(messages)
    return '（更早的對話已整理成這份摘要）\n%s\n（摘要之後的對話）\n%s' % (summary['text'], conversation_context(messages[at + 1:]))


def compact_note_usage(store, job, kind, usage):
    """Lock held, after a reply. Remembers how much the model was given, and decides whether the next message should start from a summary."""
    bot = store.find('bots', job['botId']); chat = chat_record(bot or {}, job.get('chatId'))
    used = (usage or {}).get('input')
    if not chat or job.get('groupId') or job.get('internal') or not isinstance(used, int): return
    before = chat.pop('compactedFrom', None)
    if before and used >= 0.7 * before:  # the summary did not make it smaller: doing it again would not either
        chat['compactOff'] = '整理成摘要後用量沒有明顯下降，已停止自動整理這個對話。'
    chat['ctx'] = ((chat.get('ctx') or [])[-1:] + [used]) if not before else [used]
    if compact_on(store) and kind not in COMPACT_SELF and not chat.get('compactOff') and len(chat['ctx']) == 2 and min(chat['ctx']) >= compact_limit(kind): chat['compactDue'] = True


class Compacting:
    """Mixed into App."""
    def compact_chat(self, job_id, prompt, model, bot, inventory):
        """Summarise the conversation before this message and return the prompt that starts from the summary.
        When that is not possible the prompt comes back unchanged and the reply goes on as usual."""
        store = self.store
        with store.lock:
            job = store.find('jobs', job_id); live = store.find('bots', (job or {}).get('botId')); chat = chat_record(live or {}, (job or {}).get('chatId'))
            if not job or not chat: return prompt
            messages = chat_messages(live, chat['id'])
            ask = next((i for i, m in enumerate(messages) if m.get('id') == job.get('messageId')), len(messages)) - 1  # the user's message is just before the reply
            earlier = [m for m in messages[:max(0, ask)] if m.get('content')]
            if len(earlier) < 4: chat.pop('compactDue', None); return prompt
            old = chat.get('summary') or {}
            start = next((i + 1 for i, m in enumerate(earlier) if m.get('id') == old.get('upTo')), 0)
            lines, size = [], 0
            for m in reversed(earlier[start:]):
                line = m['role'] + ': ' + m['content'][:4000]
                if size + len(line) > 2 * MAX_CONTEXT: break
                lines.append(line); size += len(line)
            text = (('（先前的摘要）\n' + old['text'] + '\n') if old.get('text') and start else '') + '\n'.join(reversed(lines))
            helper = dict(id=ID(), botId=live['id'], messageId='', status='running', content='', createdAt=NOW(), toolCalls=[], approvals=[], plan=True, noResume=True, internal='summary')
            store.data['jobs'].append(helper)
        try: self._run_attempt(helper['id'], SUMMARY_ASK + text, model[0], model[1], bot, inventory, True)
        finally:
            with store.lock:
                store.data['jobs'][:] = [j for j in store.data['jobs'] if j['id'] != helper['id']]
        with store.lock:
            job = store.find('jobs', job_id); live = store.find('bots', (job or {}).get('botId')); chat = chat_record(live or {}, (job or {}).get('chatId'))
            if not job or not chat or job['status'] != 'running': return prompt
            chat.pop('compactDue', None)
            summary = (helper.get('content') or '').strip() if helper.get('status') == 'completed' else ''
            asked = find_message(live, job.get('askedId')) if job.get('askedId') else None
            if asked is None:
                messages = chat_messages(live, chat['id'])
                at = next((i for i, m in enumerate(messages) if m.get('id') == job.get('messageId')), 0)
                asked = messages[at - 1] if at > 0 else None
            if not summary:
                chat['compactFails'] = chat.get('compactFails', 0) + 1
                if chat['compactFails'] >= 2:
                    chat['compactOff'] = '自動整理對話失敗兩次，已停止。對話太長時請開一個新對話。'
                    reply = find_message(live, job['messageId'])
                    if reply: reply['note'] = '；'.join(x for x in (reply.get('note'), chat['compactOff']) if x)
                store.save(); return prompt
            chat['summary'] = dict(text=summary[:6000], upTo=earlier[-1]['id'], at=NOW())
            chat['compactedFrom'] = (chat.get('ctx') or [0])[-1]; chat['compactFails'] = 0; chat.pop('native', None)
            job['noResume'] = True
            if asked is not None: asked['compacted'] = True  # the window draws a line here
            build = self.__dict__.get('prompt_builders', {}).get(job_id)
            store.save()
            return build()[0] if build else prompt
