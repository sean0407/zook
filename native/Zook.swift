import AppKit
import UserNotifications
import WebKit

// The page reports its header areas (and the buttons inside them); a press on empty header space moves the window.
final class ZookWebView: WKWebView {
    var dragAreas: [CGRect] = []
    var blockedAreas: [CGRect] = []
    override func mouseDown(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        let point = CGPoint(x: p.x / pageZoom, y: (isFlipped ? p.y : bounds.height - p.y) / pageZoom)
        if dragAreas.contains(where: { $0.contains(point) }) && !blockedAreas.contains(where: { $0.contains(point) }), let window = window {
            if event.clickCount == 2 { ZookWebView.toggleZoom(window) } else { window.performDrag(with: event) }
            return
        }
        super.mouseDown(with: event)
    }

    // Zoom fills the screen; when it is already that size and macOS has no smaller size to return to, use a centered default size.
    static func toggleZoom(_ window: NSWindow) {
        guard let screen = (window.screen ?? NSScreen.main)?.visibleFrame else { return }
        let before = window.frame
        window.performZoom(nil)
        if window.frame == before && window.isZoomed {
            let size = NSSize(width: max(window.minSize.width, min(1440, screen.width * 0.8)), height: max(window.minSize.height, min(900, screen.height * 0.85)))
            window.setFrame(NSRect(x: screen.midX - size.width / 2, y: screen.midY - size.height / 2, width: size.width, height: size.height), display: true, animate: true)
        }
    }
}

