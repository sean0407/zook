import AppKit
import Network
import WebKit

// Zook's browser for Bots: `Zook --zook-browser`, started by the backend for one reply and closed after it.
// It reads one JSON command per line on stdin and answers one JSON line on stdout. The first command is "setup" with the
// address and password of the backend's filtering proxy, so neither is visible to other programs on this Mac.
//
// It reads pages and types into search boxes (the backend asks the user before every typing). What it will not do: type into
// sign-in or password fields, send forms with POST, download, upload, open new windows, or reach this Mac or the local network.
//   - Its own website data store, never saved (no cookies or sign-ins from anywhere else; gone when it exits).
//   - Every connection goes through the backend's proxy, which resolves each name itself and refuses private addresses.
//     A content rule list also refuses addresses that are private on their face, before they reach the proxy.
//   - Only GET navigations to http(s) (a search form sent with GET is one); POST, downloads, file pickers, new windows and
//     sign-in prompts are refused.
//   - Pages are read from Zook's own script world, so a page's scripts cannot change what Zook reads.
final class BrowserHelper: NSObject, WKNavigationDelegate, WKUIDelegate {
    private var web: WKWebView?
    private var window: NSWindow?
    private var waiting: ((String?) -> Void)?
    private var blocked = ""
    private var deadline: DispatchWorkItem?

    static let rulesName = "zook-browser-rules"
    static let privateHosts = #"^[a-z]+://([^/@]*@)?(localhost|[^/:]*\.local|[^/:]*\.localhost|[^/:]*\.internal|[^/:]*\.home\.arpa|127\.[0-9.]+|10\.[0-9.]+|0\.[0-9.]+|192\.168\.[0-9.]+|169\.254\.[0-9.]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9.]+|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9.]+|\[[^\]]*\])([:/?#]|$)"#
    // The same, as content-blocker filters (they have no "or", so one filter each). The proxy is the real check; this one only
    // stops such loads before they get there.
    static let blockedFilters: [String] = {
        let start = "^[a-z]+://([^/@]*@)?"
        var list = ["127\\.", "10\\.", "0\\.", "192\\.168\\.", "169\\.254\\.", "172\\.1[6-9]\\.", "172\\.2[0-9]\\.", "172\\.3[01]\\.",
                    "100\\.6[4-9]\\.", "100\\.[7-9][0-9]\\.", "100\\.1[01][0-9]\\.", "100\\.12[0-7]\\.", "\\["].map { start + $0 }
        for name in ["localhost", "[^/:?#]*\\.localhost", "[^/:?#]*\\.local", "[^/:?#]*\\.internal", "[^/:?#]*\\.home\\.arpa"] {
            list += [start + name + "[:/?#]", start + name + "$"]
        }
        list += [start + "[^/:?#]*\\.[:/?#]", start + "[^/:?#]*\\.$"]  // any host ending in a dot ("localhost." skips the proxy)
        return list + ["^file:"]
    }()

