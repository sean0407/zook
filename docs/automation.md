# 本機腳本介面

讓這台 Mac 上的終端機或腳本，把工作交給某個 Bot 並取得回覆。例如：建置完成後請 Bot 整理結果、每天用自己的腳本丟一份檔案給它。

## 開啟

每個 Bot 各自開啟，預設關閉：Bot 設定 → 進階設定 →「允許本機腳本」。Zook 要開著才能用。

## 指令工具

工具隨 Zook 一起安裝：

```sh
alias zook-cli='/usr/bin/python3 "$HOME/Applications/Zook.app/Contents/Resources/backend/zook_cli.py"'
zook-cli list                                   # 已開啟的 Bot
zook-cli run "文件整理員" "整理下載資料夾" --wait   # 送出並印出回覆
zook-cli run "文件整理員" - --wait < task.md       # 內容從標準輸入讀
zook-cli status "文件整理員" <id>                 # 查詢先前送出的那一則
```

- `--timeout 90s|5m|1h`：這個指令最多等多久（預設 5 分鐘）。只影響等待，不會中斷 Bot 的工作。
- `--id KEY`：重送時帶同一個 KEY，不會變成兩則。KEY 要是 8 到 64 個英數字、底線或連字號；Zook 只記 10 分鐘，重新開啟 Zook 後也不記得。
- `--json`：以 JSON 輸出。

結束碼：0 完成、1 回覆失敗、2 連不上或參數有誤、3 等你在 Zook 核准、4 等待結束時還在進行。

## 它能做和不能做的事

能做：列出已開啟的 Bot、送訊息、查詢某一則的狀態。Bot 忙碌時會排隊（每個 Bot 最多 10 則腳本訊息）。

腳本送的訊息會放在該 Bot 一個名為「本機腳本」的獨立對話，不會混進你正在用的對話；Bot 也會被告知這些不是你本人說的。

不能做：
- 核准動作。需要核准時，回覆會停在那裡等你到 Zook 視窗或手機上按。
- 更改設定、權限、金鑰。
- 對沒有開啟這個選項的 Bot 送訊息。
- 經腳本啟動的回合，Bot 不能建立或修改排程，也不能寫入所有 Bot 共用的記憶。

每個 Bot 每小時最多接受 60 則腳本訊息。

## 直接呼叫

Zook 每次啟動會在 `~/Library/Application Support/swarmr/automation/` 寫入兩個只有你讀得到的檔案：`url`（位址，連接埠每次不同）和 `headers`（權杖，每次不同）。

```sh
A="$HOME/Library/Application Support/swarmr/automation"
curl -sS "$(cat "$A/url")/v1/agents" -H @"$A/headers"
curl -sS -X POST "$(cat "$A/url")/v1/agents/文件整理員/messages" -H @"$A/headers" \
  -H 'Content-Type: application/json' -d '{"content":"整理下載資料夾","wait":120}'
```

只接受來自這台 Mac 的請求；帶有瀏覽器來源的請求一律拒絕。
