# Zook

[English](README.md) | **繁體中文**

在 Mac 本機執行的 AI 工作區，用的是你已經安裝的命令列工具。Zook 把 Codex、Claude、Grok、Gemini 或你自己的 CLI 放進同一個介面，沿用各工具原本的登入。另有 iPhone App，透過端對端加密的中繼伺服器連回 Mac。

版面配置參考 Grok Bot。實作是獨立完成的，沒有使用它的程式碼或圖像。

## 功能

- **Bot**：建立、編輯、釘選、分類 Bot，每個 Bot 有自己的工作指示、模型、外觀和對話紀錄。
- **群組對話**：2–6 個 Bot 在同一個對話裡。可以對全員發話、用 `@Bot` 指定對象，Bot 之間也能互相交接工作。
- **任何 CLI**：內建 Codex、Claude、Grok、Gemini，也能加入自訂 CLI。不會要求或複製 API 金鑰。
- **每個 Bot 的存取範圍**：整台 Mac（預設）、單一資料夾，或只限 Zook 的工作區。
- **共用的 Skills、連接器與插件**：設定一次，所有 Bot 都能用。
- **用量**：各供應商的額度，以及每個 Bot 的 Token 用量。
- **iPhone App**：讀取和傳送訊息、核准請求、建立 Bot、查看用量。會改變 Bot 權限的設定只能在 Mac 上調整。

## 建置與開啟

需要 Apple Silicon 的 macOS、Xcode Command Line Tools（Swift），以及 `/usr/bin/python3` 3.9 以上。不需要安裝任何 npm 或 Python 套件。

```sh
bash scripts/build.sh
open build/Zook.app
```

建置結果只有本機簽署，沒有經過 Apple 公證。App 會在本機迴路埠啟動 Python 伺服器，驗證自己的 WebKit 視窗，並在結束時關閉伺服器。

## iPhone App

用 Xcode 開啟 `ios/ZookMobile.xcodeproj`，選擇你自己的開發團隊，執行到 iPhone 上（iOS 17 以上）。在 Mac 的 Zook 開啟遠端存取，再用手機掃描 QR code。

手機和 Mac 之間透過中繼伺服器通訊，伺服器只轉送加密訊息。要自行架設，請看 [relay/README.md](relay/README.md)。

## 資料與隱私

- Zook 的資料存在 `~/Library/Application Support/swarmr/swarmr.json`，檔案權限僅限本人。內容是本機的純文字 JSON，沒有加密。
- 傳送訊息時會執行所選的 CLI，並帶上該對話的內容。帳號額度與計費由供應商決定。
- 中繼伺服器讀不到訊息內容，也不儲存對話。

## 開發

```sh
python3 -m unittest discover -s tests -p '*test.py' -v
```

| 路徑 | 內容 |
|---|---|
| `native/` | macOS 視窗、本機服務的啟動與關閉、中繼連線主機 |
| `backend/` | 需驗證的 API、資料儲存、CLI 工作、裝置權限 |
| `frontend/` | HTML、CSS、JavaScript 介面 |
| `ios/` | iPhone App「ZookMobile」 |
| `relay/` | 轉送加密訊息的 Cloudflare Worker |
| `tests/` | 後端與通訊協定測試 |