    func run() {
        let stdin = FileHandle.standardInput
        DispatchQueue.global().async {
            var buffer = Data()
            while true {
                let chunk = stdin.availableData
                if chunk.isEmpty { DispatchQueue.main.async { exit(0) } ; return }  // Zook went away: nothing of this session is kept
                buffer.append(chunk)
                while let newline = buffer.firstIndex(of: 10) {
                    let line = buffer[..<newline]; buffer.removeSubrange(...newline)
                    if let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
                        let sem = DispatchSemaphore(value: 0)
                        DispatchQueue.main.async { self.handle(object) { sem.signal() } }
                        sem.wait()
                    } else { BrowserHelper.say(["error": "bad command"]) }
                }
                if buffer.count > 1_000_000 { buffer.removeAll() }
            }
        }
    }

    static func say(_ value: [String: Any]) {
        let data = (try? JSONSerialization.data(withJSONObject: value)) ?? (try? JSONSerialization.data(withJSONObject: ["error": "這個網頁的內容無法轉成文字。"])) ?? Data()
        FileHandle.standardOutput.write(data + Data([10]))
    }

    private func handle(_ command: [String: Any], done: @escaping () -> Void) {
        let reply: ([String: Any]) -> Void = { BrowserHelper.say($0); done() }
        switch command["cmd"] as? String ?? "" {
        case "setup": setup(command, reply)
        case "open": open(command["url"] as? String ?? "", reply)
        case "read": read(reply)
        case "scroll": scroll((command["dir"] as? String) == "up" ? -1 : 1, reply)
        case "shot": shot(reply)
        case "type": type(command, reply)
        case "quit": BrowserHelper.say(["ok": true]); exit(0)
        default: reply(["error": "unknown command"])
        }
    }

    private func setup(_ command: [String: Any], _ reply: @escaping ([String: Any]) -> Void) {
        guard web == nil else { reply(["error": "already set up"]); return }
        guard #available(macOS 14.0, *) else { reply(["error": "需要 macOS 14 以上才能使用內建瀏覽器。"]); return }
        guard let port = command["proxyPort"] as? Int, (1...65535).contains(port), let user = command["user"] as? String, let pass = command["pass"] as? String,
              let nwPort = NWEndpoint.Port(rawValue: UInt16(port)) else { reply(["error": "bad setup"]); return }
        let store = WKWebsiteDataStore.nonPersistent()
        var proxy = ProxyConfiguration(httpCONNECTProxy: .hostPort(host: "127.0.0.1", port: nwPort))
        proxy.applyCredential(username: user, password: pass)
        proxy.allowFailover = false
        store.proxyConfigurations = [proxy]
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = store
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.applicationNameForUserAgent = "Version/18.0 Safari/605.1.15"
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        configuration.preferences.isElementFullscreenEnabled = false
        // No peer-to-peer connections: they would not go through the proxy.
        let noPeers = "for (const k of ['RTCPeerConnection','webkitRTCPeerConnection','RTCDataChannel']) { try { Object.defineProperty(window, k, {value: undefined, configurable: false}); } catch (e) {} }"
        configuration.userContentController.addUserScript(WKUserScript(source: noPeers, injectionTime: .atDocumentStart, forMainFrameOnly: false))
        let filters = BrowserHelper.blockedFilters.map { ["trigger": ["url-filter": $0, "url-filter-is-case-sensitive": false], "action": ["type": "block"]] }
        guard let encoded = try? JSONSerialization.data(withJSONObject: filters), let rules = String(data: encoded, encoding: .utf8) else { reply(["error": "rules"]); return }
        let rulesStore = WKContentRuleListStore.default()!
        rulesStore.getAvailableContentRuleListIdentifiers { names in
            for name in names ?? [] where name.hasPrefix("zook-browser-") && name != BrowserHelper.rulesName { rulesStore.removeContentRuleList(forIdentifier: name) { _ in } }
        }
        rulesStore.compileContentRuleList(forIdentifier: BrowserHelper.rulesName, encodedContentRuleList: rules) { list, error in
            guard let list = list else { reply(["error": "rules: \(error?.localizedDescription ?? "?")"]); return }
            configuration.userContentController.add(list)
            let view = WKWebView(frame: NSRect(x: 0, y: 0, width: 1280, height: 900), configuration: configuration)
            view.navigationDelegate = self
            view.uiDelegate = self
            view.customUserAgent = nil
            // A window far off screen, so pages run and draw as they would for a person, without showing anything.
            let window = NSWindow(contentRect: NSRect(x: -30000, y: -30000, width: 1280, height: 900), styleMask: [.borderless], backing: .buffered, defer: false)
            window.contentView = view
            window.ignoresMouseEvents = true
            window.isReleasedWhenClosed = false
            window.orderFrontRegardless()
            self.web = view; self.window = window
            reply(["ok": true])
        }
    }

    // MARK: pages

    static func allowedURL(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased(), scheme == "https" || scheme == "http", let host = url.host, !host.isEmpty else { return false }
        if url.user != nil || url.password != nil || host.hasSuffix(".") { return false }  // "localhost." would not go through the proxy
        return url.absoluteString.range(of: privateHosts, options: [.regularExpression, .caseInsensitive]) == nil
    }

    private func open(_ address: String, _ reply: @escaping ([String: Any]) -> Void) {
        guard let web = web else { reply(["error": "not set up"]); return }
        guard let url = URL(string: address), BrowserHelper.allowedURL(url) else { reply(["error": "只能開啟一般的 http 或 https 網址，不能連到這台 Mac 或區域網路。"]); return }
        blocked = ""
        finish(nil)
        waiting = { [weak self] failure in
            guard let self = self else { return }
            if let failure = failure { reply(["error": failure, "url": web.url?.absoluteString ?? ""]); return }
            self.settle(stable: 0, last: -1, tries: 0) { reply(["ok": true, "url": web.url?.absoluteString ?? "", "title": web.title ?? ""]) }
        }
        let item = DispatchWorkItem { [weak self] in self?.finish(nil) }  // a slow page: read what has loaded by now
        deadline = item
        DispatchQueue.main.asyncAfter(deadline: .now() + 25, execute: item)
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 25)
        request.httpMethod = "GET"
        web.load(request)
    }

    private func finish(_ failure: String?) {
        deadline?.cancel(); deadline = nil
        let next = waiting; waiting = nil
        next?(failure)
    }

    // Pages that build themselves with scripts: wait until the text stops changing (at most about 8 seconds).
    private func settle(stable: Int, last: Int, tries: Int, then: @escaping () -> Void) {
        guard let web = web else { then(); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + (tries == 0 ? 0.8 : 0.5)) {
            web.evaluateJavaScript("[document.readyState, (document.body ? document.body.innerText.length : 0)]", in: nil, in: .defaultClient) { result in
                let parts = (try? result.get()) as? [Any] ?? []
                let length = parts.count > 1 ? (parts[1] as? Int ?? 0) : 0
                let ready = parts.first as? String == "complete"
                let now = (ready && length == last && length > 0) ? stable + 1 : 0
                if now >= 2 || tries >= 15 { then() } else { self.settle(stable: now, last: length, tries: tries + 1, then: then) }
            }
        }
    }

    // The fields a Bot may type into, in page order: search boxes only. A field counts as one when it says so (type=search,
    // role=searchbox), when it belongs to a form sent with GET (a search form), or when its own name, label or placeholder says
    // search. Never a field that looks like a sign-in, password, e-mail, phone, code or card, hides what is typed, sits in a form
    // or small block that has a password field (shadow DOM included), or cannot really be seen.
    // Strings are made well-formed, so a broken character on a page cannot break the reply.
    private static let fieldsScript = """
    const wf = v => { const s = String(v == null ? '' : v); return s.toWellFormed ? s.toWellFormed() : s.replace(/[\\uD800-\\uDBFF](?![\\uDC00-\\uDFFF])|(?<![\\uD800-\\uDBFF])[\\uDC00-\\uDFFF]/g, '\\uFFFD'); };
    const words = v => String(v || '').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
    const SECRET_WORDS = new Set(['user', 'username', 'userid', 'login', 'logon', 'signin', 'signup', 'pass', 'password', 'passwd', 'pwd', 'passcode', 'mail', 'email',
      'otp', 'code', 'pin', 'card', 'cc', 'cvc', 'cvv', 'phone', 'tel', 'mobile', 'account', 'auth', 'token', 'key', 'apikey', 'secret', 'ssn']);
    const SECRET_ZH = /(帳號|帳戶|密碼|信箱|郵件|電話|手機|驗證|登入|註冊|卡號|身分證)/;
    const SEARCH_WORDS = new Set(['search', 'searchbox', 'query', 'q', 'find', 'filter', 'lookup', 'keyword', 'keywords', 'term', 'terms']);
    const SEARCH_ZH = /(搜尋|搜索|查詢|查找|篩選|關鍵字)/;
    // Every password box on the page, and boxes that hide what is typed, inside open shadow roots too (as the element in the page).
    const secretBoxes = () => {
      const out = [];
      const walk = root => {
        for (const el of root.querySelectorAll('input')) {
          const t = (el.getAttribute('type') || '').toLowerCase(), hide = getComputedStyle(el).webkitTextSecurity;
          if (t === 'password' || (hide && hide !== 'none')) out.push(el);
        }
        for (const el of root.querySelectorAll('*')) if (el.shadowRoot) walk(el.shadowRoot);
      };
      walk(document);
      return out.map(el => { let n = el; while (n.getRootNode() !== document && n.getRootNode().host) n = n.getRootNode().host; return n; });
    };
    const labelOf = el => {
      let label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.title || '';
      if (!label && el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) label = l.innerText; }
      if (!label && el.closest('label')) label = el.closest('label').innerText;
      return wf(label).replace(/\\s+/g, ' ').trim().slice(0, 80);
    };
    const zookFields = () => {
      const out = [], secrets = secretBoxes();
      for (const el of document.querySelectorAll('input, textarea')) {
        const type = (el.getAttribute('type') || 'text').toLowerCase();
        if (el.tagName === 'INPUT' && !['text', 'search', ''].includes(type)) continue;
        if (el.disabled || el.readOnly) continue;
        const style = getComputedStyle(el), box = el.getBoundingClientRect();
        if (style.webkitTextSecurity && style.webkitTextSecurity !== 'none') continue;
        if (box.width < 8 || box.height < 8 || style.visibility !== 'visible' || style.display === 'none' || parseFloat(style.opacity) < 0.3) continue;
        if (box.right + scrollX <= 0 || box.bottom + scrollY <= 0 || box.left + scrollX >= document.documentElement.scrollWidth) continue;
        if (el.checkVisibility && !el.checkVisibility({opacityProperty: true, visibilityProperty: true})) continue;
        const label = labelOf(el), hints = [el.name, el.id, el.getAttribute('autocomplete'), el.getAttribute('aria-label'), el.getAttribute('placeholder'), label].join(' ');
        const hintWords = words(hints);
        if (hintWords.some(w => SECRET_WORDS.has(w)) || SECRET_ZH.test(hints)) continue;
        // Nothing that shares a form or any block below the page itself with a password box: that is a sign-in.
        let near = el.parentElement, signIn = false;
        while (!signIn && near && near !== document.body && near !== document.documentElement) { signIn = secrets.some(p => near.contains(p)); near = near.parentElement; }
        if (signIn) continue;
        const form = el.form || el.closest('form');
        if (form && (form.getAttribute('method') || 'get').toLowerCase() !== 'get') continue;  // a form that sends data, not a search
        const search = type === 'search' || el.getAttribute('role') === 'searchbox' || el.closest('[role=search]') || hintWords.some(w => SEARCH_WORDS.has(w)) || SEARCH_ZH.test(hints);
        if (!search) continue;
        out.push([el, label || wf(el.name || '').slice(0, 80), el.tagName === 'TEXTAREA' ? 'textarea' : 'search', form ? wf(form.action || '').slice(0, 2000) : '']);
        if (out.length >= 50) break;
      }
      return out;
    };
    """

    private static let readScript = "(() => {\n" + fieldsScript + """
      const text = wf((document.body ? document.body.innerText : '') || '');
      const found = zookFields();
      globalThis.zookFieldList = found.map(f => ({el: f[0], label: f[1]}));  // Zook's script world only; the page cannot see it
      const fields = found.map(f => [f[1], f[2], wf(f[0].value || '').slice(0, 200), f[3]]);
      const links = [], seen = new Set();
      for (const a of document.querySelectorAll('a[href]')) {
        let href; try { href = new URL(a.getAttribute('href'), document.baseURI).href; } catch (e) { continue; }
        if (!/^https?:/i.test(href) || seen.has(href)) continue;
        seen.add(href);
        const label = wf(a.innerText || a.getAttribute('aria-label') || a.title || '').replace(/\\s+/g, ' ').trim().slice(0, 120);
        links.push([label, wf(href).slice(0, 2000)]);
        if (links.length >= 400) break;
      }
      return JSON.stringify({title: wf(document.title || '').slice(0, 300), url: wf(location.href).slice(0, 2000), text: text.slice(0, 400000), links, fields,
                             y: Math.round(scrollY), height: document.documentElement.scrollHeight, view: innerHeight});
    })()
    """

    private func read(_ reply: @escaping ([String: Any]) -> Void) {
        guard let web = web else { reply(["error": "not set up"]); return }
        web.evaluateJavaScript(BrowserHelper.readScript, in: nil, in: .defaultClient) { result in
            guard let text = (try? result.get()) as? String, let data = text.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { reply(["error": "這個網頁讀不到文字。"]); return }
            reply(object)
        }
    }

    private func scroll(_ direction: Int, _ reply: @escaping ([String: Any]) -> Void) {
        guard let web = web else { reply(["error": "not set up"]); return }
        web.evaluateJavaScript("window.scrollBy(0, \(direction) * Math.round(innerHeight * 0.85)); 1", in: nil, in: .defaultClient) { _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.read(reply) }  // let a page load what comes into view
        }
    }

    // Type into one field (its number in the list from "read"), as a person's typing would: the page sees input events. With enter,
    // the field's form is sent if it is a GET form (a search), otherwise Enter is pressed in the field for the page to handle.
    // Forms that would send with POST are still refused by the navigation rules below.
    private static let typeScript = fieldsScript + """
    const item = (globalThis.zookFieldList || [])[number - 1];
    if (!item || !item.el.isConnected || item.label !== label || location.href !== page) return 'changed';
    const action = () => { const form = item.el.form || item.el.closest('form'); return form ? wf(form.action || '').slice(0, 2000) : ''; };
    if (action() !== destination) return 'changed';  // where Enter would send it is not where the user approved
    const still = () => { const f = zookFields().find(x => x[0] === item.el); return f && f[1] === item.label ? f : null; };
    let f = still();
    if (!f) return 'changed';  // the page changed it since it was listed
    const el = f[0];
    el.scrollIntoView({block: 'center'}); el.focus();
    f = still();
    if (!f || location.href !== page || action() !== destination) return 'changed';  // the page's own focus handler changed it
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text);
    el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    if (!enter) return 'typed';
    const form = el.form || el.closest('form');
    const key = {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true};
    const going = el.dispatchEvent(new KeyboardEvent('keydown', key));
    el.dispatchEvent(new KeyboardEvent('keypress', key)); el.dispatchEvent(new KeyboardEvent('keyup', key));
    if (going && form && f[2] !== 'textarea') {
      if ((form.getAttribute('method') || 'get').toLowerCase() !== 'get') return 'post form';
      if (action() !== destination) return 'changed after typing';
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    }
    return 'sent';
    """

    private func type(_ command: [String: Any], _ reply: @escaping ([String: Any]) -> Void) {
        guard let web = web else { reply(["error": "not set up"]); return }
        guard let number = command["field"] as? Int, number > 0, let text = command["text"] as? String, text.count <= 2000,
              let label = command["label"] as? String, let page = command["page"] as? String, let destination = command["action"] as? String else { reply(["error": "bad type"]); return }
        let enter = command["enter"] as? Bool ?? false
        blocked = ""
        let before = web.url?.absoluteString ?? ""
        web.callAsyncJavaScript(BrowserHelper.typeScript, arguments: ["number": number, "text": text, "enter": enter, "label": label, "page": page, "destination": destination], in: nil, in: .defaultClient) { result in
            let outcome = (try? result.get()) as? String ?? ""
            if outcome == "changed" { reply(["error": "網頁或這個欄位在核准後變了，Zook 沒有輸入。先用 zook_browser_read 重新看欄位清單再試。"]); return }
            if outcome == "post form" { reply(["error": "文字已輸入，但這個表單會送出資料（不是搜尋），Zook 不幫忙送出。"]); return }
            if outcome == "changed after typing" { reply(["error": "文字已輸入，但表單要送去的地方變了，Zook 沒有按 Enter。"]); return }
            guard outcome == "typed" || outcome == "sent" else { reply(["error": "輸入時網頁出錯，不確定有沒有輸入成功。"]); return }
            guard enter else { reply(["ok": true, "url": web.url?.absoluteString ?? "", "title": web.title ?? ""]); return }
            // Give the page a moment; if it went to a new page, wait for that page as "open" does.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                let done: (String?) -> Void = { failure in  // the helper lives until the process ends
                    if let failure = failure { reply(["error": failure, "url": web.url?.absoluteString ?? ""]); return }
                    self.settle(stable: 0, last: -1, tries: 0) {
                        let why = self.blocked
                        reply(why.isEmpty ? ["ok": true, "url": web.url?.absoluteString ?? "", "title": web.title ?? "", "moved": (web.url?.absoluteString ?? "") != before]
                                          : ["error": "Zook 擋下了這個網頁的\(why)。", "url": web.url?.absoluteString ?? ""])
                    }
                }
                if web.isLoading {
                    self.waiting = done
                    let item = DispatchWorkItem { self.finish(nil) }
                    self.deadline = item
                    DispatchQueue.main.asyncAfter(deadline: .now() + 20, execute: item)
                } else { done(nil) }
            }
        }
    }

    private func shot(_ reply: @escaping ([String: Any]) -> Void) {
        guard let web = web else { reply(["error": "not set up"]); return }
        let config = WKSnapshotConfiguration()
        config.snapshotWidth = 1024
        web.takeSnapshot(with: config) { image, error in
            guard let image = image, let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
                  let jpeg = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.6]) else {
                reply(["error": "截圖失敗：\(error?.localizedDescription ?? "")"]); return
            }
            reply(["jpeg": jpeg.base64EncodedString()])
        }
    }

    // MARK: what pages may do

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = action.request.url
        if action.shouldPerformDownload { blocked = "下載"; decisionHandler(.cancel); return }
        if action.targetFrame?.isMainFrame == false && (url?.scheme == "about" || url?.scheme == "data") { decisionHandler(.allow); return }
        guard let url = url, BrowserHelper.allowedURL(url) else { blocked = "不允許的網址"; decisionHandler(.cancel); return }
        // A form sent with GET is only an address (a search); the page's own scripts can go to any address anyway. Anything sent
        // with POST (or re-sent) carries data to the site, and is refused.
        if action.navigationType == .formResubmitted || (action.request.httpMethod ?? "GET").uppercased() != "GET" {
            blocked = "送出表單"; decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if !response.canShowMIMEType { blocked = "下載"; decisionHandler(.cancel); return }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didReceive challenge: URLAuthenticationChallenge, completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust { completionHandler(.performDefaultHandling, nil) }
        else { blocked = "登入"; completionHandler(.cancelAuthenticationChallenge, nil) }  // no sign-in prompts, no client certificates
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { finish(nil) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { finish(failure(error)) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { finish(failure(error)) }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { finish("這個網頁讓瀏覽器停止了。") }

    private func failure(_ error: Error) -> String? {
        let code = (error as NSError).code
        if code == NSURLErrorCancelled || code == 102 /* frame load interrupted */ {
            return blocked.isEmpty ? nil : "Zook 擋下了這個網頁的\(blocked)。"
        }
        if !blocked.isEmpty { return "Zook 擋下了這個網頁的\(blocked)。" }
        return "網頁打不開：\(error.localizedDescription)"
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? { nil }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) { completionHandler() }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) { completionHandler(false) }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) { completionHandler(nil) }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) { completionHandler(nil) }
    @available(macOS 12.0, *)
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) { decisionHandler(.deny) }
}

func runBrowserHelper() -> Never {
    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    let helper = BrowserHelper()
    helper.run()
    withExtendedLifetime(helper) { app.run() }
    exit(0)
}
