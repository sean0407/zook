// Zook remote access: end-to-end encryption and message framing shared by the Mac side and devices.
// The relay only ever sees the `d` strings produced here.
//
// Handshake (plaintext, carries no secrets):   d = "H" + base64(JSON hello)
//   device -> host: {v, device, nonce, pub?, pairing?}     host -> device: {v, nonce}
// Session key = HKDF-SHA256(X25519(device key, host key), salt = deviceNonce + hostNonce, info)
//   info = "zook-session-v1"                      for a paired device
//   info = "zook-pair-v1|" + one-time secret       while pairing (only someone who saw the QR code can derive it)
// Messages (sealed):                            d = "S" + base64(ChaChaPoly(JSON part))
//   Each direction counts its messages; the counter is the nonce, so replayed or reordered frames fail to open.
//   Large messages are split into parts: {m: message id, i: index, n: count, p: base64 piece}.
import CryptoKit
import Foundation

enum RemoteError: Error { case badFrame, badKey, cannotOpen }

struct RemoteKeys {
    let privateKey: Curve25519.KeyAgreement.PrivateKey
    var publicB64: String { privateKey.publicKey.rawRepresentation.base64EncodedString() }
    var id: String { RemoteKeys.deviceId(publicB64: publicB64) }
    init() { privateKey = Curve25519.KeyAgreement.PrivateKey() }
    init(privateB64: String) throws {
        guard let raw = Data(base64Encoded: privateB64) else { throw RemoteError.badKey }
        privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: raw)
    }
    var privateB64: String { privateKey.rawRepresentation.base64EncodedString() }
    static func deviceId(publicB64: String) -> String {
        let digest = SHA256.hash(data: Data(base64Encoded: publicB64) ?? Data())
        return digest.prefix(16).map { String(format: "%02x", $0) }.joined()
    }
}

func randomBytes(_ count: Int) -> Data {
    var bytes = [UInt8](repeating: 0, count: count)
    _ = SecRandomCopyBytes(kSecRandomDefault, count, &bytes)
    return Data(bytes)
}

func randomHex(_ count: Int) -> String { randomBytes(count).map { String(format: "%02x", $0) }.joined() }

/// One encrypted conversation between a device and the Mac.
final class RemoteSession {
    private let key: SymmetricKey
    private let isHost: Bool
    private var sendCount: UInt64 = 0
    private var receiveCount: UInt64 = 0
    private var nextMessage: UInt64 = 0
    private var partial: [UInt64: [Int: Data]] = [:]
    static let pieceSize = 256 * 1024

    init(mine: Curve25519.KeyAgreement.PrivateKey, theirPublicB64: String, deviceNonce: Data, hostNonce: Data, pairingSecret: String?, isHost: Bool) throws {
        guard let raw = Data(base64Encoded: theirPublicB64), deviceNonce.count == 16, hostNonce.count == 16 else { throw RemoteError.badKey }
        let shared = try mine.sharedSecretFromKeyAgreement(with: Curve25519.KeyAgreement.PublicKey(rawRepresentation: raw))
        let info = pairingSecret.map { "zook-pair-v1|" + $0 } ?? "zook-session-v1"
        key = shared.hkdfDerivedSymmetricKey(using: SHA256.self, salt: deviceNonce + hostNonce, sharedInfo: Data(info.utf8), outputByteCount: 32)
        self.isHost = isHost
    }

    private func nonce(fromHost: Bool, counter: UInt64) -> ChaChaPoly.Nonce {
        var bytes = Data([fromHost ? 1 : 2, 0, 0, 0])
        withUnsafeBytes(of: counter.bigEndian) { bytes.append(contentsOf: $0) }
        return try! ChaChaPoly.Nonce(data: bytes)
    }

    /// Frames (`d` strings) that carry one JSON message.
    func seal(_ message: [String: Any]) throws -> [String] {
        let body = try JSONSerialization.data(withJSONObject: message)
        let id = nextMessage; nextMessage += 1
        let pieces = stride(from: 0, to: max(body.count, 1), by: RemoteSession.pieceSize).map { body.subdata(in: $0..<min($0 + RemoteSession.pieceSize, body.count)) }
        return try pieces.enumerated().map { index, piece in
            let part = try JSONSerialization.data(withJSONObject: ["m": id, "i": index, "n": pieces.count, "p": piece.base64EncodedString()])
            let box = try ChaChaPoly.seal(part, using: key, nonce: nonce(fromHost: isHost, counter: sendCount))
            sendCount += 1
            return "S" + box.combined.base64EncodedString()
        }
    }

    /// The JSON message once all of its parts have arrived; nil while parts are still missing.
    func open(_ frame: String) throws -> [String: Any]? {
        guard frame.hasPrefix("S"), let data = Data(base64Encoded: String(frame.dropFirst())) else { throw RemoteError.badFrame }
        let expected = nonce(fromHost: !isHost, counter: receiveCount)
        let box = try ChaChaPoly.SealedBox(combined: data)
        guard Data(box.nonce) == Data(expected) else { throw RemoteError.cannotOpen }
        let plain = try ChaChaPoly.open(box, using: key)
        receiveCount += 1
        guard let part = try JSONSerialization.jsonObject(with: plain) as? [String: Any], let id = (part["m"] as? NSNumber)?.uint64Value,
              let index = part["i"] as? Int, let count = part["n"] as? Int, let piece = Data(base64Encoded: part["p"] as? String ?? ""),
              count >= 1, count <= 400, index >= 0, index < count else { throw RemoteError.badFrame }
        partial[id, default: [:]][index] = piece
        guard partial[id]!.count == count else { return nil }
        let whole = (0..<count).reduce(into: Data()) { $0.append(partial[id]![$1]!) }
        partial[id] = nil
        return try JSONSerialization.jsonObject(with: whole) as? [String: Any]
    }
}

func helloFrame(_ fields: [String: Any]) -> String {
    "H" + ((try? JSONSerialization.data(withJSONObject: fields)) ?? Data()).base64EncodedString()
}

func parseHello(_ frame: String) -> [String: Any]? {
    guard frame.hasPrefix("H"), let data = Data(base64Encoded: String(frame.dropFirst())) else { return nil }
    return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
}

/// What the QR code carries: where the relay is, which room, the Mac's public key, and the one-time pairing secret.
struct PairingPayload {
    let relay: String, room: String, hostKey: String, secret: String
    var url: String {
        let json = try! JSONSerialization.data(withJSONObject: ["v": 1, "relay": relay, "room": room, "hostKey": hostKey, "secret": secret])
        let b64 = json.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        return "zook://pair?d=" + b64
    }
    init(relay: String, room: String, hostKey: String, secret: String) { self.relay = relay; self.room = room; self.hostKey = hostKey; self.secret = secret }
    init?(url: String) {
        guard let range = url.range(of: "zook://pair?d=") else { return nil }
        var b64 = String(url[range.upperBound...]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64 += "=" }
        guard let data = Data(base64Encoded: b64), let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let relay = obj["relay"] as? String, let room = obj["room"] as? String, let hostKey = obj["hostKey"] as? String, let secret = obj["secret"] as? String else { return nil }
        self.relay = relay; self.room = room; self.hostKey = hostKey; self.secret = secret
    }
}
