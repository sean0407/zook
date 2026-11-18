// Notifications made on the phone itself, while the app is open or shortly after it goes to the background.
// Real push (with the app closed) needs Apple's paid developer programme and is not part of this build.
import UIKit
import UserNotifications

final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notifier()
    private var asked = false

    func prepare() {
        guard !asked else { return }
        asked = true
        let center = UNUserNotificationCenter.current(); center.delegate = self
        center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    func show(_ title: String, _ body: String) {
        let content = UNMutableNotificationContent(); content.title = title; content.body = body; content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
    }

    // Also shown while the app is in front, for conversations the user is not looking at.
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [.banner, .sound] }
}

/// What changed between two looks at the home screen that is worth telling the user.
func homeNews(old: Home, new: Home, open: String?, appActive: Bool) -> [(String, String)] {
    var news: [(String, String)] = []
    for bot in new.bots {
        guard let before = old.bots.first(where: { $0.id == bot.id }) else { continue }
        if before.running && !bot.running && !(appActive && open == bot.id) { news.append((bot.name, bot.preview.isEmpty ? "回覆完成" : String(bot.preview.prefix(80)))) }
    }
    for group in new.groups {
        guard let before = old.groups.first(where: { $0.id == group.id }) else { continue }
        if before.running && !group.running && !(appActive && open == group.id) { news.append((group.name, "討論結束")) }
    }
    if new.pending > old.pending { news.append(("需要你核准", "有 \(new.pending) 個動作等你決定")) }
    return news
}
