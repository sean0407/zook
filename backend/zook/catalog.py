# 連接器目錄: official remote MCP services, each run by the company it belongs to. Every address here was checked against the live service.
# Loaded by backend/server.py into one shared namespace.
# auth: login = sign in from Zook in the browser; open = no sign-in; key = paste a key; manual = the service does not let apps register themselves yet.
def _c(ident, name, category, url, auth, about): return dict(id=ident, name=name, category=category, url=url, auth=auth, about=about)
CONNECTOR_CATALOG = [
    _c('notion', 'Notion', '筆記與文件', 'https://mcp.notion.com/mcp', 'login', '搜尋、讀取和編輯 Notion 的頁面與資料庫。'),
    _c('dropbox', 'Dropbox', '筆記與文件', 'https://mcp.dropbox.com/mcp', 'login', '搜尋和讀取 Dropbox 裡的檔案。'),
    _c('egnyte', 'Egnyte', '筆記與文件', 'https://mcp-server.egnyte.com/mcp', 'login', '搜尋和讀取 Egnyte 的公司檔案。'),
    _c('box', 'Box', '筆記與文件', 'https://mcp.box.com', 'manual', '搜尋和讀取 Box 裡的檔案。'),
    _c('granola', 'Granola', '筆記與文件', 'https://mcp.granola.ai/mcp', 'login', '查詢 Granola 的會議筆記。'),
    _c('fireflies', 'Fireflies', '筆記與文件', 'https://api.fireflies.ai/mcp', 'login', '查詢 Fireflies 的會議逐字稿與摘要。'),
    _c('asana', 'Asana', '專案管理', 'https://mcp.asana.com/v2/mcp', 'manual', '查看和建立 Asana 的任務與專案。'),
    _c('atlassian', 'Atlassian（Jira、Confluence）', '專案管理', 'https://mcp.atlassian.com/v1/mcp', 'login', '查詢和更新 Jira 議題與 Confluence 頁面。'),
    _c('linear', 'Linear', '專案管理', 'https://mcp.linear.app/mcp', 'login', '查詢、建立和更新 Linear 的議題。'),
    _c('monday', 'monday.com', '專案管理', 'https://mcp.monday.com/mcp', 'login', '查看和更新 monday.com 的看板與項目。'),
    _c('clickup', 'ClickUp', '專案管理', 'https://mcp.clickup.com/mcp', 'login', '查看和建立 ClickUp 的任務。'),
    _c('airtable', 'Airtable', '專案管理', 'https://mcp.airtable.com/mcp', 'login', '查詢和更新 Airtable 的資料表。'),
    _c('canva', 'Canva', '設計', 'https://mcp.canva.com/mcp', 'login', '搜尋、建立和匯出 Canva 設計。'),
    _c('figma', 'Figma', '設計', 'https://mcp.figma.com/mcp', 'manual', '讀取 Figma 設計稿的內容與規格。'),
    _c('cloudinary', 'Cloudinary', '設計', 'https://asset-management.mcp.cloudinary.com/mcp', 'login', '管理 Cloudinary 的圖片與影片素材。'),
    _c('webflow', 'Webflow', '設計', 'https://mcp.webflow.com/mcp', 'login', '管理 Webflow 網站的內容。'),
    _c('wix', 'Wix', '設計', 'https://mcp.wix.com/mcp', 'login', '管理 Wix 網站與商店。'),
    _c('slack', 'Slack', '溝通與客戶', 'https://mcp.slack.com/mcp', 'manual', '搜尋 Slack 訊息與頻道。'),
    _c('zoom', 'Zoom', '溝通與客戶', 'https://mcp.zoom.us/mcp/zoom/streamable', 'manual', '查詢 Zoom 會議與錄影。'),
    _c('intercom', 'Intercom', '溝通與客戶', 'https://mcp.intercom.com/mcp', 'login', '查詢 Intercom 的客戶對話。'),
    _c('hubspot', 'HubSpot', '溝通與客戶', 'https://mcp.hubspot.com', 'manual', '查詢 HubSpot 的聯絡人與交易。'),
    _c('close', 'Close', '溝通與客戶', 'https://mcp.close.com/mcp', 'login', '查詢和更新 Close 的客戶資料。'),
    _c('stripe', 'Stripe', '金流與財務', 'https://mcp.stripe.com', 'login', '查詢 Stripe 的客戶、付款與訂閱。'),
    _c('paypal', 'PayPal', '金流與財務', 'https://mcp.paypal.com/mcp', 'login', '查詢 PayPal 的交易與發票。'),
    _c('square', 'Square', '金流與財務', 'https://mcp.squareup.com/mcp', 'login', '查詢 Square 的訂單與商品。'),
    _c('ramp', 'Ramp', '金流與財務', 'https://ramp-mcp-remote.ramp.com/mcp', 'login', '查詢 Ramp 的支出資料。'),
    _c('plaid', 'Plaid', '金流與財務', 'https://api.dashboard.plaid.com/mcp/', 'login', '查看 Plaid 後台的整合狀態。'),
    _c('mercadopago', 'Mercado Pago', '金流與財務', 'https://mcp.mercadopago.com/mcp', 'login', '查詢 Mercado Pago 的整合文件與設定。'),
    _c('github', 'GitHub', '開發', 'https://api.githubcopilot.com/mcp/', 'key', '查看程式庫、議題和 PR。需要一組 GitHub 個人存取權杖。'),
    _c('sentry', 'Sentry', '開發', 'https://mcp.sentry.dev/mcp', 'login', '查詢 Sentry 的錯誤與事件。'),
    _c('vercel', 'Vercel', '開發', 'https://mcp.vercel.com', 'login', '查看 Vercel 的專案與部署。'),
    _c('supabase', 'Supabase', '開發', 'https://mcp.supabase.com/mcp', 'login', '管理 Supabase 專案與資料庫。'),
    _c('neon', 'Neon', '開發', 'https://mcp.neon.tech/mcp', 'login', '管理 Neon 的 Postgres 資料庫。'),
    _c('netlify', 'Netlify', '開發', 'https://netlify-mcp.netlify.app/mcp', 'login', '管理 Netlify 的網站與部署。'),
    _c('cloudflare', 'Cloudflare', '開發', 'https://bindings.mcp.cloudflare.com/mcp', 'login', '管理 Cloudflare Workers 的資源。'),
    _c('posthog', 'PostHog', '開發', 'https://mcp.posthog.com/mcp', 'login', '查詢 PostHog 的產品分析資料。'),
    _c('datadog', 'Datadog', '開發', 'https://mcp.datadoghq.com/api/unstable/mcp-server/mcp', 'login', '查詢 Datadog 的監控資料。'),
    _c('semgrep', 'Semgrep', '開發', 'https://mcp.semgrep.ai/mcp', 'login', '用 Semgrep 掃描程式碼的安全問題。'),
    _c('buildkite', 'Buildkite', '開發', 'https://mcp.buildkite.com/mcp', 'login', '查看 Buildkite 的建置狀態。'),
    _c('jam', 'Jam', '開發', 'https://mcp.jam.dev/mcp', 'login', '讀取 Jam 的錯誤回報。'),
    _c('pipedream', 'Pipedream', '開發', 'https://mcp.pipedream.net/v2', 'login', '透過 Pipedream 連到更多服務。'),
    _c('huggingface', 'Hugging Face', '查資料', 'https://huggingface.co/mcp', 'open', '搜尋 Hugging Face 的模型、資料集與論文。'),
    _c('context7', 'Context7', '查資料', 'https://mcp.context7.com/mcp', 'open', '查詢各種程式庫的最新文件。'),
    _c('deepwiki', 'DeepWiki', '查資料', 'https://mcp.deepwiki.com/mcp', 'open', '查詢公開 GitHub 專案的說明文件。'),
    _c('mslearn', 'Microsoft Learn', '查資料', 'https://learn.microsoft.com/api/mcp', 'open', '搜尋微軟官方技術文件。'),
]


