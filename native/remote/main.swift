// zook-remote: the Mac side of Zook's remote access, plus a command-line "device" used to test it.
//
//   zook-remote info --state-dir DIR                     create (once) and print this Mac's room id and public key
//   zook-remote qr TEXT OUT.png                          draw a QR code
//   zook-remote host --state-dir DIR --relay URL --backend URL      (the bridge token on standard input with --token-stdin)
//   zook-remote device-pair --state FILE --payload zook://pair?d=... --name NAME
//   zook-remote device-request --state FILE --method GET --path /api/state [--body JSON] [--timeout 20]
//
// The Mac's private key stays in DIR/remote-host.json (mode 600) and is only read by this program.
import AppKit
import CoreImage
import CryptoKit
import Foundation

let queue = DispatchQueue(label: "zook.remote")
var arguments = Array(CommandLine.arguments.dropFirst())

func option(_ name: String) -> String? {
    guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else { return nil }
    return arguments[index + 1]
}

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8)); exit(code)
}

func printJSON(_ object: [String: Any]) {
    let data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data()
    FileHandle.standardOutput.write(data + Data("\n".utf8))
}

func readJSON(_ path: String) -> [String: Any]? {
    guard let data = FileManager.default.contents(atPath: path) else { return nil }
    return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
}

func writePrivateJSON(_ object: [String: Any], to path: String) {
    let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    FileManager.default.createFile(atPath: path, contents: data, attributes: [.posixPermissions: 0o600])
    try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path)
}

/// This Mac's identity for remote access: its key pair, the room it uses on the relay, and the key that proves the room is its own.
struct HostIdentity {
    let keys: RemoteKeys, room: String, roomKey: String
    static func load(stateDir: String) -> HostIdentity {
        let path = stateDir + "/remote-host.json"
        if let saved = readJSON(path), let priv = saved["privateKey"] as? String, let room = saved["room"] as? String, let roomKey = saved["roomKey"] as? String,
           let keys = try? RemoteKeys(privateB64: priv) { return HostIdentity(keys: keys, room: room, roomKey: roomKey) }
        let fresh = HostIdentity(keys: RemoteKeys(), room: randomHex(16), roomKey: randomHex(32))
        writePrivateJSON(["privateKey": fresh.keys.privateB64, "room": fresh.room, "roomKey": fresh.roomKey], to: path)
        return fresh
    }
}

/// A WebSocket whose callbacks arrive on `queue`.
final class Socket: NSObject, URLSessionWebSocketDelegate {
    private var task: URLSessionWebSocketTask!
    private var session: URLSession!
    private var closed = false
    var onOpen: (() -> Void)?
    var onText: ((String) -> Void)?
    var onClose: (() -> Void)?

    init(url: URL, headers: [String: String] = [:]) {
        super.init()
        let operations = OperationQueue(); operations.underlyingQueue = queue
        session = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: operations)
        var request = URLRequest(url: url); request.timeoutInterval = 20
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        task = session.webSocketTask(with: request)
        task.maximumMessageSize = 4 * 1024 * 1024
    }

    func start() { task.resume(); receive(); keepAlive() }

    /// A connection can die without either end being told (the Mac slept, the network changed). Ping regularly and
    /// treat a missing answer as a closed connection, so the owner reconnects instead of waiting on a dead line.
    private func keepAlive() {
        queue.asyncAfter(deadline: .now() + 20) { [weak self] in
            guard let self = self, !self.closed else { return }
            var answered = false
            self.task.sendPing { [weak self] error in queue.async { answered = true; if error != nil { self?.finish() } } }
            queue.asyncAfter(deadline: .now() + 10) { [weak self] in
                guard let self = self, !self.closed else { return }
                if answered { self.keepAlive() } else { self.finish() }
            }
        }
    }

    private func receive() {
        task.receive { [weak self] result in
            queue.async {
                guard let self = self, !self.closed else { return }
                switch result {
                case .failure: self.finish()
                case .success(let message):
                    if case .string(let text) = message { self.onText?(text) }
                    self.receive()
                }
            }
        }
    }

    func send(_ object: [String: Any]) {
        guard !closed, let data = try? JSONSerialization.data(withJSONObject: object), let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { [weak self] error in if error != nil { queue.async { self?.finish() } } }
    }

    func close() { task.cancel(with: .normalClosure, reason: nil); finish() }

    private func finish() {
        if closed { return }
        closed = true; session.invalidateAndCancel(); onClose?()
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) { onOpen?() }
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) { finish() }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) { finish() }
}

