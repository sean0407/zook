import SwiftUI

enum Route: Hashable { case bot(String, String), group(String, String) }

/// The first screen: pinned Bots on top, then groups and Bots by section, with search at the bottom.
struct HomeView: View {
    @EnvironmentObject var model: AppModel
    @AppStorage("collapsedSections") private var collapsedList = ""
    @State private var showSettings = false
    @State private var showNewBot = false
    @State private var query = ""
    @FocusState private var searching: Bool

    private var collapsed: Set<String> { Set(collapsedList.split(separator: "\n").map(String.init)) }

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if model.state != .online { OfflineBanner().padding(.vertical, 8) }
                    if let home = model.home { content(home) }
                    else if model.state == .online { HStack { Spacer(); ProgressView("正在讀取…"); Spacer() }.padding(.top, 80) }
                }
                .padding(.bottom, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .refreshable { await model.refreshHome() }
            .navigationTitle("Zook").navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: Route.self) { route in
                switch route {
                case .bot(let id, let name): ChatView(kind: .bot, id: id, title: name)
                case .group(let id, let name): ChatView(kind: .group, id: id, title: name)
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button { showSettings = true } label: { Image(systemName: "gearshape") }.accessibilityLabel("設定") }
                ToolbarItem(placement: .topBarTrailing) { Button { showNewBot = true } label: { Image(systemName: "plus") }.accessibilityLabel("新增 Bot").disabled(model.state != .online) }
            }
            .safeAreaInset(edge: .bottom) { searchBar }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .sheet(isPresented: $showNewBot) { NewBotView() }
        }
    }

    @ViewBuilder private func content(_ home: Home) -> some View {
        let word = query.trimmingCharacters(in: .whitespaces).lowercased()
        let bots = home.bots.filter { word.isEmpty || $0.name.lowercased().contains(word) || $0.preview.lowercased().contains(word) }
        let groups = home.groups.filter { word.isEmpty || $0.name.lowercased().contains(word) || $0.preview.lowercased().contains(word) }
        let pinned = bots.filter { $0.pinned }

        if !pinned.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 22) {
                    ForEach(pinned) { bot in
                        NavigationLink(value: Route.bot(bot.id, bot.name)) {
                            VStack(spacing: 10) {
                                BotAvatar(color: bot.color, shape: bot.shape, size: 92)
                                HStack(spacing: 6) {
                                    Text(bot.name).font(.subheadline).foregroundStyle(.primary).lineLimit(1)
                                    if bot.running { ProgressView().controlSize(.mini) } else if model.unread(bot.id, bot.lastAt) { UnreadDot() }
                                }
                            }.frame(width: 108)
                        }.buttonStyle(.plain)
                    }
                }.padding(.horizontal, 20).padding(.vertical, 18)
            }
        }
        if !groups.isEmpty {
            section("群組", count: groups.count) {
                ForEach(groups) { group in
                    NavigationLink(value: Route.group(group.id, group.name)) {
                        ConversationRow(name: group.name, preview: group.preview.isEmpty ? "開始群組討論" : group.preview, time: group.lastAt, running: group.running,
                                        pending: group.pending, unread: model.unread(group.id, group.lastAt)) {
                            GroupAvatar(members: group.botIds.compactMap { id in home.bots.first { $0.id == id } }, extra: max(0, group.botIds.count - 3), size: 52)
                        }
                    }.buttonStyle(.plain)
                }
            }
        }
        ForEach(sectionNames(home), id: \.self) { name in
            let list = bots.filter { !$0.pinned && $0.section == name }
            if !list.isEmpty {
                section(name, count: list.count) {
                    ForEach(list) { bot in
                        NavigationLink(value: Route.bot(bot.id, bot.name)) {
                            ConversationRow(name: (bot.jobTitle ?? "").isEmpty ? bot.name : bot.name + " · " + (bot.jobTitle ?? ""), preview: bot.preview.isEmpty ? "開始新的對話" : bot.preview, time: bot.lastAt, running: bot.running,
                                            pending: bot.pending, unread: model.unread(bot.id, bot.lastAt)) { BotAvatar(color: bot.color, shape: bot.shape, size: 52) }
                        }.buttonStyle(.plain)
                    }
                }
            }
        }
        if bots.isEmpty && groups.isEmpty {
            Text(word.isEmpty ? "還沒有 Bot。按右上角的 ＋ 新增一個。" : "找不到符合「\(query)」的 Bot 或群組。")
                .font(.subheadline).foregroundStyle(.secondary).frame(maxWidth: .infinity).padding(.top, 60).padding(.horizontal, 32).multilineTextAlignment(.center)
        }
    }

    /// A section that folds: the heading shows a count while it is closed.
    @ViewBuilder private func section<Rows: View>(_ title: String, count: Int, @ViewBuilder rows: () -> Rows) -> some View {
        let closed = collapsed.contains(title) && query.isEmpty
        Button {
            var set = collapsed
            if set.contains(title) { set.remove(title) } else { set.insert(title) }
            withAnimation(.easeInOut(duration: 0.2)) { collapsedList = set.sorted().joined(separator: "\n") }
            Haptics.tap()
        } label: {
            HStack(spacing: 8) {
                Text(title).font(.subheadline).foregroundStyle(.secondary)
                if closed { Text("\(count)").font(.subheadline).foregroundStyle(.tertiary) }
                Image(systemName: closed ? "chevron.right" : "chevron.down").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
                Spacer()
            }
            .padding(.horizontal, 20).padding(.top, 22).padding(.bottom, 8).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title)，\(count) 個，\(closed ? "已收合" : "已展開")")
        if !closed { rows() }
    }

    private var searchBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("搜尋", text: $query).focused($searching).submitLabel(.search).autocorrectionDisabled()
            if !query.isEmpty { Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary) }.accessibilityLabel("清除搜尋") }
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .background(.regularMaterial, in: Capsule())
        .overlay(Capsule().stroke(Color(.separator).opacity(0.4)))
        .padding(.horizontal, 16).padding(.bottom, 8)
    }

    private func sectionNames(_ home: Home) -> [String] {
        var names = home.sections
        for bot in home.bots where !names.contains(bot.section) { names.append(bot.section) }
        return names
    }
}

