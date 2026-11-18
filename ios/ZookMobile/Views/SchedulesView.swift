import SwiftUI

/// The Mac's schedules. They can be paused, resumed or deleted here; making and changing them stays on the Mac.
struct SchedulesView: View {
    @EnvironmentObject var model: AppModel
    @State private var items: [ScheduleItem]?
    @State private var problem: String?
    @State private var deleting: ScheduleItem?

    var body: some View {
        List {
            if let problem = problem { Text(problem).font(.footnote).foregroundStyle(.red) }
            if let items = items, items.isEmpty { Text("Mac 上還沒有排程。").foregroundStyle(.secondary) }
            ForEach(items ?? []) { item in
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(item.content).font(.subheadline).lineLimit(2)
                        Text("\(item.when) · \(item.target)").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Toggle("啟用", isOn: Binding(get: { item.on }, set: { on in act(item, on ? "resume" : "pause") })).labelsHidden()
                }
                .swipeActions { Button(role: .destructive) { deleting = item } label: { Label("刪除", systemImage: "trash") } }
            }
        }
        .overlay { if items == nil && problem == nil { ProgressView() } }
        .navigationTitle("排程").navigationBarTitleDisplayMode(.inline)
        .refreshable { await load() }
        .task { await load() }
        .confirmationDialog("刪除這個排程？", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("刪除", role: .destructive) { if let item = deleting { act(item, "delete") } }
            Button("取消", role: .cancel) {}
        } message: { Text("刪除後無法復原。新增和修改排程請在 Mac 上操作。") }
    }

    private func load() async {
        guard let api = model.api else { return }
        do { items = try await api.schedules(); problem = nil } catch { problem = error.localizedDescription }
    }

    private func act(_ item: ScheduleItem, _ action: String) {
        guard let api = model.api else { return }
        Haptics.tap()
        Task {
            do { try await api.schedule(item.id, action) } catch { problem = error.localizedDescription }
            await load()
        }
    }
}
