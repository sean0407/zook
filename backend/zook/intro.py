# A Bot's first words: a spoken greeting in its own voice and a few questions you might ask it, shown in an empty conversation.
# Loaded by backend/server.py into one shared namespace.
#
# Made once in the background when the Bot is created or what it is (name, job title, persona, work instructions) changes,
# with the Bot's own model, read-only and without tools; nothing lands in its conversations. A Bot made before this existed
# asks for it the first time its empty conversation is opened.
INTRO_FIELDS = ('name', 'jobTitle', 'persona', 'instructions')
INTRO_ASK = ('你是下面這個 Bot。依它的人格和工作，用它自己的口吻寫：\n'
             '1. greeting：見到使用者時說的一句口語化招呼（最多 40 字，像真人開口，不要長篇自我介紹）。\n'
             '2. questions：使用者最可能想問它的 3 個問題，用使用者的口吻（每題最多 25 字）。\n'
             '只輸出一個 JSON 物件，不要其他文字：{"greeting": "...", "questions": ["...", "...", "..."]}\n\n')
INTRO_RETRY = 600  # seconds before a failed greeting is tried again


def intro_source(bot):
    """What the greeting was made from; it is made again only when this changes."""
    return hashlib.sha256(json.dumps([str(bot.get(k) or '') for k in INTRO_FIELDS], ensure_ascii=False).encode('utf-8')).hexdigest()[:16]


def _intro_line(value, size):
    flat = ' '.join(str(value).split()) if isinstance(value, str) else ''
    return flat if len(flat) <= size else flat[:size] + '…'


def parse_intro(text):
    """{greeting, questions} from the model's reply, or None. Only plain strings count; at most three questions."""
    text = str(text or ''); start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start: return None
    try: data = json.loads(text[start:end + 1])
    except ValueError: return None
    if not isinstance(data, dict): return None
    greeting = _intro_line(data.get('greeting'), 80)
    questions = [q for q in (_intro_line(x, 40) for x in data.get('questions') or [] if isinstance(x, str)) if q][:3] if isinstance(data.get('questions'), list) else []
    return dict(greeting=greeting, questions=questions) if greeting and questions else None


def intro_prompt(bot):
    lines = ['名稱：' + str(bot.get('name') or '')]
    if bot.get('jobTitle'): lines.append('職稱：' + str(bot['jobTitle']))
    if bot.get('persona'): lines.append('人格：' + str(bot['persona'])[:4000])
    if bot.get('instructions'): lines.append('工作指示：' + str(bot['instructions'])[:3000])
    return INTRO_ASK + '\n'.join(lines)


class Intros:
    """Mixed into App."""
    def want_intro(self, bot_id):
        """Queue a Bot for its greeting. One worker makes them one at a time, so a new team of Bots does not start a crowd of CLIs."""
        with self.store.lock:
            queue = self.__dict__.setdefault('intro_queue', [])
            if bot_id not in queue: queue.append(bot_id)
            if self.__dict__.get('intro_working'): return
            self.intro_working = True
        threading.Thread(target=self._intro_worker, daemon=True).start()

    def _intro_worker(self):
        while True:
            with self.store.lock:
                if not self.intro_queue: self.intro_working = False; return
                bot_id = self.intro_queue.pop(0)
            try: self.make_intro(bot_id)
            except Exception: pass  # a greeting is a nicety: never let it stop anything else

    def make_intro(self, bot_id):
        store = self.store; failed = self.__dict__.setdefault('intro_failed', {})
        with store.lock:
            bot = store.find('bots', bot_id)
            if not bot: return
            source = intro_source(bot)
            if (bot.get('intro') or {}).get('source') == source: return  # still fits
            if failed.get(bot_id, ('', 0))[0] == source and time.time() - failed[bot_id][1] < INTRO_RETRY: return
            try: provider, model, account = pick_auto(store, '請打招呼', plan=True, bot=bot)[0][0] if bot.get('provider') == AUTO else bot_model(store, bot) + (None,)
            except ValueError: failed[bot_id] = (source, time.time()); return
            if provider_kind(provider) not in PLAN_KINDS or not find_cli(provider): failed[bot_id] = (source, time.time()); return  # only a CLI Zook can hold to read-only
            helper = dict(id=ID(), botId=bot_id, messageId='', status='running', content='', createdAt=NOW(), toolCalls=[], approvals=[], plan=True, noResume=True, internal='intro')
            store.data['jobs'].append(helper); runner = copy.deepcopy(bot)
            if account is not None: runner['account'] = account
        try: self._run_attempt(helper['id'], intro_prompt(runner), provider, model, runner, inventory_for(store), True)
        finally:
            with store.lock: store.data['jobs'][:] = [j for j in store.data['jobs'] if j['id'] != helper['id']]
        made = parse_intro(helper.get('content')) if helper.get('status') == 'completed' else None
        with store.lock:
            bot = store.find('bots', bot_id)
            if not made: failed[bot_id] = (source, time.time()); return
            if bot and intro_source(bot) == source:  # the Bot did not change while it was being made
                bot['intro'] = dict(made, source=source, madeAt=NOW()); failed.pop(bot_id, None); store.save()
