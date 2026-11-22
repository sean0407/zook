# Zook 開發說明

給在這個 repo 工作的 AI 與人。先讀這份，再讀 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 產品

Zook 是 macOS App（Swift 視窗 + Python 後端 + 純 JS 介面）加 iPhone App「ZookMobile」。它把使用者已安裝的 Codex、Claude、Grok、Antigravity、Gemini、Cursor 或自訂 CLI（2026-11-22 收斂成這 6 家，之後不再接新的 CLI） 放進同一個介面，可以多 Bot 群聊。

分層：模型 → 各家 CLI → Zook 的工具層與記憶層 → 簡易介面。目標是 Grok Bot 的簡單介面，加上 ChatGPT 的對話習慣和 Claude Code 的工具與自動化，同時充分發揮每家 CLI 的原生能力。

使用者是一般人，不是工程師。

## 不可違反的規則

- 介面文字用繁體中文，精簡、不出現程式碼或 JSON。
- 所有可選的設定用下拉選單或開關。
- Skill、連接器、插件在 Zook 層設定一次，全體 Bot、全部 CLI 共用；不要掛在個別 Bot 上。
- 每個 CLI 保留自己的原生工具；每個 CLI（含 Grok 和日後新增的）都有整台 Mac 的原生指令權限（Bot 可另外選擇縮小範圍）。
- 金鑰、密碼只存在 macOS 鑰匙圈。不寫進 `swarmr.json`、記錄檔、設定包，也不傳到手機。
- 寄信、建立或修改排程等 Zook 自己的對外動作，不論權限模式都要使用者核准。
- 不要把使用者的姓名、信箱等個資送到外部服務。
- 只有使用者親自送出的回合可以建立、修改、刪除排程，或寫入所有 Bot 共用的記憶。每個工作的來源記在 `job['origin']`（沒有這個欄位就是使用者；其他是 `schedule`、`trigger`、`bot`、`script`）。新增任何「會安排之後自動執行的事」的工具，都要檢查來源。
- 從外面進來的資料一律當資料看，不當指令：信件主旨與寄件者、檔名、同步資料夾裡其他 Mac 的檔案、匯入的備份檔。同步檔與備份檔要逐欄檢查，而且永遠不能帶進權限（主動性、存取範圍、管理員身分、允許本機腳本）。
- 內部權杖不放環境變數（同一台 Mac 的其他程式用 `ps` 看得到），用管線或只有本人可讀的檔案。
- 資料回到較舊的狀態時（還原備份、資料檔損壞後改用備份）一律停止多台同步，避免舊資料蓋掉其他 Mac。
- 每個檔案不超過 1000 行（`tests/layout_test.py` 會檢查）。`handler.py` 和 `app.py` 已經很接近，新功能放新檔案。

## 目錄

