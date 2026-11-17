// The phone's encrypted connection to the Mac, through the relay. Uses RemoteCore.swift (shared with the Mac side).
import CryptoKit
import Foundation

struct Credentials: Codable, Equatable {
    var privateKey: String, relay: String, room: String, hostKey: String, device: String
}

enum LinkState: Equatable { case connecting, online, macOffline, revoked }

enum LinkError: LocalizedError {
    case macOffline, revoked, timeout, badPairingCode, pairingFailed(String), server(Int, String)
    var errorDescription: String? {
        switch self {
        case .macOffline: return "連不到你的 Mac。"
        case .revoked: return "這台裝置的配對已被撤銷，請在 Mac 上重新配對。"
        case .timeout: return "等待逾時，請再試一次。"
        case .badPairingCode: return "這不是 Zook 的配對 QR code。"
        case .pairingFailed(let why): return why
        case .server(_, let message): return message
        }
    }
}

/// One WebSocket to the relay. All callbacks run on `queue`.
private final class RelaySocket: NSObject, URLSessionWebSocketDelegate {
    private var task: URLSessionWebSocketTask!
    private var session: URLSession!
    private var closed = false
    private let queue: DispatchQueue
    var onText: ((String) -> Void)?
    var onClose: ((Int) -> Void)?   // WebSocket close code, 0 when the connection just failed

    init(url: URL, queue: DispatchQueue) {
        self.queue = queue
        super.init()
        let operations = OperationQueue(); operations.underlyingQueue = queue
        session = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: operations)
        var request = URLRequest(url: url); request.timeoutInterval = 20
        task = session.webSocketTask(with: request)
        task.maximumMessageSize = 4 * 1024 * 1024
    }

    func start() { task.resume(); receive() }

    private func receive() {
        task.receive { [weak self] result in
            self?.queue.async {
                guard let self = self, !self.closed else { return }
                switch result {
                case .failure: self.finish(self.task.closeCode.rawValue)
                case .success(let message):
                    if case .string(let text) = message { self.onText?(text) }
                    self.receive()
                }
            }
        }
    }

    func send(_ object: [String: Any]) {
        guard !closed, let data = try? JSONSerialization.data(withJSONObject: object), let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { [weak self] error in if error != nil { self?.queue.async { self?.finish(0) } } }
    }

    func close() { closed = true; task.cancel(with: .normalClosure, reason: nil); session.invalidateAndCancel() }

    private func finish(_ code: Int) {
        if closed { return }
        closed = true; session.invalidateAndCancel(); onClose?(code)
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) { finish(closeCode.rawValue) }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) { finish(self.task.closeCode.rawValue) }
}

