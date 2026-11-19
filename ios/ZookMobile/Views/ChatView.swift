import PhotosUI
import SwiftUI

/// A conversation with one Bot or a group. The same screen handles both.
struct ChatView: View {
    enum Kind { case bot, group }
    let kind: Kind, id: String, title: String
    @EnvironmentObject var model: AppModel
    @State private var messages: [ChatMessage] = []
    @State private var approvals: [Approval] = []
    @State private var questions: [BotQuestion] = []
    @State private var activity: [ActivityItem] = []
    @State private var running = false
    @State private var activeJob: String?
    @State private var speaking: [String] = []
    @State private var draft = ""
    @State private var sending = false
    @State private var sendId = UUID().uuidString  // stays the same while one message is being retried
    @State private var deciding: Set<String> = []
    @State private var problem: String?
    @State private var showActivity = false
    @State private var loaded = false
    @State private var chats: [ChatSummary] = []
    @State private var photos: [Data] = []
    @State private var picked: [PhotosPickerItem] = []
    @State private var showCamera = false
    @FocusState private var typing: Bool
    static let photoLimit = 4

    var body: some View {
        VStack(spacing: 0) {
            OfflineBanner().padding(.top, model.state == .online ? 0 : 8)
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        if !loaded && model.state == .online { HStack { Spacer(); ProgressView(); Spacer() }.padding(.top, 40) }
                        ForEach(messages) { message in Bubble(message: message, showName: kind == .group).id(message.id) }
                        if kind == .bot, !running, !sending, let last = messages.last, last.role != "user", last.status == "completed", let options = last.options, !options.isEmpty {
                            ChoiceRow(options: options) { option in draft = option; send() }
                        }
                        ForEach(questions) { question in
                            QuestionCard(question: question, busy: deciding.contains(question.id)) { text in answer(question, text) }.id("question-" + question.id)
                        }
                        ForEach(approvals) { approval in
                            ApprovalCard(approval: approval, busy: deciding.contains(approval.id)) { approve in decide(approval, approve) }.id("approval-" + approval.id)
                        }
                        if kind == .group, running, !speaking.isEmpty { Text("\(speaking.joined(separator: "、")) 發言中…").font(.caption).foregroundStyle(.secondary) }
                        Color.clear.frame(height: 1).id("bottom")
                    }
                    .padding(.horizontal).padding(.top, 10)
                }
                .scrollDismissesKeyboard(.interactively)
                .simultaneousGesture(TapGesture().onEnded { typing = false })   // tapping the conversation puts the keyboard away
                .onChange(of: messages.last?.id) { _, _ in proxy.scrollTo("bottom") }
                .onChange(of: messages.last?.content.count) { _, _ in proxy.scrollTo("bottom") }
                .onChange(of: approvals.count) { _, _ in proxy.scrollTo("bottom") }
            }
            if let problem = problem { Text(problem).font(.footnote).foregroundStyle(.red).padding(.horizontal).padding(.top, 4) }
            composer
        }
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if kind == .bot {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button { switchChat(nil) } label: { Label("新對話", systemImage: "square.and.pencil") }
                        ForEach(chats) { chat in Button { switchChat(chat.id) } label: { Label(chat.title, systemImage: chat.open ? "checkmark" : "bubble.left") } }
                    } label: { Image(systemName: "bubble.left.and.bubble.right") }.accessibilityLabel("對話").disabled(running)
                }
                ToolbarItem(placement: .topBarTrailing) { Button { showActivity = true } label: { Image(systemName: "list.bullet.rectangle") }.accessibilityLabel("動態") }
            }
        }
        .sheet(isPresented: $showCamera) { CameraPicker { image in add(image) }.ignoresSafeArea() }
        .onChange(of: picked) { _, items in load(items) }
        .onAppear { model.openChat = id }
        .onDisappear { if model.openChat == id { model.openChat = nil } }
        .sheet(isPresented: $showActivity) { ActivitySheet(items: activity) }
        .task(id: id) { await poll() }
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !photos.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(Array(photos.enumerated()), id: \.offset) { index, data in
                            ZStack(alignment: .topTrailing) {
                                if let image = UIImage(data: data) { Image(uiImage: image).resizable().scaledToFill().frame(width: 64, height: 64).clipShape(RoundedRectangle(cornerRadius: 10)) }
                                Button { photos.remove(at: index) } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.white, .black.opacity(0.6)) }.accessibilityLabel("移除照片").offset(x: 5, y: -5)
                            }
                        }
                    }.padding(.horizontal).padding(.top, 6)
                }
            }
            composerRow
        }
    }

    private var composerRow: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if kind == .bot {
                Menu {
                    Button { showCamera = true } label: { Label("拍照", systemImage: "camera") }.disabled(!UIImagePickerController.isSourceTypeAvailable(.camera))
                    PhotosPicker(selection: $picked, maxSelectionCount: max(1, ChatView.photoLimit - photos.count), matching: .images) { Label("從相簿選", systemImage: "photo.on.rectangle") }
                } label: { Image(systemName: "plus.circle").font(.system(size: 28)) }.accessibilityLabel("附上照片").disabled(photos.count >= ChatView.photoLimit)
            }
            TextField(kind == .group ? "傳送訊息給群組，用 @ 指定 Bot" : "傳送訊息給 \(title)", text: $draft, axis: .vertical)
                .lineLimit(1...5).focused($typing)
                .padding(.horizontal, 14).padding(.vertical, 9)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 20))
                .contextMenu {
                    Button { if let pasted = UIPasteboard.general.string { draft += pasted } } label: { Label("貼上", systemImage: "doc.on.clipboard") }
                    if !draft.isEmpty {
                        Button { UIPasteboard.general.string = draft } label: { Label("複製", systemImage: "doc.on.doc") }
                        Button(role: .destructive) { draft = "" } label: { Label("清除", systemImage: "xmark.circle") }
                    }
                }
            if running {
                Button { stop() } label: { Image(systemName: "stop.circle.fill").font(.system(size: 32)) }.accessibilityLabel("停止回覆")
            } else {
                Button { send() } label: { Image(systemName: "arrow.up.circle.fill").font(.system(size: 32)) }
                    .disabled((draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && photos.isEmpty) || sending || model.state != .online).accessibilityLabel("送出")
            }
        }
        .padding(.horizontal).padding(.vertical, 8)
    }

    private func poll() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(nanoseconds: running || !approvals.isEmpty || !questions.isEmpty ? 1_500_000_000 : 4_000_000_000)
        }
    }

    private func refresh() async {
        guard model.state == .online, let api = model.api else { return }
        do {
            if kind == .bot {
                let view = try await api.bot(id)
                messages = view.messages; approvals = view.approvals; activity = view.activity; running = view.running; activeJob = view.activeJobId; chats = view.chats ?? []; questions = view.questions ?? []
            } else {
                let view = try await api.group(id)
                messages = view.messages; approvals = view.approvals; running = view.running; speaking = view.speaking
            }
            loaded = true
            model.markSeen(id)
        } catch LinkError.macOffline {} catch { if !loaded { problem = error.localizedDescription } }
    }

    private func send() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty || !photos.isEmpty, let api = model.api else { return }
        sending = true; problem = nil; Haptics.tap()
        Task {
            do {
                if kind == .bot {
                    var ids: [String] = []
                    for photo in photos { ids.append(try await api.upload(photo: photo)) }
                    try await api.send(toBot: id, text, photos: ids, clientId: sendId)
                } else { try await api.send(toGroup: id, text, clientId: sendId) }
                sendId = UUID().uuidString  // the next message is a new one
                draft = ""; photos = []; await refresh()
            } catch { problem = error.localizedDescription }
            sending = false
        }
    }

    private func add(_ image: UIImage) {
        guard photos.count < ChatView.photoLimit, let small = image.shrunkForSending() else { return }
        photos.append(small)
    }

    private func load(_ items: [PhotosPickerItem]) {
        guard !items.isEmpty else { return }
        picked = []
        Task {
            for item in items { if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) { add(image) } }
        }
    }

    private func switchChat(_ chat: String?) {
        guard let api = model.api else { return }
        Task {
            do { if let chat = chat { try await api.openChat(bot: id, chat: chat) } else { try await api.newChat(bot: id) } } catch { problem = error.localizedDescription }
            await refresh()
        }
    }

    private func stop() {
        guard let api = model.api else { return }
        Task {
            do { if kind == .group { try await api.stop(group: id) } else if let job = activeJob { try await api.stop(job: job) } } catch { problem = error.localizedDescription }
            await refresh()
        }
    }

    private func answer(_ question: BotQuestion, _ text: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let api = model.api else { return }
        deciding.insert(question.id); Haptics.tap()
        Task {
            do { try await api.answer(question.id, text) } catch { problem = error.localizedDescription }
            await refresh(); deciding.remove(question.id)
        }
    }

    private func decide(_ approval: Approval, _ approve: Bool) {
        guard let api = model.api else { return }
        deciding.insert(approval.id); Haptics.tap()
        Task {
            do { try await api.decide(approval.id, approve: approve) } catch { problem = error.localizedDescription }
            await refresh(); deciding.remove(approval.id)
        }
    }
}