func relayURL(_ base: String, room: String, role: String) -> URL {
    guard let url = URL(string: base.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/v1/room/" + room + "/" + role),
          ["ws", "wss"].contains(url.scheme ?? "") else { fail("中繼伺服器網址無效。") }
    return url
}

// MARK: - Mac side

final class Host {
    struct Connection { var session: RemoteSession?; var device: String?; var pairingPublic: String?; var pairingSecret: String? }
    let identity: HostIdentity, relay: String, backend: String, token: String
    var socket: Socket?
    var connections: [String: Connection] = [:]
    var retry = 2.0
    var unreachable = 0
    var statusTimer: DispatchSourceTimer?
    let http = URLSession(configuration: .ephemeral)

    init(identity: HostIdentity, relay: String, backend: String, token: String) {
        self.identity = identity; self.relay = relay; self.backend = backend; self.token = token
    }

    /// Calls Zook's own backend on this Mac. `device` marks the request as coming from that paired device.
    func call(_ method: String, _ path: String, body: Data? = nil, device: String? = nil, done: @escaping (Int, Data) -> Void) {
        guard path.hasPrefix("/api/"), let url = URL(string: backend + path) else { return done(400, Data()) }
        var request = URLRequest(url: url); request.httpMethod = method; request.timeoutInterval = 60
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        if let device = device { request.setValue(device, forHTTPHeaderField: "X-Zook-Device") }
        if let body = body { request.httpBody = body; request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        http.dataTask(with: request) { data, response, _ in
            queue.async { done((response as? HTTPURLResponse)?.statusCode ?? 502, data ?? Data()) }
        }.resume()
    }

    func json(_ data: Data) -> [String: Any] { ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any]) ?? [:] }

    func connect() {
        let socket = Socket(url: relayURL(relay, room: identity.room, role: "host"), headers: ["X-Zook-Room-Key": identity.roomKey])
        self.socket = socket
        socket.onOpen = { [weak self] in self?.retry = 2.0; self?.report(connected: true) }
        socket.onText = { [weak self] text in self?.handle(text) }
        socket.onClose = { [weak self] in
            guard let self = self else { return }
            self.connections.removeAll(); self.socket = nil; self.report(connected: false)
            queue.asyncAfter(deadline: .now() + self.retry) { self.connect() }
            self.retry = min(self.retry * 2, 30)
        }
        socket.start()
    }

    func report(connected: Bool) {
        let online = Array(Set(connections.values.compactMap { $0.session != nil ? $0.device : nil }))
        let body = try? JSONSerialization.data(withJSONObject: ["connected": connected, "online": online])
        call("POST", "/api/remote/bridge/status", body: body) { [weak self] status, data in
            guard let self = self else { return }
            // Zook itself has gone away (quit or crashed): do not stay connected to the relay on its behalf.
            self.unreachable = status == 502 ? self.unreachable + 1 : 0
            if self.unreachable >= 4 { exit(0) }
            if status == 403 || (status == 200 && (self.json(data)["enabled"] as? Bool) == false) { exit(0) }  // turned off in Zook
            guard status == 200, let valid = self.json(data)["devices"] as? [String] else { return }
            for (conn, state) in self.connections where state.session != nil && state.pairingPublic == nil {
                if let device = state.device, !valid.contains(device) { self.drop(conn) }  // revoked while connected
            }
        }
    }

    func drop(_ conn: String) {
        connections[conn] = nil
        socket?.send(["c": conn, "event": "close"])
    }

    func reply(_ conn: String, _ message: [String: Any]) {
        guard let session = connections[conn]?.session, let frames = try? session.seal(message) else { return }
        for frame in frames { socket?.send(["c": conn, "d": frame]) }
    }

    func handle(_ text: String) {
        guard let message = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any], let conn = message["c"] as? String else { return }
        if let event = message["event"] as? String {
            if event == "open" { connections[conn] = Connection() } else if event == "close" { connections[conn] = nil }
            return
        }
        guard let frame = message["d"] as? String else { return }
        if connections[conn] == nil { connections[conn] = Connection() }
        if frame.hasPrefix("H") { return hello(conn, frame) }
        guard let session = connections[conn]?.session else { return drop(conn) }
        do {
            guard let request = try session.open(frame) else { return }
            serve(conn, request)
        } catch { drop(conn) }  // wrong key, replayed or tampered frame
    }

    func hello(_ conn: String, _ frame: String) {
        guard connections[conn]?.session == nil, let hello = parseHello(frame), let deviceNonce = Data(base64Encoded: hello["nonce"] as? String ?? ""),
              deviceNonce.count == 16 else { return drop(conn) }
        let hostNonce = randomBytes(16)
        let finish: (String, String, String?) -> Void = { [weak self] device, publicKey, secret in
            guard let self = self, self.connections[conn] != nil,
                  let session = try? RemoteSession(mine: self.identity.keys.privateKey, theirPublicB64: publicKey, deviceNonce: deviceNonce, hostNonce: hostNonce, pairingSecret: secret, isHost: true)
            else { self?.drop(conn); return }
            self.connections[conn] = Connection(session: session, device: device, pairingPublic: secret == nil ? nil : publicKey, pairingSecret: secret)
            self.socket?.send(["c": conn, "d": helloFrame(["v": 1, "nonce": hostNonce.base64EncodedString()])])
        }
        if (hello["pairing"] as? Bool) == true, let publicKey = hello["pub"] as? String {
            // A new device: it can only talk to us if it knows the one-time secret from the QR code shown on this Mac.
            call("GET", "/api/remote/bridge/pairing") { [weak self] status, data in
                guard status == 200, let secret = self?.json(data)["secret"] as? String else { self?.drop(conn); return }
                finish(RemoteKeys.deviceId(publicB64: publicKey), publicKey, secret)
            }
        } else if let device = hello["device"] as? String {
            call("GET", "/api/remote/bridge/devices") { [weak self] status, data in
                let devices = (self?.json(data)["list"] as? [[String: Any]]) ?? []
                guard status == 200, let entry = devices.first(where: { $0["id"] as? String == device }), let publicKey = entry["publicKey"] as? String else { self?.drop(conn); return }
                finish(device, publicKey, nil)
            }
        } else { drop(conn) }
    }

    func serve(_ conn: String, _ request: [String: Any]) {
        guard let state = connections[conn], let device = state.device, let id = request["id"] else { return drop(conn) }
        if let pairingPublic = state.pairingPublic {
            // The first sealed message of a pairing connection registers the device.
            let name = String((request["name"] as? String ?? "裝置").prefix(60))
            let body = try? JSONSerialization.data(withJSONObject: ["id": device, "publicKey": pairingPublic, "name": name, "secret": state.pairingSecret ?? ""])
            call("POST", "/api/remote/bridge/paired", body: body) { [weak self] status, data in
                self?.reply(conn, ["id": id, "status": status, "text": String(data: data, encoding: .utf8) ?? ""])
                queue.asyncAfter(deadline: .now() + 0.5) { self?.drop(conn) }  // the device reconnects with its own key
            }
            return
        }
        guard let method = request["method"] as? String, ["GET", "POST", "PATCH", "DELETE"].contains(method), let path = request["path"] as? String else { return drop(conn) }
        let body = (request["body"] as? String).map { Data($0.utf8) }
        call(method, path, body: body, device: device) { [weak self] status, data in
            if status == 401 { self?.drop(conn); return }  // no longer a paired device
            self?.reply(conn, ["id": id, "status": status, "text": String(data: data, encoding: .utf8) ?? ""])
        }
    }

    func run() {
        queue.async { self.connect() }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 3, repeating: 3)
        timer.setEventHandler { [weak self] in self?.report(connected: self?.socket != nil) }
        timer.resume()
        statusTimer = timer  // kept for the life of the program
        signal(SIGTERM) { _ in exit(0) }
        dispatchMain()
    }
}