private struct UnreadDot: View {
    var body: some View { Circle().fill(Color.accentColor).frame(width: 9, height: 9).accessibilityLabel("有新訊息") }
}

private struct ConversationRow<Picture: View>: View {
    let name: String, preview: String, time: String?, running: Bool, pending: Int, unread: Bool
    @ViewBuilder let picture: () -> Picture

    var body: some View {
        HStack(spacing: 14) {
            picture()
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(name).font(.body.weight(.semibold)).lineLimit(1)
                    if running { ProgressView().controlSize(.mini) }
                    Spacer()
                    Text(shortTime(time)).font(.caption).foregroundStyle(.secondary)
                }
                HStack(spacing: 8) {
                    Text(preview).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                    Spacer(minLength: 0)
                    if pending > 0 { Text("待核准").font(.caption2.weight(.semibold)).padding(.horizontal, 7).padding(.vertical, 3).background(Color.orange.opacity(0.2), in: Capsule()).foregroundStyle(.orange) }
                    else if unread { UnreadDot() }
                }
            }
        }
        .padding(.horizontal, 20).padding(.vertical, 10)
        .contentShape(Rectangle())
    }
}

// MARK: - New Bot

struct NewBotView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var instructions = ""
    @State private var provider = ""
    @State private var shape = Int.random(in: 0..<BotLook.shapeCount)
    @State private var color = BotLook.colors.randomElement() ?? "#2585f6"
    @State private var providers: [ProviderOption] = []
    @State private var saving = false
    @State private var problem: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 26) {
                    BotAvatar(color: color, shape: String(shape), size: 132).padding(.top, 12)
                    TextField("為你的 Bot 取個名字", text: $name)
                        .multilineTextAlignment(.center).font(.title3.weight(.semibold))
                        .padding(.vertical, 14).padding(.horizontal, 16)
                        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 5), spacing: 14) {
                        ForEach(0..<BotLook.shapeCount, id: \.self) { index in
                            Button { shape = index; Haptics.tap() } label: {
                                BotAvatar(color: color, shape: String(index), size: 40)
                                    .padding(7).overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.secondary, lineWidth: shape == index ? 2 : 0))
                            }.buttonStyle(.plain).accessibilityLabel("形狀 \(index + 1)").accessibilityAddTraits(shape == index ? .isSelected : [])
                        }
                    }
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 6), spacing: 16) {
                        ForEach(BotLook.colors, id: \.self) { hex in
                            Button { color = hex; Haptics.tap() } label: {
                                Circle().fill(Color(hex: hex) ?? .gray).frame(width: 30, height: 30)
                                    .overlay(Circle().stroke(Color(.separator), lineWidth: 1))
                                    .padding(5).overlay(Circle().stroke(Color.secondary, lineWidth: color == hex ? 2 : 0))
                            }.buttonStyle(.plain).accessibilityLabel("顏色 \(hex)").accessibilityAddTraits(color == hex ? .isSelected : [])
                        }
                    }
                    VStack(spacing: 0) {
                        HStack {
                            Text("模型")
                            Spacer()
                            Picker("模型", selection: $provider) {
                                Text("使用預設").tag("")
                                ForEach(providers.filter { $0.installed }) { option in Text(option.name.components(separatedBy: "（").first ?? option.name).tag(option.id) }
                            }.pickerStyle(.menu)
                        }.padding(.horizontal, 16).padding(.vertical, 6)
                        Divider().padding(.leading, 16)
                        TextField("工作指示（選填）：這個 Bot 負責什麼、該怎麼回答", text: $instructions, axis: .vertical).lineLimit(2...6).padding(16)
                    }
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
                    Text("連接器、Skill、權限和存取範圍使用預設值，之後可以在 Mac 上調整。").font(.footnote).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
                    if let problem = problem { Text(problem).font(.footnote).foregroundStyle(.red) }
                }
                .padding(.horizontal, 24).padding(.bottom, 24)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("建立新 Bot").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarLeading) { Button { dismiss() } label: { Image(systemName: "xmark") }.accessibilityLabel("關閉") } }
            .safeAreaInset(edge: .bottom) {
                Button { Task { await save() } } label: {
                    Group { if saving { ProgressView() } else { Text("建立").fontWeight(.semibold) } }.frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent).controlSize(.large).buttonBorderShape(.capsule)
                .disabled(saving || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.state != .online)
                .padding(.horizontal, 24).padding(.bottom, 10).background(.bar)
            }
            .task { providers = (try? await model.api?.providers()) ?? [] }
        }
    }

    private func save() async {
        guard let api = model.api else { problem = "連不到你的 Mac。"; return }
        saving = true; problem = nil
        do {
            try await api.createBot(name: name.trimmingCharacters(in: .whitespacesAndNewlines), instructions: instructions, provider: provider, color: color, shape: String(shape))
            Haptics.tap(); await model.refreshHome(); dismiss()
        } catch { problem = error.localizedDescription }
        saving = false
    }
}

