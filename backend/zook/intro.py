# A Bot's first words: a spoken greeting in its own voice and a few questions you might ask it, shown in an empty conversation.
# Loaded by backend/server.py into one shared namespace.
#
# Made once in the background when the Bot is created or what it is (name, job title, persona, work instructions) changes.
# It does not go through a normal reply: Zook starts Codex or Claude itself with every tool, Skill, connector and web search
# turned off, read-only, in an empty folder made for this one run and removed afterwards, only on a sign-in known to be a
# subscription, never past a used-up budget or limit, and for two minutes at most. The answer stays in memory until it has
# been checked; nothing lands in the Bot's conversations or in the job list. Other CLIs get a plain hello without questions.
import unicodedata as _unicodedata

INTRO_FIELDS = ('name', 'jobTitle', 'persona', 'instructions')
INTRO_KINDS = ('codex', 'claude')  # the CLIs whose tools Zook can switch off completely
INTRO_ASK = ('你是下面這個 Bot。依它的人格和工作，用它自己的口吻寫：\n'
             '1. greeting：見到使用者時說的一句口語化招呼（最多 40 字，像真人開口，不要長篇自我介紹）。\n'
             '2. questions：使用者最可能想問它的 3 個問題，用使用者的口吻（每題最多 25 字）。\n'
             '只輸出一個 JSON 物件，不要其他文字：{"greeting": "...", "questions": ["...", "...", "..."]}\n\n')
INTRO_RETRY = 600  # seconds before a failed greeting is tried again
INTRO_TIMEOUT = 120  # seconds one greeting may take
INTRO_QUEUE_MOST = 50
INTRO_CODEX_OFF = ('shell_tool', 'unified_exec', 'apps', 'plugins', 'browser_use', 'computer_use', 'skill_search', 'memories', 'multi_agent', 'image_generation')


def intro_prompt(bot):
    lines = ['名稱：' + str(bot.get('name') or '')[:100]]
    if bot.get('jobTitle'): lines.append('職稱：' + str(bot['jobTitle'])[:40])
    if bot.get('persona'): lines.append('人格：' + str(bot['persona'])[:4000])
    if bot.get('instructions'): lines.append('工作指示：' + str(bot['instructions'])[:3000])
    return INTRO_ASK + '\n'.join(lines)


def intro_source(bot):
    """What the greeting was made from (exactly what is sent); it is made again only when this changes."""
    return hashlib.sha256(intro_prompt(bot).encode('utf-8', 'replace')).hexdigest()[:16]


def _intro_line(value, size):
    """One plain line: no control or direction-changing characters, never a slash command, nothing that cannot be saved."""
    if not isinstance(value, str): return ''
    clean = ''.join(ch for ch in value if _unicodedata.category(ch) not in ('Cc', 'Cf', 'Cs', 'Co') or ch in '\n\t ')
    flat = ' '.join(clean.split()).lstrip('/').strip()
    return flat if len(flat) <= size else flat[:size] + '…'


def parse_intro(text):
    """{greeting, questions} from the model's reply, or None. Only plain strings count; at most three questions."""
    text = str(text or '')[:20000]; start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start: return None
    try: data = json.loads(text[start:end + 1])
    except (ValueError, RecursionError): return None
    if not isinstance(data, dict): return None
    greeting = _intro_line(data.get('greeting'), 80)
    raw = data.get('questions') if isinstance(data.get('questions'), list) else []
    questions = [q for q in (_intro_line(x, 40) for x in raw[:10]) if q][:3]
    return dict(greeting=greeting, questions=questions) if greeting and questions else None


def intro_valid(intro):
    """A stored greeting the window may show (also after an import or a restore): it must already be in the clean form."""
    if not isinstance(intro, dict) or not isinstance(intro.get('greeting'), str) or not isinstance(intro.get('questions'), list): return False
    return (_intro_line(intro['greeting'], 80) == intro['greeting'] != '' and 0 < len(intro['questions']) <= 3
            and all(isinstance(q, str) and q and _intro_line(q, 40) == q for q in intro['questions']))


def intro_blocked(store, bot, provider, account_id):
    """Lock held. Why a greeting is not made now, or ''. Only a sign-in known to be a subscription; never past a used-up budget or limit."""
    if provider_kind(provider) not in INTRO_KINDS: return '這個 CLI 不能完全關閉工具'
    account = find_account(account_id, provider) if account_id else None
    if account_id and not account: return '帳號已移除'
    if account and account.get('type') != 'login': return 'API 計費'
    key = auto_account_key(account) if account else provider
    if not auto_ready(store, key): return '還沒確認是訂閱帳號'
    if budget_state(store, provider) == 'over': return '用量預算已用完'
    snap = (store.data.get('quota') or {}).get(key) or {}
    if quota_exhausted(store, key) or (isinstance(snap, dict) and snap.get('limitReached')): return '額度已用完'
    return ''


