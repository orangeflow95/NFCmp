import SwiftUI

/// The home screen: search your library and TMDB for a title to put on a card.
struct ContentView: View {
    @ObservedObject private var player = Player.shared
    @AppStorage("tmdbKey") private var tmdbKey = ""
    @AppStorage(Player.addressKey) private var playerAddress = ""
    @Environment(\.scenePhase) private var scenePhase
    @State private var editingAddress = false
    @State private var addressDraft = ""
    @State private var scanned: ScannedCard?
    @State private var scanProblem: String?
    @State private var sharedText: SharedText? // A pasted or shared link being turned into a card
    @State private var showingSetup = false
    @State private var offeredSetup = false // Setup opens by itself once per launch when the player needs it

    var body: some View {
        NavigationStack {
            SearchView()
                .navigationTitle("NFCMP")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button { showingSetup = true } label: {
                            StatusBadge(status: player.status)
                                .labelStyle(.titleAndIcon)
                                .font(.footnote)
                                .fixedSize() // iOS 26 toolbar bubbles otherwise cut the words off
                        }
                    }
                    if PhoneCard.isAvailable {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button("Read a card", systemImage: "wave.3.right.circle") {
                                Task { await readCard() }
                            }
                        }
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button("Paste a share link", systemImage: "link") {
                                sharedText = SharedText(text: "")
                            }
                            Button("Player settings", systemImage: "gearshape") {
                                showingSetup = true
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
                .safeAreaInset(edge: .bottom) {
                    if player.needsSetup {
                        SetupBanner(problem: player.setup?.tv.kind == nil ? "Choose the TV your cards play on." : player.setup?.tv.problem) { showingSetup = true }
                    }
                }
                .sheet(isPresented: $showingSetup) { PlayerSetupView() }
                .sheet(item: $scanned) { ReadCardView(card: $0) }
                .sheet(item: $sharedText) { ShareLinkView(text: $0.text) }
                .onOpenURL { url in // From the Share Extension: nfcmp://share?text=…
                    if let text = ShareHandoff.text(from: url) { sharedText = SharedText(text: text) }
                }
                .alert("Couldn't read the card", isPresented: Binding(get: { scanProblem != nil }, set: { if !$0 { scanProblem = nil } })) {
                    Button("OK", role: .cancel) {}
                } message: {
                    Text(scanProblem ?? "")
                }
        }
        .task {
            await player.check()
            if player.needsSetup, !offeredSetup {
                offeredSetup = true
                showingSetup = true
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await player.check() } }
        }
    }

    private func readCard() async {
        do {
            scanned = try await PhoneCard.read()
        } catch is CancellationError {
        } catch {
            scanProblem = error.localizedDescription
        }
    }
}

private struct SharedText: Identifiable {
    let id = UUID()
    let text: String
}

/// "Finish setting up": shown along the bottom until the player has a working TV.
private struct SetupBanner: View {
    let problem: String?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: "tv.badge.wifi").font(.title3)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Finish setting up your player").font(.subheadline.bold())
                    if let problem { Text(problem).font(.caption).opacity(0.85) }
                }
                Spacer()
                Image(systemName: "chevron.right")
            }
            .foregroundStyle(.white)
            .padding()
            .background(.tint, in: RoundedRectangle(cornerRadius: 16))
        }
        .buttonStyle(.plain)
        .padding(.horizontal)
        .padding(.bottom, 8)
    }
}

private struct StatusBadge: View {
    let status: Player.Status

    // An icon and text side by side, not a Label: iOS 26 shows only a Label's icon, in one color, inside a toolbar button
    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: icon).foregroundStyle(color)
            Text(title).foregroundStyle(.primary)
        }
        .accessibilityElement(children: .combine)
    }

    private var title: String {
        switch status {
        case .online: "Online"
        case .offline: "Offline"
        case .checking: "Checking"
        }
    }

    private var icon: String { status == .checking ? "circle.dotted" : "circle.fill" }

    private var color: Color {
        switch status {
        case .online: .green
        case .offline: .orange
        case .checking: .secondary
        }
    }
}