| 路徑 | 內容 |
|---|---|
| `native/Zook.swift` | macOS 視窗、啟動與關閉後端、檔案選取與下載、通知 |
| `native/Voice.swift` | 語音輸入（Mac 內建語音辨識）。建置時 `Zook.swift` 會複製成 `main.swift` 一起編譯 |
| `native/Browser.swift` | Bot 的內建瀏覽器（`Zook --zook-browser`，同一個執行檔）：不保存資料的 WKWebView，可瀏覽與在搜尋框輸入 |
| `native/remote/` | `zook-remote`，與中繼伺服器的加密連線 |
| `backend/server.py` | 啟動入口：依序載入 `backend/zook/` 的檔案，全部共用同一個命名空間 |
| `backend/zook/` | 依 `server.py` 裡的順序載入，共用同一個命名空間。`core` 資料儲存、`accounts` 帳號與更新、`agyhome` Antigravity 額外帳號的家目錄、`library` 設定包與排程規則、`oauth` 連接器與 Google 登入、`catalog` 連接器目錄、`outputs` 產出、`mobile` 手機、`groupfiles` 群組共用檔案、`groups` 群組討論、`triggers` 資料夾與信件觸發、`sync` 多台 Mac 同步、`errors` CLI 失敗原因分類、`stream` 回覆逐字顯示、`waiting` 忙碌時排隊、`paging` 長對話分頁與搜尋、`compact` 對話過長自動整理、`automation` 本機腳本介面、`choices` 選項按鈕與 Bot 提問、`teams` 一句話建立團隊、`live` 保持 CLI 開啟、`cursor` Cursor、`browser` 內建瀏覽器（擋私有位址的轉送層、工具、誰能用）、任務引擎（[設計](docs/task-engine-design.md)）：`tasks` 帳本、提示詞與工具，`taskrun` 執行迴圈，`taskcheck` 交叉驗收、重試、決策關卡與確認，`taskplus` 依驗收紀錄派工與派助手、`app` 回覆、`parsing` 解讀 CLI 輸出、`abilities` 各家能力對照、`sessions` 接續 CLI 原生對話與即時讀取輸出、`routing` 自動選擇模型、`fields` 欄位檢查、`upkeep` 備份、活動紀錄、用量預算、固定規則、舊工作瘦身、已刪除的 Bot、`templates` Skill 範本、`usageview` 用量頁、`handler` HTTP 路由 |
| `backend/runtime.py` | MCP 客戶端、工具執行、核准分級；連接器的工具用到才載入 |
| `backend/discovery.py` | 掃描這台 Mac 上 Codex、Claude 與共用庫的 Skills、連接器、插件（由 `runtime.py` 以路徑載入） |
| `backend/zook_cli.py` | 本機腳本介面的指令工具，說明在 [docs/automation.md](docs/automation.md) |
| `backend/providers.py` | 各家 CLI 的定義 |
| `backend/tool_server.py` | 提供給 CLI 的 Zook 工具（MCP） |
| `backend/cursor_guard.py` | Cursor 的 preToolUse 檢查：內建工具只能用在 Bot 允許的資料夾（fail-closed） |
| `backend/gmail_mcp.py` | 內建 Gmail |
| `backend/cli_installer.py` | 把 npm 類 CLI（例如 Gemini）連同 Node.js 裝進 Zook 自己的 tools 資料夾 |
| `frontend/` | `index.html`、`style.css`、`js/`。`js/` 的檔案依檔名順序接成 `/app.js`（第一個檔案開頭和最後一個檔案結尾是同一個函式），無框架、無建置步驟 |
| `ios/` | iPhone App |
| `relay/` | Cloudflare Worker 中繼 |
| `tests/` | `*_test.py`，unittest |
| `scripts/` | 建置、圖示、[App 檢查](scripts/check_app.py)、[用真實 CLI 的驗收腳本](scripts/acceptance.py)、[Codex 審查](scripts/codex_review.py) |

資料存在 `~/Library/Application Support/swarmr/swarmr.json`；Preview 版（`bash scripts/build.sh --preview`）用 `swarmr-preview`，可以和使用者正在用的 Zook 同時開。

## 開發環境

- 只用 `/usr/bin/python3`（3.9）標準函式庫，沒有 npm 或 pip 依賴。這台 Mac 沒有 `node`。
- 含中文的修改請用檔案編輯工具或寫成 `.py` 檔執行，不要用 shell heredoc。
- 測試用的環境變數：