def catalog_icon(item_id):
    """The company's own logo for a catalog entry, when Zook carries one."""
    name = 'asana.png' if item_id == 'asana' else 'cat-%s.png' % item_id
    return '/icons/' + name if (pathlib.Path(__file__).resolve().parents[1] / 'frontend' / 'icons' / name).is_file() else None


def catalog_icon_for_url(url):
    item = next((x for x in CONNECTOR_CATALOG if x['url'] == url), None)
    return catalog_icon(item['id']) if item else None


def catalog_view(store):
    """The catalog, with which entries are already in Zook."""
    with store.lock: have = {c.get('url'): c['id'] for c in store.data.get('connectors') or []}
    return dict(items=[dict(item, icon=catalog_icon(item['id']), vendor=item['name'].split('（')[0], added=item['url'] in have, connector='zook:' + have[item['url']] if item['url'] in have else '') for item in CONNECTOR_CATALOG])


_catalog_lock = threading.Lock()  # one add at a time, so a double click cannot make two connectors


def _catalog_check(item, key):
    """Connect once and list the tools, so a wrong key or an unreachable service is found before anything is saved."""
    client = None
    try:
        client = runtime_module().ProtocolClient(dict(transport='http', url=item['url'], headers={'Authorization': 'Bearer ' + key} if key else {}))
        client.tools()
    except Exception as exc:
        refused = type(exc).__name__ == 'AuthorizationNeeded'
        raise ValueError('%s 不接受這組金鑰，請確認後再貼一次。' % item['name'] if refused and key else '連不上 %s，請確認網路後再試。' % item['name'])
    finally:
        if client: client.close()