// MARK: - Device side (command line; the iPhone app follows the same steps)

final class Device {
    let keys: RemoteKeys, relay: String, room: String, hostKey: String
    var session: RemoteSession?
    var socket: Socket!
    var sentHello = false
    let nonce = randomBytes(16)
    let pairingSecret: String?
    var onReady: (() -> Void)?
    var onMessage: (([String: Any]) -> Void)?

    init(keys: RemoteKeys, relay: String, room: String, hostKey: String, pairingSecret: String?) {
        self.keys = keys; self.relay = relay; self.room = room; self.hostKey = hostKey; self.pairingSecret = pairingSecret
    }

    func start() {
        socket = Socket(url: relayURL(relay, room: room, role: "device"))
        socket.onText = { [weak self] text in self?.handle(text) }
        socket.onClose = { fail("連線已被關閉。", code: 4) }
        socket.start()
    }

    func handle(_ text: String) {
        guard let message = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any] else { return }
        if message["event"] as? String == "host" {
            if message["online"] as? Bool == true, !sentHello {
                sentHello = true
                var hello: [String: Any] = ["v": 1, "device": keys.id, "nonce": nonce.base64EncodedString()]
                if pairingSecret != nil { hello["pairing"] = true; hello["pub"] = keys.publicB64 }
                socket.send(["d": helloFrame(hello)])
            } else if message["online"] as? Bool == false, session != nil { fail("連不到你的 Mac。", code: 3) }
            return
        }
        guard let frame = message["d"] as? String else { return }
        if frame.hasPrefix("H"), session == nil {
            guard let hello = parseHello(frame), let hostNonce = Data(base64Encoded: hello["nonce"] as? String ?? ""),
                  let made = try? RemoteSession(mine: keys.privateKey, theirPublicB64: hostKey, deviceNonce: nonce, hostNonce: hostNonce, pairingSecret: pairingSecret, isHost: false)
            else { fail("無法建立加密連線。", code: 4) }
            session = made; onReady?()
            return
        }
        guard let session = session else { return }
        do { if let message = try session.open(frame) { onMessage?(message) } } catch { fail("收到無法解開的訊息。", code: 4) }
    }

    func send(_ message: [String: Any]) {
        guard let frames = try? session?.seal(message) else { return }
        for frame in frames { socket.send(["d": frame]) }
    }
}

