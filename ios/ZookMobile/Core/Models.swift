// What the phone shows. These mirror the backend's /api/mobile/* views.
import Foundation

struct BotSummary: Codable, Identifiable, Equatable {
    var id: String, name: String, color: String?, shape: String?, section: String, pinned: Bool, model: String, preview: String, lastAt: String?, running: Bool, pending: Int
}

struct GroupSummary: Codable, Identifiable, Equatable {
    var id: String, name: String, botIds: [String], running: Bool, preview: String, lastAt: String?, pending: Int
}

struct Home: Codable, Equatable {
    var bots: [BotSummary], groups: [GroupSummary], sections: [String], pending: Int
}

struct ChatMessage: Codable, Identifiable, Equatable {
    var id: String, role: String, content: String, status: String, createdAt: String?, botId: String?, botName: String?, note: String?, author: String?, attachments: Int?
}

struct Approval: Codable, Identifiable, Equatable {
    var id: String, jobId: String, botId: String, botName: String, category: String, text: String
}

struct ActivityItem: Codable, Identifiable, Equatable {
    var id: String, text: String, state: String, createdAt: String?, `where`: String?
}

struct BotHeader: Codable, Equatable { var id: String, name: String, color: String?, shape: String?, model: String? }

struct ChatSummary: Codable, Identifiable, Equatable { var id: String, title: String, updatedAt: String?, open: Bool }

struct BotConversation: Codable, Equatable {
    var bot: BotHeader, messages: [ChatMessage], running: Bool, activeJobId: String?, approvals: [Approval], activity: [ActivityItem], chats: [ChatSummary]?
}

struct ScheduleItem: Codable, Identifiable, Equatable { var id: String, content: String, when: String, target: String, on: Bool, group: Bool }
struct ScheduleList: Codable, Equatable { var schedules: [ScheduleItem] }
struct Notice: Codable, Equatable { var seq: Int, title: String, body: String, targetId: String? }
struct NoticeList: Codable, Equatable { var seq: Int, items: [Notice] }
private struct UploadedPhoto: Codable { var id: String }

struct GroupHeader: Codable, Equatable { var id: String, name: String }

struct GroupConversation: Codable, Equatable {
    var group: GroupHeader, members: [BotHeader], messages: [ChatMessage], running: Bool, speaking: [String], approvals: [Approval]
}

struct QuotaWindow: Codable, Equatable { var label: String, usedPercent: Double }
struct ProviderQuota: Codable, Equatable { var windows: [QuotaWindow]? }
struct ProviderUsage: Codable, Identifiable, Equatable {
    var id: String, name: String, status: String?, email: String?, quota: ProviderQuota?
}
struct QuotaView: Codable, Equatable { var providers: [ProviderUsage] }

struct ProviderOption: Codable, Identifiable, Equatable { var id: String, name: String, installed: Bool }

/// What the Mac is set to. Shown on the phone, changed only on the Mac.
struct SwitchItem: Codable, Identifiable, Equatable { var id: String, name: String, on: Bool }
struct PairedDevice: Codable, Identifiable, Equatable { var id: String, name: String, lastSeenAt: String? }
struct MacSettings: Codable, Equatable {
    var mac: String, permissionMode: String, webSearch: Bool, model: String
    var connectors: [SwitchItem], skills: [SwitchItem], devices: [PairedDevice], thisDevice: String?
}
struct ProviderList: Codable, Equatable { var providers: [ProviderOption] }

/// Typed calls on top of a link.
struct ZookAPI {
    let link: ZookLink

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let (status, data) = try await link.request("GET", path)
        guard status == 200 else { throw LinkError.server(status, ZookAPI.message(data)) }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post(_ path: String, _ body: [String: Any]) async throws {
        let (status, data) = try await link.request("POST", path, body: try JSONSerialization.data(withJSONObject: body))
        guard (200..<300).contains(status) else { throw LinkError.server(status, ZookAPI.message(data)) }
    }

    static func message(_ data: Data) -> String {
        (((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])?["error"] as? String) ?? "沒有成功，請再試一次。"
    }

    func home() async throws -> Home { try await get("/api/mobile/home") }
    func bot(_ id: String) async throws -> BotConversation { try await get("/api/mobile/bots/" + id) }
    func group(_ id: String) async throws -> GroupConversation { try await get("/api/mobile/groups/" + id) }
    func quota() async throws -> QuotaView { try await get("/api/quota") }
    func send(toBot id: String, _ text: String, photos: [String] = []) async throws { try await post("/api/chat", ["botId": id, "content": text, "attachments": photos]) }
    /// Sends one photo (already made small) to the Mac and returns its id, to attach to the next message.
    func upload(photo: Data) async throws -> String {
        let (status, data) = try await link.request("POST", "/api/mobile/photos", body: try JSONSerialization.data(withJSONObject: ["data": photo.base64EncodedString()]), timeout: 90)
        guard (200..<300).contains(status) else { throw LinkError.server(status, ZookAPI.message(data)) }
        return try JSONDecoder().decode(UploadedPhoto.self, from: data).id
    }
    func schedules() async throws -> [ScheduleItem] { let list: ScheduleList = try await get("/api/mobile/schedules"); return list.schedules }
    /// `action` is pause, resume or delete. Making and changing schedules stays on the Mac.
    func schedule(_ id: String, _ action: String) async throws { try await post("/api/mobile/schedules/" + id, ["action": action]) }
    func openChat(bot id: String, chat: String) async throws { try await post("/api/mobile/bots/" + id + "/chats", ["chatId": chat]) }
    func newChat(bot id: String) async throws { try await post("/api/mobile/bots/" + id + "/chats", ["new": true]) }
    func notices(after seq: Int) async throws -> NoticeList { try await get("/api/notifications?after=\(seq)") }
    func send(toGroup id: String, _ text: String) async throws { try await post("/api/groups/" + id + "/messages", ["content": text]) }
    func decide(_ approval: String, approve: Bool) async throws { try await post("/api/approvals/" + approval, ["decision": approve ? "approve" : "deny"]) }
    func providers() async throws -> [ProviderOption] { let list: ProviderList = try await get("/api/providers"); return list.providers }
    /// `provider` empty means the Mac's default model.
    func createBot(name: String, instructions: String, provider: String, color: String, shape: String) async throws {
        try await post("/api/mobile/bots", ["name": name, "instructions": instructions, "provider": provider, "color": color, "shape": shape])
    }
    func settings() async throws -> MacSettings { try await get("/api/mobile/settings") }
    func stop(job id: String) async throws { try await post("/api/jobs/" + id + "/cancel", [:]) }
    func stop(group id: String) async throws { try await post("/api/groups/" + id + "/stop", [:]) }
}