| 變數 | 作用 |
|---|---|
| `ZOOK_SKIP_UPDATE_CHECK=1` | 不檢查更新 |
| `ZOOK_SECRETS_DIR=<資料夾>` | 金鑰存到檔案，不碰真實鑰匙圈 |
| `ZOOK_SHELL_ENV=0` | 連接器不讀登入 shell 的環境 |
| `ZOOK_SCHEDULE_TICK=<秒>` | 排程檢查間隔（預設 15） |
| `ZOOK_CLI_DIRS` | 額外的 CLI 搜尋路徑 |
| `ZOOK_GMAIL_SKIP_CHECK=1` | 不實際連 Gmail |
| `ZOOK_TRIGGER_EVERY=<秒>`、`ZOOK_TRIGGER_MAIL_FILE=<json>` | 觸發條件的檢查間隔；用一個 JSON 檔假裝信箱 |
| `ZOOK_SYNC_EVERY=<秒>` | 多台同步的間隔（預設 30） |
| `ZOOK_NO_INTRO=1` | 建立或修改 Bot 時不生成招呼語（假 CLI 會計算每次呼叫的測試用） |
| `ZOOK_COMPACT_AT=<Token>` | 自動整理對話的門檻（預設 15 萬） |
| `ZOOK_AUTOMATION=<資料夾>` | `zook_cli.py` 去哪裡找本機腳本介面的位址與權杖 |
| `ZOOK_UPDATE_URL`、`ZOOK_UPDATE_NO_RELAUNCH` | 更新測試 |
| `ZOOK_BROWSER_HELPER` | 內建瀏覽器要啟動的程式（從原始碼執行時沒有 App，例如指到 `build/Zook.app/Contents/MacOS/Zook --zook-browser`） |

測試時自己開的臨時伺服器不要用連接埠 8799（手機連線測試會誤認成中繼伺服器）、8788（驗收腳本在用）和 8787。

## 驗證

每個改動都要過這三層，缺一層就在報告寫「未驗證」：

1. **自動測試**：`/usr/bin/python3 scripts/run_tests.py`（每個測試檔各自一個程序、同時跑幾個，全部約 2–3 分鐘；只跑幾個檔：`scripts/run_tests.py outline_test intro_test`）。開 PR 前一定跑完整一次。失敗的檔會單獨重跑一次，重跑才通過的列為「不穩定」，要找出原因修掉，不能當作沒事。新功能先寫會失敗的測試，再實作。
   - 每個測試檔都要能單獨跑（不能依賴其他測試先載入的東西）；啟動 Zook 並用假 CLI 的測試要設 `ZOOK_NO_INTRO=1`。
2. **介面實測**：啟動臨時伺服器，用內建瀏覽器實際操作。
   ```sh
   ZOOK_SKIP_UPDATE_CHECK=1 ZOOK_SECRETS_DIR=<暫存> python3 backend/server.py --port 8791 --data-dir <暫存>/data --assets frontend
   ```
   第一行輸出有 `token`；在瀏覽器執行 `document.cookie='swarmr_session=<token>; path=/'` 後重新整理。內建瀏覽器的點擊有時會逾時，改用 `javascript_tool` 操作頁面。用完關掉伺服器、刪掉暫存資料夾。
3. **真實 App**：`bash scripts/build.sh` 後執行 `python3 scripts/check_app.py`（檢查建置好的 App 內的後端）；要連真實 CLI 加 `--live`（會用到少量額度）。要看視窗就建 Preview 版開起來截圖。

改到回覆流程（CLI 的呼叫、輸出解讀、排隊、來源、壓縮）時，另外跑 `python3 scripts/acceptance.py --speed --compare docs/0.14-baseline.json`：它用真實 CLI 檢查約 20 項並量四家的速度，結束碼 0 表示沒有比基準差。某家額度用完時該家會標成「略過」。

改到任務引擎（`tasks`、`taskrun`、`taskcheck`、`taskplus`）時，另外跑 `python3 scripts/task_eval.py --compare docs/0.17-eval-baseline.json`：用假的 CLI 跑八個固定情境（同時進行、先後順序、交叉驗收、三次後停下、決策關卡、先問我、依紀錄派工、助手兩層），分數比基準低或模型請求變多時結束碼 1。加 `--live` 會多跑一次真實 CLI（Claude 主持、Grok 與 Claude 成員，用少量額度）。整段群組工作的速度、請求與 token 用 `scripts/task_bench.py --mode split|auto` 量。

