# 任務引擎設計（0.17 系列）

依據：2026-11-20 拆解 Orca（`stablyai/orca`，commit `2e97495c`）的調度程式，以及 Zook 0.16.2 的群組程式（`backend/zook/groups.py`）。只借鏡做法，沒有複製程式碼。

## 從 Orca 學到的事

Orca 能讓模型互相派活，靠的不是更聰明的規劃程式，而是一套嚴格的協定加帳本：拆工作、決定下一步交給「總指揮」那個 AI；程式只負責記帳、轉信、管並發、擋重複、判失敗。

| Orca 的做法 | 在 Zook 的對應 |
|---|---|
| Run → Task（有相依）→ Dispatch（每一次嘗試）→ 有型別的信件 | `group['taskRun']`：目標、工作、每一次嘗試、回報 |
| 總指揮用 CLI 指令建 Task、派工 | 主持人用 Zook 工具（MCP），六家 CLI 共用 |
| 派工前言：只做這件事、完成時送一次 `worker_done`（三句、成功或失敗）、有問題 `ask` 後結束這一輪 | 成員的提示詞與 `zook_task_done`、`zook_task_ask`、`zook_task_blocked` |
| 成員看不到總指揮的對話，只拿自足的 spec | 成員只拿工作說明、完成條件、上游摘要 |
| 不輪詢：派完工就結束，有信才叫醒 | 一批都有結果、或有人提問、卡住時，才叫醒主持人一次 |
| 只接受這次嘗試的回報（身分圍籬） | 回報工具不收工作編號，綁在那一則回覆上；不是目前的嘗試就拒絕 |
| 同一條重試鏈 3 次失敗就斷路，不能用開新 Task 繞過 | 同一個工作 3 次沒完成就停，只有使用者按「重試」才重開 |
| 只憑證據行動：沒有回應、逾時都不代表結束 | Zook 重啟時還在進行的嘗試標「狀態不明」，不自動重做 |
| 決策關卡：卡住相關 Task，答案帶進下一次派工 | 主持人用選項按鈕問使用者，只卡相關工作 |
| 同時最多 4 個，分批啟動 | 全部上限加上每家 CLI 的上限 |

不搬的部分：終端機輸入、畫面識別碼、遠端主機、WSL、git worktree。Zook 是在背景用 `-p` 加 JSON 輸出驅動 CLI，不需要這些。

## 資料

`group['taskRun']`（存在主資料檔，Zook 重啟後還在）：

```text
taskRun {id, goal, hostId, origin, status, createdAt, wakes, batches, tasks[], gates[], log[]}
task    {id, n, title, spec, doneWhen, assignee, suggested, why, deps[], changes, status,
         attempts[], failures, result{outcome, summary, files[]}, question, answer, depth}
attempt {id, jobId, n, retryOf, state, outcome, summary, files[], feedback, startedAt, endedAt}
```

工作狀態：`pending`（等相依）、`ready`、`running`、`asked`（等主持人回答）、`blocked`（等決策或卡住）、`verifying`、`done`、`failed`、`stuck`（斷路）、`unknown`（重啟後狀態不明）。

## 流程

1. 使用者在群組送出訊息，討論方式是「自動（主持人決定）」。
2. 主持人規劃：簡單問題直接回答，不建立工作；需要分工就用 `zook_task_create` 建立工作，然後結束這一輪。
3. 排程器：相依都完成的工作依上限啟動，每個工作是一則成員回覆（沿用群組的回覆流程、主動性、存取範圍、核准與共用檔案）。
4. 成員用回報工具交回結果；沒有回報就結束的嘗試算失敗。
5. 叫醒：一批都有結果，或有人提問、卡住時，把整批三句摘要交給主持人一次。主持人可以回答提問、再建立工作，或在全部結束時寫總結卡。
6. 上限：一次最多 12 個工作、主持人最多被叫醒 8 次、整個目標最多 30 次嘗試，避免無限派工。

## 安全

- 每個工作用負責那位 Bot 自己的主動性與存取範圍；寄信、改排程等照樣逐次核准，核准卡寫明是哪個工作。
- 來源規則照舊：排程或觸發開始的目標，裡面的每個工作都是同一個來源，不會因為派工得到更多權限。
- 只有主持人那一則回覆有建立工作的工具；成員那一則只有回報工具。
- 開關「任務引擎」預設關閉，關閉時群組和以前完全一樣。
