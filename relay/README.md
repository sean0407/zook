# Zook 中繼伺服器

在 Mac 和已配對的裝置之間轉送加密訊息。伺服器讀不到內容，也不儲存對話。

本機執行（測試用）：`npx wrangler dev --port 8799`
部署到自己的 Cloudflare 帳號：`npx wrangler login`，再 `npx wrangler deploy`。部署後把顯示的網址（改成 `wss://` 開頭）填進 Zook 設定頁的「中繼伺服器」。