// MARK: - Settings

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @AppStorage("appearance") private var appearance = "system"
    @AppStorage("haptics") private var haptics = true
    @State private var settings: MacSettings?
    @State private var confirmUnpair = false
    private let modes = ["manual": "謹慎", "auto": "自動", "bypass": "全部允許"]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 14) {
                        Image(systemName: "desktopcomputer").font(.title2).foregroundStyle(.tint).frame(width: 40)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(settings?.mac ?? "你的 Mac").font(.body.weight(.semibold))
                            Text(model.state == .online ? "已連線" : model.state == .connecting ? "正在連線…" : "連不到").font(.subheadline).foregroundStyle(model.state == .online ? Color.green : Color.secondary)
                        }
                    }.padding(.vertical, 4)
                    NavigationLink { UsageView() } label: { Label("用量", systemImage: "chart.bar") }
                    NavigationLink { SchedulesView() } label: { Label("排程", systemImage: "calendar.badge.clock") }
                }
                Section {
                    NavigationLink { SwitchListView(title: "連接器", items: settings?.connectors, empty: "Mac 上還沒有連接器。") } label: { row("連接器", "puzzlepiece.extension", settings.map { "已開啟 \($0.connectors.filter(\.on).count) 個" }) }
                    NavigationLink { SwitchListView(title: "Skills", items: settings?.skills, empty: "Mac 上還沒有 Skill。") } label: { row("Skills", "sparkles", settings.map { "已開啟 \($0.skills.filter(\.on).count) 個" }) }
                } footer: { Text("所有 Bot 共用。要開啟或關閉請在 Mac 上操作。") }
                Section {
                    row("主動性", "hand.raised", settings.map { modes[$0.permissionMode] ?? $0.permissionMode })
                    row("上網搜尋", "globe", settings.map { $0.webSearch ? "開啟" : "關閉" })
                    row("預設模型", "cpu", settings?.model)
                    NavigationLink { DeviceListView(devices: settings?.devices, this: settings?.thisDevice) } label: { row("已配對的裝置", "iphone", settings.map { "\($0.devices.count) 台" }) }
                } header: { Text("Bot") } footer: { Text("這些設定只能在 Mac 上更改。") }
                Section {
                    Picker(selection: $appearance) { Text("系統").tag("system"); Text("淺色").tag("light"); Text("深色").tag("dark") } label: { Label("外觀", systemImage: "circle.lefthalf.filled") }.pickerStyle(.menu)
                    Toggle(isOn: $haptics) { Label("觸感反饋", systemImage: "hand.tap") }
                }
                Section {
                    Button(role: .destructive) { confirmUnpair = true } label: { Label("解除這支 iPhone 的配對", systemImage: "iphone.slash").foregroundStyle(.red) }
                } footer: {
                    Text("Zook \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") (\(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""))\n對話只存在你的 Mac 上，傳輸全程加密。")
                        .frame(maxWidth: .infinity).multilineTextAlignment(.center).padding(.top, 16)
                }
            }
            .navigationTitle("設定").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarLeading) { Button { dismiss() } label: { Image(systemName: "xmark") }.accessibilityLabel("關閉") } }
            .confirmationDialog("解除配對後，要再使用必須在 Mac 上重新產生 QR code。", isPresented: $confirmUnpair, titleVisibility: .visible) {
                Button("解除配對", role: .destructive) { dismiss(); model.unpair() }
                Button("取消", role: .cancel) {}
            }
            .task { settings = try? await model.api?.settings() }
        }
    }

    private func row(_ title: String, _ symbol: String, _ value: String?) -> some View {
        HStack { Label(title, systemImage: symbol); Spacer(); Text(value ?? "—").foregroundStyle(.secondary).lineLimit(1) }
    }
}