func runDevice(_ device: Device, timeout: Double, request: [String: Any], done: @escaping ([String: Any]) -> Void) -> Never {
    device.onReady = { device.send(request) }
    device.onMessage = { message in done(message); exit(0) }
    queue.async { device.start() }
    queue.asyncAfter(deadline: .now() + timeout) { fail("連不到你的 Mac（等待逾時）。", code: 3) }
    dispatchMain()
}

// MARK: - Commands

guard let command = arguments.first else { fail("usage: zook-remote info|qr|host|device-pair|device-request ...") }

switch command {
case "info":
    guard let dir = option("--state-dir") else { fail("--state-dir required") }
    let identity = HostIdentity.load(stateDir: dir)
    printJSON(["room": identity.room, "publicKey": identity.keys.publicB64])

case "qr":
    guard arguments.count >= 3, let filter = CIFilter(name: "CIQRCodeGenerator") else { fail("usage: zook-remote qr TEXT OUT.png") }
    filter.setValue(Data(arguments[1].utf8), forKey: "inputMessage"); filter.setValue("M", forKey: "inputCorrectionLevel")
    guard let image = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)) else { fail("cannot draw QR code") }
    let rep = NSBitmapImageRep(ciImage: image)
    guard let png = rep.representation(using: .png, properties: [:]) else { fail("cannot encode QR code") }
    do { try png.write(to: URL(fileURLWithPath: arguments[2]), options: .atomic) } catch { fail("cannot write QR code") }

case "host":
    guard let dir = option("--state-dir"), let relay = option("--relay"), let backend = option("--backend"),
          let token = (CommandLine.arguments.contains("--token-stdin") ? readLine(strippingNewline: true) : ProcessInfo.processInfo.environment["ZOOK_BRIDGE_TOKEN"]), !token.isEmpty else { fail("host needs --state-dir, --relay, --backend and ZOOK_BRIDGE_TOKEN") }
    let host = Host(identity: HostIdentity.load(stateDir: dir), relay: relay, backend: backend, token: token)
    withExtendedLifetime(host) { host.run() }

case "device-pair":
    guard let state = option("--state"), let payload = PairingPayload(url: option("--payload") ?? "") else { fail("device-pair needs --state and --payload") }
    let keys = RemoteKeys()
    let device = Device(keys: keys, relay: payload.relay, room: payload.room, hostKey: payload.hostKey, pairingSecret: payload.secret)
    runDevice(device, timeout: Double(option("--timeout") ?? "20") ?? 20, request: ["id": 1, "name": option("--name") ?? "測試裝置"]) { message in
        let status = message["status"] as? Int ?? 0
        if status == 200 {
            writePrivateJSON(["privateKey": keys.privateB64, "relay": payload.relay, "room": payload.room, "hostKey": payload.hostKey, "device": keys.id], to: state)
        }
        printJSON(["status": status, "text": message["text"] as? String ?? "", "device": keys.id])
        if status != 200 { exit(5) }
    }