做不到、需要使用者驗收的：另一台 Mac、公司帳號的連接器、手機實機、App 內的更新按鈕。

## 開發與發佈的分工（使用者 2026-11-21 定）

兩個對話分工，各做各的：

- **開發視窗（「ZOOK開發」）只做到開 PR**：開分支 → 寫測試 → 實作 → 三層驗證 → Codex 審查 → 開 PR（下面「每個項目的流程」1–8），然後用 SendMessage 把 PR 交給「ZOOK發佈」，接著做下一件事。不等 CI、不合併、不改版號、不打包。
  - 下一件事從最新的 `main` 開分支；要用到還沒合併的改動時，接在上一個分支後面做，PR 說明寫清楚它接在哪個 PR 後面。
  - 一個版本一個 PR。
- **「ZOOK發佈」對話**：收到 PR 後用 App 的 ccd_pr 工具綁定這個 PR、打開 Auto-fix 盯 CI（不自己輪詢）。
  - CI 失敗：先看原因。只跟測試環境、時間、格式有關的簡單問題直接在 PR 的分支修；需要動功能（例如新功能干擾了舊測試的行為、驗收條件沒達成）就用 SendMessage 回報「ZOOK開發」，附上失敗的測試和原因，不要一直重跑。
  - 合併衝突：沒有功能影響的（文件、版號、相鄰的行）由發佈對話解決；牽涉功能的回報「ZOOK開發」。
  - CI 通過後依下面「發佈」做完：合併到 `main`、改版號、建置、打包 DMG、建立 GitHub 發佈、確認下載網址、安裝。
- **授權**：CI 通過就合併、發佈並直接安裝這台 Mac，不用再問使用者。安裝前一定等使用者的 Zook 沒有進行中的工作。

## 讓開發維持效率（使用者 2026-11-21 選定）

- **版本切小**：一版只做一件事，審查和測試都小而快，出問題也好找。
- **先寫驗收範例再動手**：動手前用幾句白話和使用者確認「做完長什麼樣子」（例如「選單裡會有 Codex（Waifdance），選了之後可以選模型」），避免做完才發現方向不對。
- **Codex 審查分級**：只有改到核准、權限、沙盒、金鑰、計費的版本跑 astra；文字與排版的小版合併到下一版再審。
- **真實 CLI 驗收**（`scripts/acceptance.py`）：只有改到回覆流程（CLI 的呼叫、輸出解讀、排隊、來源、壓縮）的版本每版跑；其他交給每天的體驗巡檢。
- **巡檢→開發→發佈循環**（2026-11-22 啟動）：規則與接力檔案在 `/Users/sean/Documents/Claude code/Zook/loop/`（README、`queue.md` 待辦、`decisions.md` 要使用者決定的事、題庫、分數）。
  - 排程 `zook-daily-inspection` 每 2 小時扮成各行業員工在 Zook 交辦工作（單一 Bot 與群組、交出的檔案也驗收），評分後把打磨類問題寫進 `queue.md` 並通知「ZOOK開發」；功能的新增、移除、保留寫進 `decisions.md` 讓使用者決定。08:00 那次與嚴重問題才推手機。只用訂閱額度（每次約 20 次模型回覆，低於 20% 跳過要用模型的項目）。
  - `zook-dev-loop` 每 3 小時：`queue.md` 有待開發、沒有開發中時提醒「ZOOK開發」做最上面一件；開發照本檔流程做完後更新 `queue.md` 的狀態。
  - `zook-release-loop` 每小時：有開著的 PR 就提醒「ZOOK發佈」照流程處理。

## 每個項目的流程

