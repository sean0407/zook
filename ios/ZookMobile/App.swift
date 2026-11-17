import LocalAuthentication
import Security
import SwiftUI

@main
struct ZookMobileApp: App {
    @StateObject private var model = AppModel()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .onOpenURL { url in if url.scheme == "zook" { model.pendingCode = url.absoluteString } }
                .onChange(of: phase) { _, new in model.scene(active: new == .active, background: new == .background) }
        }
    }
}

/// The device's pairing, kept in the iPhone Keychain (this device only, never synced).
enum CredentialStore {
    private static let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "app.zook.mobile", kSecAttrAccount as String: "pairing"]

    static func load() -> Credentials? {
        var q = query; q[kSecReturnData as String] = true
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return try? JSONDecoder().decode(Credentials.self, from: data)
    }

    static func save(_ credentials: Credentials) {
        guard let data = try? JSONEncoder().encode(credentials) else { return }
        SecItemDelete(query as CFDictionary)
        var q = query; q[kSecValueData as String] = data; q[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }

    static func clear() { SecItemDelete(query as CFDictionary) }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var credentials: Credentials?
    @Published var state: LinkState = .connecting
    @Published var home: Home?
    @Published var locked = true
    @Published var pendingCode: String?
    @Published var lastOnline: Date?
    /// The time of the last message the user has seen in each conversation; anything newer shows an unread dot.
    @Published var seen: [String: String] = (UserDefaults.standard.dictionary(forKey: "seen") as? [String: String]) ?? [:]
    private var link: ZookLink?
    private var leftAt: Date?
    private var homeTask: Task<Void, Never>?

    var api: ZookAPI? { link.map(ZookAPI.init) }

    init() {
        credentials = CredentialStore.load()
        lastOnline = UserDefaults.standard.object(forKey: "lastOnline") as? Date
        if ProcessInfo.processInfo.environment["ZOOK_UI_TEST_UNLOCKED"] == "1" { locked = false }   // simulator checks only
        if let code = ProcessInfo.processInfo.environment["ZOOK_UI_TEST_PAIR"] { pendingCode = code }
        if credentials != nil { connect() }
    }

    func connect() {
        link?.stop(); link = nil; home = nil
        guard let credentials = credentials, let link = try? ZookLink(credentials: credentials) else { return }
        link.onState = { [weak self] new in Task { @MainActor in self?.apply(new) } }
        self.link = link; state = .connecting
        link.start()
        homeTask?.cancel()
        homeTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refreshHome()
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }

    private func apply(_ new: LinkState) {
        state = new
        if new == .online { lastOnline = Date(); UserDefaults.standard.set(lastOnline, forKey: "lastOnline"); Task { await refreshHome() } }
        if new == .revoked { unpair() }
    }

    func refreshHome() async {
        guard !locked, state == .online, let api = api else { return }
        guard let fresh = try? await api.home() else { return }
        if UserDefaults.standard.object(forKey: "seen") == nil {   // first run: nothing counts as unread yet
            for bot in fresh.bots { seen[bot.id] = bot.lastAt ?? "" }
            for group in fresh.groups { seen[group.id] = group.lastAt ?? "" }
            UserDefaults.standard.set(seen, forKey: "seen")
        }
        if fresh != home { home = fresh }
    }

    func unread(_ id: String, _ lastAt: String?) -> Bool {
        guard let lastAt = lastAt, !lastAt.isEmpty else { return false }
        return seen[id] != lastAt
    }

    /// Called while a conversation is open: what is in it now has been seen.
    func markSeen(_ id: String) {
        let lastAt = home?.bots.first { $0.id == id }?.lastAt ?? home?.groups.first { $0.id == id }?.lastAt
        guard let lastAt = lastAt, seen[id] != lastAt else { return }
        seen[id] = lastAt; UserDefaults.standard.set(seen, forKey: "seen")
    }

    func pair(code: String) async throws {
        let name = UIDevice.current.name
        let made = try await ZookLink.pair(code: code, deviceName: name)
        CredentialStore.save(made); credentials = made
        connect()
    }

    func unpair() {
        homeTask?.cancel(); link?.stop(); link = nil
        CredentialStore.clear(); credentials = nil; home = nil
    }

    func scene(active: Bool, background: Bool) {
        if background { leftAt = Date() }
        if active, let left = leftAt, Date().timeIntervalSince(left) > 60 { locked = true }
        if active { leftAt = nil }
    }

    /// Face ID (or the device passcode) before anything is shown.
    func unlock() {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else { locked = false; return }   // no passcode set on this device
        context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "解鎖 Zook") { ok, _ in
            Task { @MainActor in if ok { self.locked = false; await self.refreshHome() } }
        }
    }
}