def catalog_add(app, item_id, key=None):
    """Add one catalog entry as a connector. Returns the connector's record and, for a sign-in, the page to open. Nothing is saved unless every step worked."""
    store = app.store
    item = next((x for x in CONNECTOR_CATALOG if x['id'] == item_id), None)
    if not item: raise LookupError('目錄裡沒有這個連接器。')
    if item['auth'] == 'manual': raise ValueError('%s 目前不開放應用程式自行登記，還不能一鍵連結。' % item['name'])
    key = key.strip() if item['auth'] == 'key' and isinstance(key, str) else ''
    if item['auth'] == 'key' and not key: raise ValueError('請貼上金鑰。')
    with _catalog_lock:
        with store.lock: existing = copy.deepcopy(next((c for c in store.data['connectors'] if c.get('url') == item['url']), None))
        if existing and existing.get('oauth'): return existing, ''
        if existing and item['auth'] == 'open': return existing, ''
        record = existing
        if not record: record, _ = connector_fields(dict(name=item['name'], transport='http', url=item['url'], **({'secret': key} if key else {})))
        url, auth = '', item['auth']
        if auth == 'login':
            try: url = oauth_begin(app, record)
            except RuntimeError as exc:
                if '不需要登入' not in str(exc): raise RuntimeError('%s 目前無法登入：%s' % (item['name'], exc))
                auth = 'open'  # the service turned out to need no sign-in
        if auth != 'login': _catalog_check(item, key)
        made = ''
        try:
            if key:
                if not record.get('secretId'): record['secretId'] = made = ID()
                record['secretName'] = 'Authorization'; secret_set(record['secretId'], key)
            with store.lock:
                taken = {c['name'] for c in store.data['connectors'] if c['id'] != record['id']}
                record['name'] = next((n for n in [record['name']] + ['%s %d' % (item['name'], i) for i in range(2, 200)] if n not in taken), '%s %s' % (item['name'], record['id'][:6]))
                store.data['connectors'] = [c for c in store.data['connectors'] if c['id'] != record['id']] + [record]
                st = store.data['settings']; st['sharedMcp'] = list(dict.fromkeys((st.get('sharedMcp') or []) + ['zook:' + record['id']]))
                store.save()
        except Exception:
            if made: secret_delete(made)  # the connector was not saved, so its key does not stay behind
            with store.lock: store.data['connectors'] = [c for c in store.data['connectors'] if c['id'] != record['id']] + ([existing] if existing else [])
            raise
        return record, url