1. 在 [docs/ROADMAP.md](docs/ROADMAP.md) 寫驗收條件（白話、可檢查）。
2. 從最新的 `main` 開分支 `item/<編號>-<簡稱>`（要用到還沒合併的改動時，從上一個分支開）。
3. 先寫測試，確認它失敗。
4. 實作。
5. 三層驗證。
6. 用 Codex 審查（和開發者不同家的模型）：使用共用的 `codex-review` Skill（`~/.claude/skills/codex-review`，帳號輪流、20% 下限、不用付費點數、自動取最新模型都在它的 SKILL.md）。在 repo 根目錄執行：
   `python3 scripts/codex_review.py --family sol|astra --brief <審查說明> --out <結果檔>`（這個檔案只是轉給共用 Skill，參數相同）。Zook 自己的規定：
   - 每一版的例行審查用 sol（medium）：找錯誤、漏掉的測試、和這份規則衝突的地方。
   - 交辦標「找獨立審查」的版本，以及改到核准、權限、沙盒、金鑰的版本，用 astra（high）：冒名回報、繞過核准、派工失控、權限與金鑰這類安全問題。
   - 審查範圍只限這一版的改動（diff）；只改文字或文件的小版本，併到下一版一起審。
   - 結果檔放在 repo 外面；進度檔記下它印出的帳號、模型和 token，以及每個發現怎麼處理。
   - 另外請 Claude 子代理審查時，兩邊互相看不到結果；兩邊都找到的先修，只有一邊找到的先重現再決定，理由寫進進度檔，報告分開列出。
7. 驗收報告：每條驗收條件寫「通過／未通過／未驗證」和證據，寫在進度檔。
8. 更新 ROADMAP 的狀態，推送分支，用 sean0407 開 PR（`gh pr create --repo sean0407/zook --base main`，說明列出驗收結果、審查結果和要發佈的版本號），交給「ZOOK發佈」。

GitHub Actions（`.github/workflows/test.yml`）在每個 PR 和推送到 `main` 時用同一個 `scripts/run_tests.py` 跑測試，再建置與檢查 App；沒過不能併入。有合併衝突的 PR，GitHub 不會跑檢查：解完衝突推送後才會跑。

## 發佈（由「ZOOK發佈」對話做）

0. PR 的 CI 通過後，用 sean0407 合併到 `main`（`gh pr merge --merge`），之後的步驟都在更新過的 `main` 上做。
1. 改版號：`scripts/build.sh` 和 `native/Zook.swift` 兩處，ROADMAP 的狀態改成 ✅；提交到 `main`。
2. 跑全部測試、`bash scripts/build.sh`、`codesign --verify --deep build/Zook.app`。
3. 打包：暫存資料夾放 `Zook.app` 和指向 `/Applications` 的捷徑，`hdiutil create -volname Zook -srcfolder <資料夾> -ov -format UDZO <dmg>`，再 `hdiutil verify`。DMG 放在 `/Users/sean/Documents/Claude code/Zook/`。
4. GitHub 一律用 sean0407 帳號，不切換 gh 的作用中帳號：
   ```sh
   export GH_TOKEN=$(gh auth token --user sean0407)
   U="22557931+sean0407@users.noreply.github.com"
   git -c user.name=sean0407 -c user.email="$U" commit ...
   git -c credential.helper= -c "http.extraheader=Authorization: Basic $(printf 'x-access-token:%s' "$GH_TOKEN" | base64)" push origin <分支>
   gh release create vX.Y.Z <dmg> --repo sean0407/zook --target main --title "Zook X.Y.Z" --notes "<中文>\n\n<English>"
   ```
5. 確認下載網址回 200。
6. 安裝：等使用者的 Zook 沒有進行中的工作（`swarmr.json` 裡沒有 `running` 的工作，也沒有 `running` 的群組討論，連續兩次檢查都是）才換版。結束 Zook → 舊的 App 另存到暫存資料夾 → 從 DMG 複製新的 `Zook.app` 到 `~/Applications` → `codesign --verify --deep` → 開啟 → 確認後端已啟動、Bot／群組／排程數量和換版前一樣。
7. 在進度檔記下發佈結果，提交並推送到 `main`。

## 已知限制

