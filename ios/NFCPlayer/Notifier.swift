import UserNotifications

/// Turns player events into local notifications. Tapping one opens the player's page.
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notifier()

    /// One notification at a time: each event replaces the last.
    private static let id = "card"

    var onOpen: (() -> Void)?

    func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func post(_ event: PlayerEvent) {
        let center = UNUserNotificationCenter.current()
        let content = UNMutableNotificationContent()
        switch event.kind {
        case .learn:
            content.title = "New card"
            content.body = "Start something on the TV to link it."
        case .link:
            content.title = "Link this card"
            content.body = "Something's playing on \(event.detail ?? "the TV"). Tap to paste its share link."
            content.sound = .default
        case .locked:
            content.title = "Card linked"
            content.body = event.detail ?? "Tap the card any time to play it."
        case .idle:
            center.removeDeliveredNotifications(withIdentifiers: [Self.id])
            return
        }
        center.add(UNNotificationRequest(identifier: Self.id, content: content, trigger: nil))
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        onOpen?()
        completionHandler()
    }
}