def intro_args(binary, kind, model):
    if kind == 'codex':
        args = [binary, 'exec', '--json', '--sandbox', 'read-only', '--skip-git-repo-check', '--ephemeral', '--ignore-user-config', '--color', 'never', '-c', 'project_doc_max_bytes=0']
        for feature in INTRO_CODEX_OFF: args += ['--disable', feature]
        args += ['--enable', 'skip_host_skill_discovery', '-c', 'web_search="disabled"']
        return args + (['--model', model] if model else []) + ['-']
    return [binary, '--print', '--safe-mode', '--strict-mcp-config', '--no-session-persistence', '--tools', '', '--output-format', 'stream-json', '--verbose'] + (['--model', model] if model else [])


def intro_env(provider, account):
    """The CLI's own sign-in, without any API key from Zook's environment."""
    env = provider_env(provider, account)
    for names in ACCOUNT_KEYS.values():
        for name in names: env.pop(name, None)
    return env


class Intros:
    """Mixed into App."""
    def want_intro(self, bot_id):
        """Queue a Bot for its greeting. One worker makes them one at a time."""
        with self.store.lock:
            queue = self.__dict__.setdefault('intro_queue', [])
            if bot_id not in queue and len(queue) < INTRO_QUEUE_MOST: queue.append(bot_id)
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

    def _intro_choice(self, bot):
        """Lock held. (provider, model, account id) for this Bot's greeting, or (None, reason)."""
        store = self.store
        if bot.get('provider') == AUTO:
            try: chain = pick_auto(store, '請打招呼', plan=True, bot=bot)[0]
            except ValueError as exc: return None, str(exc)
            for p, m, *rest in chain:
                if not intro_blocked(store, bot, p, rest[0] if rest else ''): return (p, m, rest[0] if rest else ''), ''
            return None, '沒有可用的訂閱帳號'
        provider, model = bot_model(store, bot); account = bot.get('account') if find_account(bot.get('account'), provider) else ''
        why = intro_blocked(store, bot, provider, account or '')
        return ((provider, model, account or ''), '') if not why else (None, why)

    def make_intro(self, bot_id):
        store = self.store; failed = self.__dict__.setdefault('intro_failed', {})
        for key in [k for k, (_, at) in failed.items() if time.time() - at > 86400]: failed.pop(key, None)
        with store.lock:
            bot = store.find('bots', bot_id)
            if not bot: return
            source = intro_source(bot)
            if (bot.get('intro') or {}).get('source') == source: return  # still fits
            if failed.get(bot_id, ('', 0))[0] == source and time.time() - failed[bot_id][1] < INTRO_RETRY: return
            needs_status = 'autoStatus' not in store.data or bot.get('provider', '') not in (AUTO, '') and bot_model(store, bot)[0] not in (store.data.get('autoStatus') or {})
        if needs_status: refresh_auto_status(store)  # which sign-ins are subscriptions: learnt once, outside the lock
        with store.lock:
            bot = store.find('bots', bot_id)
            if not bot or intro_source(bot) != source: return
            choice, why = self._intro_choice(bot)
            if not choice or not find_cli(choice[0]): failed[bot_id] = (source, time.time()); return
            provider, model, account_id = choice; prompt = intro_prompt(bot)
            account = find_account(account_id, provider) if account_id else None
        folder = pathlib.Path(tempfile.mkdtemp(prefix='intro-', dir=str(self._intro_tmp())))
        try: parsed = self._intro_run(find_cli(provider), provider_kind(provider), model, intro_env(provider, account), folder, prompt)
        finally: shutil.rmtree(str(folder), ignore_errors=True)
        made = parse_intro(parsed.get('content')) if parsed and not parsed.get('isError') else None
        if parsed and parsed.get('usage'):
            try: budget_add(self, provider, parsed['usage'])  # it counts toward the month's budget like any reply
            except Exception: pass
        with store.lock:
            bot = store.find('bots', bot_id)
            if not made: failed[bot_id] = (source, time.time()); return
            if bot and intro_source(bot) == source:  # the Bot did not change while it was being made
                old = bot.get('intro'); bot['intro'] = dict(made, source=source, madeAt=NOW()); failed.pop(bot_id, None)
                try: store.save()
                except (OSError, ValueError, TypeError):
                    if old is None: bot.pop('intro', None)
                    else: bot['intro'] = old

    def _intro_tmp(self):
        folder = self.store.dir / 'intro-runs'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        return folder

    def _intro_run(self, binary, kind, model, env, folder, prompt):
        """One run of the CLI with everything switched off. Its output is read in memory only."""
        try: proc = subprocess.Popen(intro_args(binary, kind, model), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=str(folder), env=dict(env, PWD=str(folder)), start_new_session=True)
        except OSError: return None
        try: out, _ = proc.communicate(prompt.encode('utf-8', 'replace'), timeout=INTRO_TIMEOUT)
        except subprocess.TimeoutExpired:
            try: os.killpg(proc.pid, signal.SIGKILL)  # the leader is not reaped yet, so the group is still its own
            except OSError: pass
            proc.wait(); return None
        return parse_cli_output(kind, out[:1000000].decode('utf-8', 'replace')) if proc.returncode == 0 else None