- 綁在 Claude 或 ChatGPT 帳號的遠端連接器（例如 LogiQ／Google Chat）複製到 Zook 後會被拒絕，因為授權留在原服務。要在 Zook 的連接器頁新增網址後按「登入」。
- 手機 App 的排程、照片、切換對話和通知還沒在實機測過；真正的推播需要付費開發者帳號。
- 群組討論每次重新帶入最近的對話，不接續 CLI 原生對話。
- 自動選擇：每個帳號各自是一個選項（同一家的預設帳號優先），各有自己的開關與額度；API 計費帳號一律不選。
- Grok 額度：`grok usage --json` 到 1.0.89 還不能用，Zook 每次先試它；不能用時在看不見的終端機開 Grok、讀畫面底部的「Weekly limit left」，再關掉（`grokquota.py`）。只在 Zook 資料夾裡的 `grok-usage`（必須是空的、只有本人能進、不是連結）開；只帶 Grok 需要的環境變數。唯一會輸入的是「y」，而且只在畫面上除了「是否信任這個資料夾」以外沒有別的內容時輸入一次。只有每週額度，沒有重置時間。`grok usage --json` 能用後，移除讀畫面的做法。
- Antigravity 走官方 `agy` CLI。Google 條款限制第三方工具使用，帳號有被暫停的風險，卡片上有寫明；AI 點數一律關閉。
- Antigravity 的額外帳號：agy 只認 `HOME`，所以額外帳號用 `accounts/<帳號>` 當家目錄，裡面只連回桌面、文件、下載、圖片、影片、音樂和 iCloud Drive（`agyhome.py`）；其他家目錄裡的東西（例如 ~/.zshrc、~/Projects）用 `~` 找不到，要用完整路徑。連到家目錄本身、整個資源庫或金鑰資料夾的連結不建立。agy 不提供信箱，卡片只顯示帳號名稱。登入只能在終端機。模型清單仍用預設帳號查。agy 的原生刪除不經 Zook 核准關卡（預設帳號也一樣，只靠提示詞先問）。每個額外帳號有自己的鑰匙圈（`Library/Keychains/zook-agy.keychain-db`，`login.keychain-db` 連到它；叫 login 的檔案無法用密碼解鎖），隨機密碼存在使用者的登入鑰匙圈，只經 `security -i` 的 stdin 傳；每次執行前解鎖、不自動上鎖；不改使用者的鑰匙圈清單。Bot 有整台 Mac 的指令權限，仍能主動用 `security` 讀出這個密碼（和 API 金鑰一樣），也能讀出該帳號自己的 agy 憑證。
- Gemini CLI 沒有接 Zook 工具（ROADMAP E6）。到 0.16.2 為止使用者還沒在 Zook 加 Gemini API 金鑰帳號。Google 已不讓個人帳號使用這個 CLI（`IneligibleTierError`），要有 Gemini API 金鑰才能用，所以沒辦法開發與驗證。技術上可行的做法：工作資料夾裡的 `.gemini/settings.json` 設 `mcpServers`，加上 `--allowed-mcp-server-names` 與 `--approval-mode`。
- Grok 在「指定資料夾」時從那個資料夾啟動，靠它自己的嚴格沙盒限制在資料夾內；Zook 的設定放在該資料夾的 `.grok`（有 `.zook-owned` 標記），回覆結束就刪。資料夾裡原本就有 `.grok` 時不執行。這個模式下 Grok 讀不到對話附件。新版 Grok 仍不接受 `--add-dir`。它的嚴格沙盒不限制系統暫存區，所以這類測試不要在 `/tmp` 做。
- 回覆逐字顯示：Codex 的 CLI 只在整則訊息完成時輸出，所以是整段出現；Grok 會先思考幾十秒才出字；手機是輪詢，一兩秒跳一段。
- 群組討論沒有分頁，也不套用自動整理。
- 任務引擎（設定裡預設關閉）：
  - 主持人、驗收者、只讀的工作都用只能讀的回覆；工作只透過 `zook_task_*` 工具回報，回報綁在當次嘗試上。
  - 驗收一定找另一家；群組裡沒有另一家能驗時改成「等你看結果」。驗收沒通過最多重試三次，做過對外動作的不自動重試。
  - 成員可以派助手，最多兩層（主持人派的工作是第一層，助手是第二層，助手不能再派），一項工作最多三位助手，助手能做的不能比原工作多。
  - 依驗收紀錄派工：某家在某類工作（寫程式、分析、簡短工作、圖片，用自動選擇的分類）至少驗收三次、通過不到一半，而另一位成員那家的通過率高 30 個百分點以上，才改派；紀錄存在 `swarmr.json` 的 `taskStats`。
  - 沒做：Zook 工具的權杖仍放在 CLI 的環境變數（0.16 以前就這樣，所有 Zook 工具共用，和上面「內部權杖不放環境變數」的規則衝突，待改）；換到備用模型那一刻不再檢查每家 CLI 的同時上限；重試時主持人會看到之後的群組對話。
