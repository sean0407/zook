import SwiftUI

struct RootView: View {
    @EnvironmentObject var model: AppModel
    @AppStorage("appearance") private var appearance = "system"

    var body: some View {
        Group {
            if model.locked { LockView() }
            else if model.credentials == nil { PairView() }
            else { HomeView() }
        }
        .tint(Color(red: 0.15, green: 0.52, blue: 0.96))
        .preferredColorScheme(appearance == "light" ? .light : appearance == "dark" ? .dark : nil)
    }
}

struct LockView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "lock.fill").font(.system(size: 40)).foregroundStyle(.secondary)
            Text("Zook 已上鎖").font(.title3.weight(.semibold))
            Button("解鎖") { model.unlock() }.buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { model.unlock() }
    }
}

/// Shown over the content while the Mac cannot be reached.
struct OfflineBanner: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        if model.state != .online {
            VStack(alignment: .leading, spacing: 4) {
                Label(model.state == .connecting ? "正在連線到你的 Mac…" : "連不到你的 Mac", systemImage: model.state == .connecting ? "arrow.triangle.2.circlepath" : "wifi.slash")
                    .font(.subheadline.weight(.semibold))
                if model.state == .macOffline {
                    Text("可能是 Mac 關機、睡眠、沒有網路，或 Zook 沒有開著。恢復後會自動連上。").font(.caption).foregroundStyle(.secondary)
                    if let last = model.lastOnline { Text("最後連線：\(last.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary) }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(Color.yellow.opacity(0.18), in: RoundedRectangle(cornerRadius: 12))
            .padding(.horizontal)
        }
    }
}

extension Color {
    init?(hex: String?) {
        guard let hex = hex?.trimmingCharacters(in: CharacterSet(charactersIn: "#")), hex.count == 6, let value = UInt32(hex, radix: 16) else { return nil }
        self.init(red: Double((value >> 16) & 255) / 255, green: Double((value >> 8) & 255) / 255, blue: Double(value & 255) / 255)
    }
}

func shortTime(_ iso: String?) -> String {
    guard let iso = iso else { return "" }
    let parser = ISO8601DateFormatter(); parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    guard let date = parser.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else { return "" }
    return Calendar.current.isDateInToday(date) ? date.formatted(date: .omitted, time: .shortened) : date.formatted(.dateTime.month().day())
}