private func relayEndpoint(_ base: String, room: String) -> URL? {
    guard let url = URL(string: base.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/v1/room/" + room + "/device"), ["ws", "wss"].contains(url.scheme ?? "") else { return nil }
    return url
}

/// A lasting connection for a paired device: reconnects by itself and answers requests in order of arrival.
final class ZookLink {
    private let credentials: Credentials
    private let keys: RemoteKeys
    private let queue = DispatchQueue(label: "zook.link")
    private var socket: RelaySocket?
    private var session: RemoteSession?
    private var nonce = Data()
    private var nextId = 1
    private var waiting: [Int: (Result<(Int, Data), Error>) -> Void] = [:]
    private var stopped = false
    private var retry = 1.0
    private var refusedAtHello = 0
    private(set) var state: LinkState = .connecting
    var onState: ((LinkState) -> Void)?

    init(credentials: Credentials) throws {
        self.credentials = credentials
        keys = try RemoteKeys(privateB64: credentials.privateKey)
    }

    func start() { queue.async { self.stopped = false; self.connect() } }
    func stop() { queue.async { self.stopped = true; self.socket?.close(); self.socket = nil; self.failAll(LinkError.macOffline) } }

    private func set(_ new: LinkState) {
        if state == new { return }
        state = new; onState?(new)
    }

    private func failAll(_ error: Error) {
        let callbacks = waiting.values; waiting.removeAll()
        for done in callbacks { done(.failure(error)) }
    }

    private func connect() {
        guard !stopped, socket == nil, let url = relayEndpoint(credentials.relay, room: credentials.room) else { return }
        session = nil; nonce = randomBytes(16)
        let socket = RelaySocket(url: url, queue: queue); self.socket = socket
        socket.onText = { [weak self] text in self?.handle(text) }
        socket.onClose = { [weak self] code in self?.closed(code) }
        socket.start()
    }

    private func closed(_ code: Int) {
        let hadSession = session != nil
        socket = nil; session = nil
        if stopped { return }
        // The Mac closes a device it does not know (never paired, or revoked) right after its greeting.
        if code == 4001 && !hadSession { refusedAtHello += 1 } else if hadSession { refusedAtHello = 0 }
        if refusedAtHello >= 2 { set(.revoked); failAll(LinkError.revoked); return }
        failAll(LinkError.macOffline)
        if state == .online { set(.connecting) }
        queue.asyncAfter(deadline: .now() + retry) { [weak self] in self?.connect() }
        retry = min(retry * 1.6, 15)
    }

    private func handle(_ text: String) {
        guard let message = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any] else { return }
        if message["event"] as? String == "host" {
            if message["online"] as? Bool == true {
                if session == nil { socket?.send(["d": helloFrame(["v": 1, "device": keys.id, "nonce": nonce.base64EncodedString()])]) }
            } else { session = nil; failAll(LinkError.macOffline); set(.macOffline) }
            return
        }
        guard let frame = message["d"] as? String else { return }
        if frame.hasPrefix("H") {
            guard session == nil, let hello = parseHello(frame), let hostNonce = Data(base64Encoded: hello["nonce"] as? String ?? ""),
                  let made = try? RemoteSession(mine: keys.privateKey, theirPublicB64: credentials.hostKey, deviceNonce: nonce, hostNonce: hostNonce, pairingSecret: nil, isHost: false)
            else { socket?.close(); closed(0); return }
            session = made; retry = 1.0; refusedAtHello = 0; set(.online)
            return
        }
        guard let session = session else { return }
        do {
            guard let reply = try session.open(frame), let id = reply["id"] as? Int, let done = waiting.removeValue(forKey: id) else { return }
            done(.success((reply["status"] as? Int ?? 0, Data((reply["text"] as? String ?? "").utf8))))
        } catch { socket?.close(); closed(0) }
    }

    /// Sends one request to Zook on the Mac. Fails at once when the Mac cannot be reached.
    func request(_ method: String, _ path: String, body: Data? = nil, timeout: Double = 60) async throws -> (Int, Data) {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                if self.state == .revoked { return continuation.resume(throwing: LinkError.revoked) }
                guard let session = self.session, let socket = self.socket else { return continuation.resume(throwing: LinkError.macOffline) }
                let id = self.nextId; self.nextId += 1
                var message: [String: Any] = ["id": id, "method": method, "path": path]
                if let body = body { message["body"] = String(data: body, encoding: .utf8) ?? "" }
                guard let frames = try? session.seal(message) else { return continuation.resume(throwing: LinkError.macOffline) }
                self.waiting[id] = { continuation.resume(with: $0) }
                for frame in frames { socket.send(["d": frame]) }
                self.queue.asyncAfter(deadline: .now() + timeout) { self.waiting.removeValue(forKey: id)?(.failure(LinkError.timeout)) }
            }
        }
    }

    /// Pairs this device with the Mac that showed the QR code. Returns what the device must keep to connect later.
    static func pair(code: String, deviceName: String, timeout: Double = 25) async throws -> Credentials {
        guard let payload = PairingPayload(url: code), let url = relayEndpoint(payload.relay, room: payload.room) else { throw LinkError.badPairingCode }
        let keys = RemoteKeys(), nonce = randomBytes(16), queue = DispatchQueue(label: "zook.pair")
        return try await withCheckedThrowingContinuation { continuation in
            queue.async {
                var session: RemoteSession?, finished = false, sentHello = false
                let socket = RelaySocket(url: url, queue: queue)
                func finish(_ result: Result<Credentials, Error>) {
                    if finished { return }
                    finished = true; socket.close(); continuation.resume(with: result)
                }
                socket.onClose = { _ in finish(.failure(LinkError.pairingFailed("配對沒有成功。QR code 可能已過期或已經用過，請在 Mac 上重新產生。"))) }
                socket.onText = { text in
                    guard let message = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any] else { return }
                    if message["event"] as? String == "host" {
                        if message["online"] as? Bool == true, !sentHello {
                            sentHello = true
                            socket.send(["d": helloFrame(["v": 1, "device": keys.id, "nonce": nonce.base64EncodedString(), "pairing": true, "pub": keys.publicB64])])
                        } else if message["online"] as? Bool == false { finish(.failure(LinkError.macOffline)) }
                        return
                    }
                    guard let frame = message["d"] as? String else { return }
                    if frame.hasPrefix("H"), session == nil {
                        guard let hello = parseHello(frame), let hostNonce = Data(base64Encoded: hello["nonce"] as? String ?? ""),
                              let made = try? RemoteSession(mine: keys.privateKey, theirPublicB64: payload.hostKey, deviceNonce: nonce, hostNonce: hostNonce, pairingSecret: payload.secret, isHost: false),
                              let frames = try? made.seal(["id": 1, "name": deviceName]) else { return finish(.failure(LinkError.pairingFailed("無法建立加密連線。"))) }
                        session = made
                        for frame in frames { socket.send(["d": frame]) }
                        return
                    }
                    guard let reply = try? session?.open(frame) else { return }
                    if reply["status"] as? Int == 200 {
                        finish(.success(Credentials(privateKey: keys.privateB64, relay: payload.relay, room: payload.room, hostKey: payload.hostKey, device: keys.id)))
                    } else { finish(.failure(LinkError.pairingFailed("配對沒有成功，請在 Mac 上重新產生 QR code。"))) }
                }
                socket.start()
                queue.asyncAfter(deadline: .now() + timeout) { finish(.failure(LinkError.macOffline)) }
            }
        }
    }
}
