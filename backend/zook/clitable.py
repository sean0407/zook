# 每家 CLI 一份能力表 (#246): where its models come from, which thinking levels it takes, whether Zook can hold it to read-only (先規劃),
# which 存取範圍 it offers, its native tools and whether Zook can read its limits. Every menu for these (新增／編輯 Bot, 換模型重答,
# 一句話建團隊, the thinking level beside the message box, 設定's 預設 AI) is made from it. A new CLI needs a row here next to its entry in
# backend/providers.py CATALOG (cli_table_test checks the two agree). Loaded first by backend/server.py into one shared namespace.
EFFORT_CHOICES = (('standard', '標準', '交給模型自己決定，不另外指定'), ('fast', '快速', '想得少一點，回得快'),
                  ('medium', '中', '比快速仔細，用量比深入少'), ('deep', '深入', '想得更久、更仔細，用量較多'))
ACCESS_CHOICES = (('full', '整台 Mac', '可以讀寫任何檔案、執行任何指令，就像你自己在用這台 Mac'), ('folder', '指定資料夾', '只能讀寫你選的那個資料夾'),
                  ('workspace', '只限 Bot 工作區', '只能讀寫 Zook 為它準備的資料夾'))
ALL_EFFORTS = tuple(x[0] for x in EFFORT_CHOICES)
ALL_ACCESS = tuple(x[0] for x in ACCESS_CHOICES)
_ZOOK = ('multi', 'browser')  # features: 多代理協作, 圖片生成, Zook's own browser (abilities.py FEATURES)
CLI_TABLE = {
    'codex': dict(models='cli', modelsHow='向這台 Mac 上的 Codex 查詢（model/list）；讀不到時用 Codex 上次記下的清單。', modelGroups=False,
                  efforts=ALL_EFFORTS, effortFlag=('-c', 'model_reasoning_effort="{level}"'), effortNote='',
                  readOnly=True, access=ALL_ACCESS, gated=False, nativeTools=True, zookTools=True, features=_ZOOK + ('image',),
                  quota=True, quotaHow='讀 Codex 帳號的 5 小時與每週額度。'),
    'claude': dict(models='alias', modelsHow='Opus／Sonnet／Haiku 三個別名（永遠指向最新版），加上你最近用過的型號。', modelGroups=False,
                   efforts=ALL_EFFORTS, effortFlag=('--effort', '{level}'), effortNote='',
                   readOnly=True, access=('full',), gated=True, nativeTools=True, zookTools=True, features=_ZOOK,
                   quota=True, quotaHow='讀 Claude 回覆時附帶的額度。'),
    'grok': dict(models='cli', modelsHow='向這台 Mac 上的 Grok 查詢（grok models）。', modelGroups=False,
                 efforts=ALL_EFFORTS, effortFlag=('--reasoning-effort', '{level}'), effortNote='',
                 readOnly=True, access=ALL_ACCESS, gated=False, nativeTools=True, zookTools=True, features=_ZOOK + ('image',),
                 quota=True, quotaHow='讀 Grok 的每週額度（沒有恢復時間）。'),
    'antigravity': dict(models='cli', modelsHow='向這台 Mac 上的 Antigravity 查詢（agy models）；額外帳號也用預設帳號的清單。', modelGroups=False,
                        efforts=ALL_EFFORTS, effortFlag=('--effort', '{level}'),
                        effortNote='型號名稱裡的 High／Medium／Low 是型號本身的強度；選「標準」就照型號，選其他檔位時 Zook 會另外指定給 Antigravity。',
                        readOnly=True, access=ALL_ACCESS, gated=False, nativeTools=True, zookTools=True, features=('browser',),
                        quota=True, quotaHow='讀 Antigravity 各類模型的額度。'),
    'cursor': dict(models='cli', modelsHow='向你的 Cursor 查詢（cursor-agent models），能用哪些看你的 Cursor 方案；型號很多，依家族分組、可以搜尋。', modelGroups=True,
                   efforts=('standard',), effortNote='Cursor 的思考強度寫在型號名稱裡（例如 Low、High、Thinking），選型號就是選強度。',
                   readOnly=True, access=('full',), gated=True, nativeTools=True, zookTools=True, features=_ZOOK,
                   quota=False, quotaHow='Cursor 不提供額度給其他程式讀，只能看 Zook 記下的用量。'),
    'gemini': dict(models='fixed', modelsHow='Gemini CLI 沒有列出型號的指令，所以列出它認得的三個別名：Pro、Flash、Flash-Lite（永遠指向最新版）。', modelGroups=False,
                   efforts=('standard',), effortNote='Gemini CLI 沒有調整思考強度的選項，由它自己決定。',
                   readOnly=False, access=ALL_ACCESS, gated=False, nativeTools=True, zookTools=False, features=(),
                   quota=False, quotaHow='Gemini CLI 不提供額度給其他程式讀，只能看 Zook 記下的用量。'),
    'custom': dict(models='config', modelsHow='新增這個 CLI 時填的型號清單；沒填就用它建議的。', modelGroups=False,
                   efforts=('standard',), effortNote='自訂的 CLI 沒有 Zook 認得的思考強度選項。',
                   readOnly=False, access=ALL_ACCESS, gated=False, nativeTools=True, zookTools=False, features=(),
                   quota=False, quotaHow='自訂的 CLI 沒有額度可讀，只能看 Zook 記下的用量。'),
}