private struct SwitchListView: View {
    let title: String, items: [SwitchItem]?, empty: String

    var body: some View {
        List {
            if let items = items {
                if items.isEmpty { Text(empty).foregroundStyle(.secondary) }
                if items.contains(where: \.on) { Section("已開啟") { ForEach(items.filter(\.on)) { item in Label(item.name, systemImage: "checkmark.circle.fill").symbolRenderingMode(.multicolor) } } }
                if items.contains(where: { !$0.on }) { Section("未開啟") { ForEach(items.filter { !$0.on }) { item in Label(item.name, systemImage: "circle").foregroundStyle(.secondary) } } }
            } else { HStack { Spacer(); ProgressView(); Spacer() } }
        }
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
    }
}

private struct DeviceListView: View {
    let devices: [PairedDevice]?, this: String?

    var body: some View {
        List {
            Section {
                ForEach(devices ?? []) { device in
                    HStack {
                        Label(device.name, systemImage: "iphone")
                        if device.id == this { Text("這支手機").font(.caption).padding(.horizontal, 7).padding(.vertical, 3).background(Color.accentColor.opacity(0.15), in: Capsule()) }
                        Spacer()
                        Text(shortTime(device.lastSeenAt)).font(.caption).foregroundStyle(.secondary)
                    }
                }
            } footer: { Text("要撤銷其他裝置，請在 Mac 的「設定 → 遠端連線」操作。") }
        }
        .navigationTitle("已配對的裝置").navigationBarTitleDisplayMode(.inline)
    }
}