final class ZookApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandler, UNUserNotificationCenterDelegate {
    private var window: NSWindow!
    private var webView: ZookWebView!
    private var backend: Process?
    private var outputPipe: Pipe?
    private var readyBuffer = Data()
    private var origin: URL?
    private var downloads: [WKDownload] = []
    private var launched = false
    private var token = ""
    private var noticeSeq = 0
    private var noticeTimer: Timer?
    private var noticeBusy = false
    private var pendingOpen: [String]?
    private lazy var voice = VoiceInput { [weak self] info in self?.tellPage("zookVoice", info) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if Bundle.main.bundleIdentifier != nil { UNUserNotificationCenter.current().delegate = self }  // before a click that launched Zook arrives
        buildMenu()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.userContentController.add(self, name: "zookWindow")
        configuration.userContentController.add(self, name: "zookVoice")
        webView = ZookWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.underPageBackgroundColor = .white
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900), styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.title = Bundle.main.bundleIdentifier == "local.swarmr.preview" ? "Zook Preview" : "Zook"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(calibratedWhite: 0.98, alpha: 1)
        window.minSize = NSSize(width: 940, height: 640)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = webView
        if let screen = NSScreen.main?.visibleFrame {
            // Fit the first window on smaller screens so every edge can be grabbed to resize.
            let size = NSSize(width: min(1440, screen.width - 40), height: min(900, screen.height - 40))
            window.setContentSize(NSSize(width: max(size.width, window.minSize.width), height: max(size.height, window.minSize.height)))
        }
        window.center()
        window.setFrameAutosaveName("ZookMainWindow")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        webView.loadHTMLString("<html><body style='background:#fafafa;color:#777;font:14px -apple-system;display:grid;place-items:center;height:95vh'>正在啟動 Zook…</body></html>", baseURL: nil)
        startBackend()
    }

    private func buildMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "關於 Zook", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "隱藏 Zook", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "結束 Zook", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "編輯")
        for (title, action, key) in [("復原", "undo:", "z"), ("剪下", "cut:", "x"), ("複製", "copy:", "c"), ("貼上", "paste:", "v"), ("全選", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editItem.submenu = edit
        menu.addItem(editItem)
        let viewItem = NSMenuItem()
        let viewMenu = NSMenu(title: "顯示方式")
        viewMenu.addItem(withTitle: "放大", action: #selector(zoomIn), keyEquivalent: "+")
        viewMenu.addItem(withTitle: "放大", action: #selector(zoomIn), keyEquivalent: "=").isHidden = true
        viewMenu.addItem(withTitle: "縮小", action: #selector(zoomOut), keyEquivalent: "-")
        viewMenu.addItem(withTitle: "實際大小", action: #selector(zoomReset), keyEquivalent: "0")
        viewItem.submenu = viewMenu
        menu.addItem(viewItem)
        let windowItem = NSMenuItem()
        let windowMenu = NSMenu(title: "視窗")
        windowMenu.addItem(withTitle: "縮到最小", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "縮放視窗", action: #selector(zoomWindow), keyEquivalent: "")
        windowMenu.addItem(withTitle: "進入全螢幕", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f").keyEquivalentModifierMask = [.command, .control]
        windowItem.submenu = windowMenu
        menu.addItem(windowItem)
        NSApp.mainMenu = menu
        NSApp.windowsMenu = windowMenu
    }

    @objc private func zoomWindow() { ZookWebView.toggleZoom(window) }
    @objc private func zoomIn() { webView.pageZoom = min(2.0, webView.pageZoom + 0.1) }
    @objc private func zoomOut() { webView.pageZoom = max(0.6, webView.pageZoom - 0.1) }
    @objc private func zoomReset() { webView.pageZoom = 1.0 }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "zookVoice", let body = message.body as? [String: Any] {
            // Only Zook's own page may open the microphone.
            guard message.frameInfo.isMainFrame, let host = message.frameInfo.request.url?.host, host == "127.0.0.1" || host == "localhost" else { return }
            if body["stop"] as? Bool == true { voice.stop() } else if body["start"] as? Bool == true { voice.start(language: body["lang"] as? String ?? "") }
            return
        }
        guard message.name == "zookWindow", let body = message.body as? [String: Any] else { return }
        if body["quit"] as? Bool == true { NSApp.terminate(nil); return }  // an update is ready to be swapped in
        if let zoom = body["zoom"] as? Double {  // 設定 → 外觀：text size for the whole window, and light or dark for its frame
            webView.pageZoom = CGFloat(min(1.6, max(0.6, zoom)))
            if let dark = body["dark"] as? Bool { window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua) }
            return
        }
        let scale = Double(webView.pageZoom)  // the page reports its own units; an enlarged page covers more of the window
        func rects(_ key: String) -> [CGRect] {
            ((body[key] as? [[Double]]) ?? []).prefix(400).compactMap { r in r.count == 4 ? CGRect(x: r[0] * scale, y: r[1] * scale, width: r[2] * scale, height: r[3] * scale) : nil }
        }
        webView.dragAreas = rects("drag")
        webView.blockedAreas = rects("block")
    }

    private func tellPage(_ function: String, _ info: [String: Any]) {
        if let json = try? JSONSerialization.data(withJSONObject: info), let text = String(data: json, encoding: .utf8) {
            webView.evaluateJavaScript("window.\(function) && window.\(function)(\(text))", completionHandler: nil)
        }
    }

    @objc private func showAbout() {
        let alert = NSAlert()
        alert.messageText = "Zook"
        alert.informativeText = "0.16.1\n你的本機 AI 工作空間\nBot 對話・知識庫・用量與工具管理"
        alert.runModal()
    }

    private func startBackend() {
        guard let resources = Bundle.main.resourceURL else { showError("找不到應用程式資源。"); return }
        let script = resources.appendingPathComponent("backend/server.py")
        let directoryName = Bundle.main.bundleIdentifier == "local.swarmr.preview" ? "swarmr-preview" : "swarmr"
        let dataDir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent(directoryName, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: dataDir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            task.arguments = [script.path, "--port", "0", "--data-dir", dataDir.path, "--assets", resources.appendingPathComponent("frontend").path]
            var env = ProcessInfo.processInfo.environment
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PATH"] = "\(NSHomeDirectory())/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            task.environment = env
            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = FileHandle.nullDevice
            outputPipe = pipe
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else { return }
                DispatchQueue.main.async { self?.consumeReady(data) }
            }
            task.terminationHandler = { [weak self] process in
                DispatchQueue.main.async {
                    guard let self = self, NSApp.isRunning else { return }
                    if self.backend != nil { self.showError("本機服務已停止（狀態 \(process.terminationStatus)）。請重新開啟 Zook。") }
                }
            }
            backend = task
            try task.run()
            DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in
                guard let self = self, !self.launched else { return }
                self.showError("本機服務未能啟動。請確認這台 Mac 的 /usr/bin/python3 可執行，或依 README 執行診斷。")
            }
        } catch { showError("啟動失敗：\(error.localizedDescription)") }
    }

    private func consumeReady(_ data: Data) {
        guard !launched else { return }
        readyBuffer.append(data)
        guard readyBuffer.count < 65536 else { showError("本機服務回應無效。"); return }
        guard let newline = readyBuffer.firstIndex(of: 10) else { return }
        let line = readyBuffer[..<newline]
        readyBuffer.removeSubrange(...newline)
        guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
              let port = object["port"] as? Int, (1...65535).contains(port),
              let token = object["token"] as? String, !token.isEmpty,
              let url = URL(string: "http://127.0.0.1:\(port)/") else { showError("本機服務啟動回應格式不符。"); return }
        launched = true
        origin = url
        self.token = token
        startNotices()
        let cookie = HTTPCookie(properties: [.domain: "127.0.0.1", .path: "/", .name: "swarmr_session", .value: token, HTTPCookiePropertyKey("HttpOnly"): "TRUE", HTTPCookiePropertyKey("SameSite"): "Strict"])!
        webView.configuration.websiteDataStore.httpCookieStore.setCookie(cookie) { [weak self] in
            self?.webView.load(URLRequest(url: url))
        }
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Zook 無法啟動"
        alert.informativeText = message
        alert.addButton(withTitle: "好")
        if window != nil { alert.beginSheetModal(for: window) } else { alert.runModal() }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload { decisionHandler(.download); return }
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" || url.scheme == "blob" { decisionHandler(.allow); return }
        if let origin = origin, url.host == origin.host && url.port == origin.port && url.scheme == origin.scheme {
            decisionHandler(.allow)
        } else {
            if action.navigationType == .linkActivated, ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { downloads.append(download); download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { downloads.append(download); download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.url : nil) }
    }
    func downloadDidFinish(_ download: WKDownload) { downloads.removeAll { $0 === download } }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) { downloads.removeAll { $0 === download } }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = "Zook"; alert.informativeText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    // File pickers on the page (importing a settings pack) open the standard macOS panel.
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = "Zook"; alert.informativeText = message
        alert.addButton(withTitle: "確定"); alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }
    // Mac notifications for schedules. The backend keeps a short queue; this asks for new entries every few seconds
    // (the page itself may be paused while the window is hidden, so the app does it, not the page).
    private func startNotices() {
        guard Bundle.main.bundleIdentifier != nil else { return }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
        noticeTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.pollNotices() }
    }

    private func pollNotices() {
        guard !noticeBusy, let origin = origin, let url = URL(string: "api/notifications?after=\(noticeSeq)", relativeTo: origin) else { return }
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        noticeBusy = true
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.noticeBusy = false
                guard let data = data, let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let seq = object["seq"] as? Int, let items = object["items"] as? [[String: Any]] else { return }
                if seq < self.noticeSeq { self.noticeSeq = 0; return }  // the backend restarted
                self.noticeSeq = seq
                for item in items.suffix(5) { self.post(item) }
            }
        }.resume()
    }

    private func post(_ item: [String: Any]) {
        let content = UNMutableNotificationContent()
        content.title = item["title"] as? String ?? "Zook"
        content.body = item["body"] as? String ?? ""
        content.sound = .default
        content.userInfo = ["kind": item["kind"] as? String ?? "", "id": item["targetId"] as? String ?? "", "messageId": item["messageId"] as? String ?? ""]
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "zook-\(item["seq"] as? Int ?? 0)-\(UUID().uuidString)", content: content, trigger: nil))
    }

    // Show banners while Zook is in front, too.
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }

    // Clicking a notification brings Zook forward on that conversation.
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        let args = [info["kind"] as? String ?? "", info["id"] as? String ?? "", info["messageId"] as? String ?? ""]
        DispatchQueue.main.async {
            if self.window.isMiniaturized { self.window.deminiaturize(nil) }
            self.window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            if self.launched && self.webView.url?.scheme == "http" { self.open(args) } else { self.pendingOpen = args }
            completionHandler()
        }
    }

    private func open(_ args: [String]) {
        if let json = try? JSONSerialization.data(withJSONObject: args), let list = String(data: json, encoding: .utf8) {
            webView.evaluateJavaScript("window.zookOpen && window.zookOpen(...\(list))", completionHandler: nil)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView.url?.scheme == "http", let args = pendingOpen else { return }
        pendingOpen = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.open(args) }  // let the page load its data first
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        noticeTimer?.invalidate()
        let task = backend; backend = nil
        if task?.isRunning == true { task?.terminate(); task?.waitUntilExit() }
    }
}

let app = NSApplication.shared
let delegate = ZookApp()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