def cli_row(provider):
    """The table row for a provider id (a built-in CLI, or any custom one)."""
    return CLI_TABLE.get(provider) if provider in CLI_TABLE and provider != 'custom' else CLI_TABLE['custom']


def cli_row_view(store, provider):
    """Lock held or not. The row for the window: lists instead of tuples, without how the CLI is called; a level this version lost is said."""
    row = {k: list(v) if isinstance(v, tuple) else v for k, v in cli_row(provider).items() if k != 'effortFlag'}
    if len(row['efforts']) > 1 and not ability_on(store, provider, 'effort'):
        row.update(efforts=['standard'], effortNote='這個版本暫時無法調整思考強度，先用「標準」。')
    return row


def cli_table_view(store):
    """Lock held. The choices with their words, and a row for every CLI Zook knows (built-in and custom)."""
    ids = list(P.CATALOG) + [x['id'] for x in P.custom_list(store.data) if isinstance(x.get('id'), str)]
    return dict(efforts=[dict(id=i, name=n, hint=h) for i, n, h in EFFORT_CHOICES], access=[dict(id=i, name=n, hint=h) for i, n, h in ACCESS_CHOICES],
                clis={pid: cli_row_view(store, pid) for pid in ids})


def _family(model):
    name = str(model.get('name') or '') if model.get('name') and model.get('name') != model.get('id') else str(model.get('id') or '')
    words = re.split(r'[\s（(]+', name.strip())
    first = re.split(r'[-_.\d]', words[0] or '')[0] or words[0] if words else ''
    return (first.upper() if first.lower() in ('gpt', 'glm', 'oss') else first[:1].upper() + first[1:]) or '其他', words[1:2]


_LEVEL_WORDS = {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'extra', 'max', 'fast', 'thinking', 'preview'}


def add_families(models):
    """#220: each model's family for grouping a long list, from its shown name (「Claude Opus 5 1M」 → Claude); a family over 40 is split by its next word."""
    found = [(m, *_family(m)) for m in models]
    sizes = {}
    for _, first, _ in found: sizes[first] = sizes.get(first, 0) + 1
    sub = lambda first, rest: first + ' ' + rest[0] if sizes[first] > 40 and rest and re.fullmatch(r'[A-Za-z]+', rest[0]) and rest[0].lower() not in _LEVEL_WORDS else first
    subs = {}
    for _, first, rest in found: subs[sub(first, rest)] = subs.get(sub(first, rest), 0) + 1
    for model, first, rest in found:
        name = sub(first, rest)
        model['family'] = name if subs[name] >= 5 else first  # a line of its own (Opus, Sonnet, Mini), not a level (Low, High) or a lone model
    return models


def model_view(provider):
    """/api/models: the CLI's list (library.py model_list), each model with its family for grouping."""
    found = model_list(provider); add_families(found['models'])
    return found
