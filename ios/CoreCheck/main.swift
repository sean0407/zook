// Runs the phone's connection code on the Mac (no simulator needed): pair with a QR link, then use the typed calls.
//   corecheck <pairing link> [message to the first Bot]
import Foundation

let args = CommandLine.arguments
guard args.count >= 2 else { print("usage: corecheck <zook://pair?...> [message]"); exit(2) }

func step(_ text: String) { print(text); fflush(stdout) }

Task {
    do {
        let credentials = try await ZookLink.pair(code: args[1], deviceName: "核心測試")
        step("paired as \(credentials.device.prefix(8))…")
        do { _ = try await ZookLink.pair(code: args[1], deviceName: "again"); step("ERROR: the same code paired twice"); exit(1) } catch { step("same code again: refused (\(error.localizedDescription))") }
        let link = try ZookLink(credentials: credentials)
        link.onState = { step("state: \($0)") }
        link.start()
        var tries = 0
        while link.state != .online, tries < 50 { try await Task.sleep(nanoseconds: 200_000_000); tries += 1 }
        let api = ZookAPI(link: link)
        let home = try await api.home()
        step("home: \(home.bots.count) bots, \(home.groups.count) groups, pending \(home.pending)")
        if args.count >= 3, let first = home.bots.first {
            try await api.send(toBot: first.id, args[2])
            var view = try await api.bot(first.id)
            var waited = 0
            while view.running, waited < 90 {
                if let approval = view.approvals.first { step("approval asked: \(approval.text)"); try await api.decide(approval.id, approve: true); step("approved from the device") }
                try await Task.sleep(nanoseconds: 1_500_000_000); waited += 1
                view = try await api.bot(first.id)
            }
            step("reply: \(view.messages.last?.content.prefix(70) ?? "")")
            step("activity: \(view.activity.prefix(3).map { $0.text + "(" + $0.state + ")" })")
        }
        do { _ = try await link.request("PATCH", "/api/settings", body: Data("{\"permissionMode\":\"bypass\"}".utf8)).0 == 403 ? step("settings change: refused (403)") : step("ERROR: settings change was allowed") }
        step("waiting to be revoked…")
        var seconds = 0
        while link.state != .revoked, seconds < 40 {
            try await Task.sleep(nanoseconds: 1_000_000_000); seconds += 1
            _ = try? await api.home()
        }
        step(link.state == .revoked ? "revoked: the app would show the pairing screen" : "ERROR: not revoked after 40s (state \(link.state))")
        exit(link.state == .revoked ? 0 : 1)
    } catch { step("failed: \(error.localizedDescription)"); exit(1) }
}
dispatchMain()
