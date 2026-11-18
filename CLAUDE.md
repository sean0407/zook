# Zook 開發說明

給在這個 repo 工作的 AI 與人。先讀這份，再讀 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 產品

Zook 是 macOS App（Swift 視窗 + Python 後端 + 純 JS 介面）加 iPhone App「ZookMobile」。它把使用者已安裝的 Codex、Claude、Grok、Gemini 或自訂 CLI 放進同一個介面，可以多 Bot 群聊。

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

## 目錄

| 路徑 | 內容 |
|---|---|
| `native/Zook.swift` | macOS 視窗、啟動與關閉後端、檔案選取與下載 |
| `native/remote/` | `zook-remote`，與中繼伺服器的加密連線 |
| `backend/server.py` | API、資料儲存、CLI 工作、群組、排程、更新、設定包 |
| `backend/runtime.py` | Skill 與連接器探索、MCP 客戶端、工具執行 |
| `backend/providers.py` | 各家 CLI 的定義 |
| `backend/tool_server.py` | 提供給 CLI 的 Zook 工具（MCP） |
| `backend/gmail_mcp.py` | 內建 Gmail |
| `frontend/` | `index.html`、`app.js`、`style.css`，無框架、無建置步驟 |
| `ios/` | iPhone App |
| `relay/` | Cloudflare Worker 中繼 |
| `tests/` | `*_test.py`，unittest |
| `scripts/` | 建置、圖示、[App 檢查](scripts/check_app.py) |

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
| `ZOOK_UPDATE_URL`、`ZOOK_UPDATE_NO_RELAUNCH` | 更新測試 |

## 驗證

每個改動都要過這三層，缺一層就在報告寫「未驗證」：

1. **自動測試**：`python3 -m unittest discover -s tests -p '*test.py'`。新功能先寫會失敗的測試，再實作。
2. **介面實測**：啟動臨時伺服器，用內建瀏覽器實際操作。
   ```sh
   ZOOK_SKIP_UPDATE_CHECK=1 ZOOK_SECRETS_DIR=<暫存> python3 backend/server.py --port 8791 --data-dir <暫存>/data --assets frontend
   ```
   第一行輸出有 `token`；在瀏覽器執行 `document.cookie='swarmr_session=<token>; path=/'` 後重新整理。內建瀏覽器的點擊有時會逾時，改用 `javascript_tool` 操作頁面。用完關掉伺服器、刪掉暫存資料夾。
3. **真實 App**：`bash scripts/build.sh` 後執行 `python3 scripts/check_app.py`（檢查建置好的 App 內的後端）；要連真實 CLI 加 `--live`（會用到少量額度）。要看視窗就建 Preview 版開起來截圖。

做不到、需要使用者驗收的：另一台 Mac、公司帳號的連接器、手機實機、App 內的更新按鈕。

## 每個項目的流程

1. 在 [docs/ROADMAP.md](docs/ROADMAP.md) 寫驗收條件（白話、可檢查）。
2. 開分支 `item/<編號>-<簡稱>`。
3. 先寫測試，確認它失敗。
4. 實作。
5. 三層驗證。
6. 請一個沒看過實作過程的 AI 審查 diff；改到核准、金鑰、權限的一定要審。
7. 驗收報告：每條驗收條件寫「通過／未通過／未驗證」和證據。全部通過才併入 `main` 並發佈。
8. 更新 ROADMAP 的狀態。

GitHub Actions（`.github/workflows/test.yml`）會在每次推送跑測試和建置，沒過不能併入。

## 發佈

1. 改版號：`scripts/build.sh` 和 `native/Zook.swift` 兩處。
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
6. 替換這台 Mac 的 `~/Applications/Zook.app` 前，先確認 `swarmr.json` 裡沒有 `running` 的工作。

## 已知限制

- 需要登入授權、綁在 Claude 或 ChatGPT 帳號的遠端連接器（例如公司的 LogiQ／Google Chat）複製到 Zook 後會 403，原因未查明。
- 每則訊息都重新啟動 CLI，只帶最近 12 則對話（ROADMAP A2 要改）。
- Gemini 沒有接 Zook 工具（ROADMAP E6）。Grok 的檔案工具只在工作資料夾，新版 Grok 不接受 `--add-dir`（ROADMAP E7）。
- Grok 的 Zook 工具伺服器必須用 `/usr/bin/python3` 啟動，嚴格沙箱擋得住 Xcode 內的 Python。
- 後端和介面各是一個大檔案（ROADMAP G6 要拆）。