- 自動整理用的輸入量是 CLI 回報的整個回合總和，是估算；所以要連續兩則都超過門檻才觸發。
- 來源規則擋的是 Zook 自己的工具。CLI 的原生工具仍可直接改 Mac 上的檔案，包含 Zook 的資料檔。
- 本機腳本介面：同一個使用者的任何程式都讀得到權杖檔，包含 Bot 自己的 CLI。它能用已開啟的 Bot 的身分做事，但不能核准、不能改設定。
- Grok 的 Zook 工具伺服器必須用 `/usr/bin/python3` 啟動，嚴格沙箱擋得住 Xcode 內的 Python。
- 內建瀏覽器（`browser.py`、`native/Browser.swift`）：需要 macOS 14（用 WKWebView 的轉送設定）。每則回覆第一次用到時才啟動，回覆結束就關掉。所有連線經過 Zook 自己的轉送層，名稱由它解析、任何一個答案是私有位址就整個拒絕，並連到它檢查過的位址；WebKit 的內容規則另外先擋字面上的私有位址。只開放 http(s) 的 GET 換頁（包含用 GET 送出的搜尋表單）；POST 表單、下載、上傳、新視窗、登入對話框、WebRTC 都關掉。Bot 只能在搜尋欄位（不在 POST 表單裡）輸入，不能在密碼、信箱、電話、驗證碼欄位或任何和密碼欄同一區塊的欄位輸入。網頁自己的程式可以在文字打進去的當下就送走，Zook 擋不到，所以每次輸入不論主動性都先問使用者，卡片寫出網站、欄位和文字，核准後網頁或欄位變了就不輸入；Bot 自己組出、帶資料（查詢參數、片段或很長的路徑）的網址也一樣先問。macOS 會讓結尾有點的名稱（`localhost.`）不經轉送層，所以這種網址一律拒絕。群組討論的回合算非使用者的回合。活動紀錄只留動作與網址，不留網頁內容。因為沒有使用者的登入，Bot 無法以使用者身分發文或下單。網頁內容只放在回覆的 `page` 裡，內文用每次不同的標記包住。轉送層也擋這台 Mac 所在、有公開位址的網段（用介面的實際網段；讀不到時一律不連），每則回覆最多同時 24 條連線、全部回覆合計 96 條。路由器的對外 IPv4 位址沒有擋（要查外部服務才知道）。Bot 能把資料放進網址開啟，這和上網搜尋一樣，靠「上網搜尋」開關與每個 Bot 的開關控制。
- Cursor：用 `--force` 跑，靠工作資料夾 `.cursor/hooks.json` 的 preToolUse 檢查（`cursor_guard.py`）限制範圍；它的網頁搜尋不經過這個檢查，「上網搜尋」關閉時用 `CURSOR_FORCED_SHELL_EGRESS=1` 關掉。
