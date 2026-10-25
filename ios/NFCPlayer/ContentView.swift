import SwiftUI
import WebKit

struct ContentView: View {
    @ObservedObject private var link = PlayerLink.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            Group {
                if let url = link.pageURL {
                    PlayerPage(url: url, version: link.pageVersion)
                        .ignoresSafeArea(edges: .bottom)
                } else {
                    ContentUnavailableView {
                        Label("Looking for your player", systemImage: "dot.radiowaves.left.and.right")
                    } description: {
                        Text("Keep the player plugged in and your phone nearby. It needs to be set up on your Wi-Fi first.")
                    }
                }
            }
            .navigationTitle("NFC Player")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    StatusBadge(status: link.status)
                        .labelStyle(.titleAndIcon)
                        .font(.footnote)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("Reload", systemImage: "arrow.clockwise") { link.reloadPage() }
                        Button("Forget this player", systemImage: "xmark.circle", role: .destructive) { link.forgetPlayer() }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { link.reloadPage() } // Show what the player is waiting for now
        }
    }
}

private struct StatusBadge: View {
    let status: PlayerLink.Status

    var body: some View {
        switch status {
        case .connected: Label("Connected", systemImage: "circle.fill").foregroundStyle(.green)
        case .outOfRange: Label("Out of range", systemImage: "circle.fill").foregroundStyle(.orange)
        case .searching: Label("Searching", systemImage: "circle.dotted").foregroundStyle(.secondary)
        case .bluetoothOff: Label("Bluetooth off", systemImage: "circle.slash").foregroundStyle(.red)
        }
    }
}

/// The player's own web page (paste a link, change settings) in a web view.
private struct PlayerPage: UIViewRepresentable {
    let url: URL
    let version: Int

    final class Coordinator {
        var loadedURL: URL?
        var loadedVersion = -1
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.allowsBackForwardNavigationGestures = true
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let loaded = context.coordinator
        guard loaded.loadedURL != url || loaded.loadedVersion != version else { return }
        loaded.loadedURL = url
        loaded.loadedVersion = version
        webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
    }
}
