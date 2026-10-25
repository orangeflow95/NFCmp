import SwiftUI

/// The home screen: search your library and TMDB for a title to put on a card.
struct ContentView: View {
    @ObservedObject private var player = Player.shared
    @AppStorage("tmdbKey") private var tmdbKey = ""
    @AppStorage(Player.addressKey) private var playerAddress = ""
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    @State private var editingAddress = false
    @State private var addressDraft = ""

    var body: some View {
        NavigationStack {
            SearchView()
                .navigationTitle("NFCMP")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        StatusBadge(status: player.status)
                            .labelStyle(.titleAndIcon)
                            .font(.footnote)
                            .fixedSize() // iOS 26 toolbar bubbles otherwise cut the words off
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button("Player settings", systemImage: "gearshape") {
                                openURL(Player.url.appendingPathComponent("setup"))
                            }
                            Button("Player address", systemImage: "network") {
                                addressDraft = playerAddress
                                editingAddress = true
                            }
                            if !tmdbKey.isEmpty {
                                Button("Change TMDB key", systemImage: "key") { tmdbKey = "" }
                            }
                        } label: {
                            Image(systemName: "ellipsis.circle")
                        }
                    }
                }
                .alert("Player address", isPresented: $editingAddress) {
                    TextField(Player.defaultAddress, text: $addressDraft)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Button("Save") {
                        playerAddress = addressDraft
                        Task { await player.check() }
                    }
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text("Leave blank to find the player automatically. Otherwise enter its IP address, shown in its log at startup.")
                }
        }
        .task { await player.check() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await player.check() } }
        }
    }
}

private struct StatusBadge: View {
    let status: Player.Status

    var body: some View {
        switch status {
        case .online: Label("Online", systemImage: "circle.fill").foregroundStyle(.green)
        case .offline: Label("Offline", systemImage: "circle.fill").foregroundStyle(.orange)
        case .checking: Label("Checking", systemImage: "circle.dotted").foregroundStyle(.secondary)
        }
    }
}