private struct Bubble: View {
    let message: ChatMessage, showName: Bool

    var body: some View {
        if message.role == "system" {
            Text(message.content).font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity)
        } else if message.role == "user" {
            VStack(alignment: .trailing, spacing: 3) {
                HStack { Spacer(minLength: 48); SelectableText(text: message.content).padding(.horizontal, 14).padding(.vertical, 9).background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 18)) }
                if let count = message.attachments, count > 0 { Label("\(count) 個附件", systemImage: "paperclip").font(.caption).foregroundStyle(.secondary) }
            }
        } else {
            VStack(alignment: .leading, spacing: 4) {
                if showName, let name = message.botName { Text(name).font(.caption).foregroundStyle(.secondary) }
                VStack(alignment: .leading, spacing: 8) {
                    if message.status == "running" && message.content.isEmpty { HStack(spacing: 8) { ProgressView().controlSize(.small); Text("正在思考…").foregroundStyle(.secondary) } }
                    else if message.content.isEmpty { Text(message.status == "cancelled" ? "已停止回覆" : "回覆失敗，請到 Mac 上檢查模型設定。").foregroundStyle(message.status == "cancelled" ? Color.secondary : Color.red) }
                    else { SelectableText(text: message.content, markdown: true) }
                    if let note = message.note { Divider(); Text(note).font(.caption).foregroundStyle(.orange) }
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 18))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(Color(.separator).opacity(0.5)))
                .frame(maxWidth: .infinity, alignment: .leading).padding(.trailing, 32)
                .contextMenu {
                    if !message.content.isEmpty {
                        Button { UIPasteboard.general.string = message.content } label: { Label("複製整則訊息", systemImage: "doc.on.doc") }
                        ShareLink(item: message.content) { Label("分享", systemImage: "square.and.arrow.up") }
                    }
                }
            }
        }
    }
}

