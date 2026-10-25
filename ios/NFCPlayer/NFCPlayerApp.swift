import SwiftUI
import UserNotifications

/// Sets up Bluetooth and notifications at launch, including when iOS relaunches
/// the app in the background for a player event (no window appears then).
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let link = PlayerLink.shared
        let notifier = Notifier.shared
        UNUserNotificationCenter.current().delegate = notifier
        notifier.requestPermission()
        link.onEvent = { notifier.post($0) }
        notifier.onOpen = { link.reloadPage() }
        return true
    }
}

@main
struct NFCPlayerApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