case "device-request":
    guard let state = option("--state"), let saved = readJSON(state), let keys = try? RemoteKeys(privateB64: saved["privateKey"] as? String ?? ""),
          let relay = saved["relay"] as? String, let room = saved["room"] as? String, let hostKey = saved["hostKey"] as? String,
          let path = option("--path") else { fail("device-request needs a paired --state file and --path") }
    var request: [String: Any] = ["id": 1, "method": option("--method") ?? "GET", "path": path]
    if let body = option("--body") { request["body"] = body }
    let device = Device(keys: keys, relay: relay, room: room, hostKey: hostKey, pairingSecret: nil)
    runDevice(device, timeout: Double(option("--timeout") ?? "20") ?? 20, request: request) { message in
        printJSON(["status": message["status"] as? Int ?? 0, "text": message["text"] as? String ?? ""])
    }

case "selftest":
    // Checks of the encryption layer that need no network.
    func check(_ ok: Bool, _ what: String) { if !ok { fail("selftest failed: " + what) } }
    let hostKeys = RemoteKeys(), deviceKeys = RemoteKeys(), dn = randomBytes(16), hn = randomBytes(16)
    func pairOf(secret: String?, hostSecret: String?) throws -> (RemoteSession, RemoteSession) {
        (try RemoteSession(mine: deviceKeys.privateKey, theirPublicB64: hostKeys.publicB64, deviceNonce: dn, hostNonce: hn, pairingSecret: secret, isHost: false),
         try RemoteSession(mine: hostKeys.privateKey, theirPublicB64: deviceKeys.publicB64, deviceNonce: dn, hostNonce: hn, pairingSecret: hostSecret, isHost: true))
    }
    do {
        var (device, host) = try pairOf(secret: nil, hostSecret: nil)
        let frames = try device.seal(["id": 1, "path": "/api/state"])
        check(frames.count == 1 && !frames[0].contains("api"), "content is not visible in the frame")
        check((try host.open(frames[0]))?["path"] as? String == "/api/state", "round trip")
        check((try? host.open(frames[0])) == nil, "a replayed frame is rejected")
        let big = String(repeating: "字", count: 400_000)
        let parts = try host.seal(["text": big])
        check(parts.count > 1, "large messages are split")
        var whole: [String: Any]?
        for part in parts { whole = try device.open(part) }
        check(whole?["text"] as? String == big, "split message is reassembled")
        (device, host) = try pairOf(secret: nil, hostSecret: nil)
        let two = try device.seal(["n": 1]) + (try device.seal(["n": 2]))
        check((try? host.open(two[1])) == nil, "out-of-order frames are rejected")
        (device, host) = try pairOf(secret: "right", hostSecret: "wrong")
        check((try? host.open(try device.seal(["id": 1])[0])) == nil, "a wrong pairing secret cannot be read")
        let stranger = RemoteKeys()
        let fake = try RemoteSession(mine: stranger.privateKey, theirPublicB64: hostKeys.publicB64, deviceNonce: dn, hostNonce: hn, pairingSecret: nil, isHost: false)
        (_, host) = try pairOf(secret: nil, hostSecret: nil)
        check((try? host.open(try fake.seal(["id": 1])[0])) == nil, "another key cannot pose as a paired device")
        var tampered = Array(try device.seal(["id": 9])[0]); tampered[tampered.count - 6] = tampered[tampered.count - 6] == "A" ? "B" : "A"
        check((try? host.open(String(tampered))) == nil, "a modified frame is rejected")
        let payload = PairingPayload(relay: "wss://relay.example", room: "ab", hostKey: hostKeys.publicB64, secret: "s3")
        check(PairingPayload(url: payload.url)?.secret == "s3", "pairing link round trip")
        check(RemoteKeys.deviceId(publicB64: deviceKeys.publicB64).count == 32, "device id")
    } catch { fail("selftest failed: \(error)") }
    print("selftest ok")

default:
    fail("unknown command: " + command)
}