/// The options a Bot listed at the end of its reply. Tapping one sends it as the next message.
private struct ChoiceRow: View {
    let options: [String]
    let pick: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(options, id: \.self) { option in
                Button(option) { pick(option) }.buttonStyle(.bordered).buttonBorderShape(.capsule).multilineTextAlignment(.leading)
            }
        }
    }
}

private struct QuestionCard: View {
    let question: BotQuestion, busy: Bool
    let answer: (String) -> Void
    @State private var own = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("\(question.botName) 想問你").font(.subheadline.weight(.semibold))
            Text(question.question).font(.subheadline)
            ForEach(question.options, id: \.self) { option in
                Button(option) { answer(option) }.buttonStyle(.bordered).buttonBorderShape(.capsule).multilineTextAlignment(.leading)
            }
            HStack {
                TextField(question.options.isEmpty ? "輸入你的回答" : "或自己回答", text: $own).textFieldStyle(.roundedBorder)
                Button("送出") { answer(own) }.buttonStyle(.bordered).disabled(own.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if busy { ProgressView().controlSize(.small) }
            }
            Text("回答只會告訴 Bot 你的選擇，不代表核准任何動作。").font(.caption).foregroundStyle(.secondary)
        }
        .disabled(busy)
        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.blue.opacity(0.10), in: RoundedRectangle(cornerRadius: 16))
    }
}

private struct ApprovalCard: View {
    let approval: Approval, busy: Bool
    let decide: (Bool) -> Void
    private let reasons = ["danger": "高風險動作（刪除、安全性或對外發送），一律需要核准", "code": "會執行程式碼", "external_write": "會修改外部服務", "external_read": "會查詢外部服務", "internal": "會變更 Zook 內的資料"]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(approval.text).font(.subheadline.weight(.semibold))
            if let reason = reasons[approval.category] { Text(reason).font(.caption).foregroundStyle(.secondary) }
            HStack {
                Button("允許這次") { decide(true) }.buttonStyle(.borderedProminent)
                Button("不要") { decide(false) }.buttonStyle(.bordered)
                if busy { ProgressView().controlSize(.small) }
            }.disabled(busy)
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 16))
    }
}

private struct ActivitySheet: View {
    let items: [ActivityItem]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if items.isEmpty { Text("這裡會顯示這個 Bot 做過的事。").foregroundStyle(.secondary) }
                ForEach(items) { item in
                    HStack(alignment: .top, spacing: 10) {
                        Circle().fill(color(item.state)).frame(width: 6, height: 6).padding(.top, 7)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.text).font(.subheadline)
                            if let place = item.where, !place.isEmpty { Text("在群組「\(place)」").font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
            .navigationTitle("最近動態").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
        }
    }

    private func color(_ state: String) -> Color {
        switch state { case "done": return .green; case "waiting": return .yellow; case "failed": return .red; default: return .blue }
    }
}