struct UsageView: View {
    @EnvironmentObject var model: AppModel
    @State private var quota: QuotaView?
    @State private var problem: String?
    @State private var autoWanted: Int?          // chosen here and not yet confirmed by the Mac
    @State private var autoProblem: String?
    @State private var autoChain: Task<Void, Never>?  // choices are sent one after another, so the last one chosen is the one that stays
    @State private var detectDone: Double?

    var body: some View {
        List {
            if let quota = quota {
                Section {
                    Picker("自動偵測", selection: Binding(get: { autoWanted ?? quota.usageDetectEvery ?? 0 }, set: { every in setAuto(every) })) {
                        ForEach(UsageView.autoChoices, id: \.0) { choice in Text(choice.1).tag(choice.0) }
                    }.pickerStyle(.menu)
                } footer: {
                    VStack(alignment: .leading, spacing: 4) {
                        if let autoProblem = autoProblem { Text(autoProblem).foregroundStyle(.red) }
                        Text("自動偵測時，Claude 每次會用到一點點額度。")
                    }
                }
                ForEach(quota.providers) { provider in
                    Section(provider.name.components(separatedBy: "（").first ?? provider.name) {
                        if provider.status != "logged_in" { Text("尚未登入").foregroundStyle(.secondary) }
                        else if let windows = provider.quota?.windows, !windows.isEmpty {
                            ForEach(windows, id: \.label) { window in
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack { Text(window.label); Spacer(); Text("剩餘 \(Int((100 - window.usedPercent).rounded()))%").fontWeight(.semibold) }
                                    ProgressView(value: min(max(window.usedPercent, 0), 100), total: 100).tint(window.usedPercent >= 90 ? .red : window.usedPercent >= 70 ? .orange : .green)
                                }.padding(.vertical, 4)
                            }
                        } else { Text("暫無資料").foregroundStyle(.secondary) }
                    }
                }
            } else if let problem = problem { Text(problem).foregroundStyle(.red) }
            else { HStack { Spacer(); ProgressView("正在讀取額度…"); Spacer() } }
        }
        .navigationTitle("用量").navigationBarTitleDisplayMode(.inline)
        .task {
            do { quota = try await model.api?.quota() } catch { problem = error.localizedDescription }
            // While this page is open: read the figures again after each detection on the Mac, and keep 自動偵測 on what the Mac has.
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 30_000_000_000)
                guard !Task.isCancelled, let status = try? await model.api?.usageDetectStatus() else { continue }
                if autoWanted == nil { quota?.usageDetectEvery = status.usageDetectEvery }
                if !status.running, status.doneAt > 0, let seen = detectDone, seen != status.doneAt, let fresh = try? await model.api?.quota() {
                    quota = autoWanted == nil ? fresh : QuotaView(providers: fresh.providers, usageDetectEvery: quota?.usageDetectEvery)
                }
                detectDone = status.doneAt
            }
        }
    }

    static let autoChoices: [(Int, String)] = [(0, "關閉"), (15, "每 15 分鐘"), (30, "每 30 分鐘"), (60, "每 1 小時"), (180, "每 3 小時")]

    private func setAuto(_ every: Int) {
        autoWanted = every; autoProblem = nil
        let before = autoChain, api = model.api
        autoChain = Task { @MainActor in
            _ = await before?.value  // the earlier choice reaches the Mac first
            do {
                guard let api = api else { throw LinkError.macOffline }
                try await api.setUsageDetect(every: every)
                quota?.usageDetectEvery = every
                if autoWanted == every { autoWanted = nil }
            } catch {
                autoProblem = "自動偵測沒有改成功：" + error.localizedDescription
                if autoWanted == every { autoWanted = nil }  // show what the Mac still has
            }
        }
    }
}
