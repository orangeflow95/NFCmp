import SwiftUI

/// Player settings: everything after Wi-Fi. Choose the TV, pair a Google TV, test it,
/// sign in to a media server, or move the player to another Wi-Fi.
struct PlayerSetupView: View {
    @ObservedObject private var player = Player.shared
    @Environment(\.dismiss) private var dismiss
    @State private var testing = false
    @State private var message: (title: String, text: String)?
    @State private var confirmingWiFi = false

    var body: some View {
        NavigationStack {
            Group {
                if let setup = player.setup {
                    form(setup)
                } else if player.status == .checking {
                    ProgressView("Looking for your player…")
                } else {
                    NotFoundView { Task { await player.check() } }
                }
            }
            .navigationTitle("Player")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .alert(message?.title ?? "", isPresented: Binding(get: { message != nil }, set: { if !$0 { message = nil } })) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(message?.text ?? "")
            }
        }
        .task { await player.check() }
    }

    private func form(_ setup: PlayerStatus) -> some View {
        Form {
            Section {
                NavigationLink {
                    ChooseTVView()
                } label: {
                    TVRow(tv: setup.tv)
                }
                if setup.tv.kind == "googletv" {
                    NavigationLink {
                        PairTVView()
                    } label: {
                        LabeledContent("Pairing") {
                            if setup.tv.paired == true {
                                Label("Paired", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                            } else {
                                Text("Not paired").foregroundStyle(.orange)
                            }
                        }
                    }
                }
                if setup.tv.kind != nil, setup.tv.ip != nil {
                    Button {
                        Task { await testTV() }
                    } label: {
                        HStack {
                            Label("Turn on the TV", systemImage: "power")
                            if testing { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(testing)
                }
            } header: {
                Text("TV")
            } footer: {
                if setup.tv.kind == nil {
                    Text("Pick the TV the player turns on when you tap a card.")
                } else if let problem = setup.tv.problem {
                    Text(problem)
                } else {
                    Text("Cards play on this TV. They work on any TV, so you can switch later without rewriting them.")
                }
            }

            Section {
                NavigationLink {
                    MediaServerView(server: setup.server)
                } label: {
                    LabeledContent("Media server") {
                        Text(serverSummary(setup.server))
                            .foregroundStyle(setup.server.problem == nil ? Color.secondary : Color.orange)
                    }
                }
            } footer: {
                Text("Optional. With Jellyfin, the app also searches your own movies and shows.")
            }

            Section {
                Button("Move to another Wi-Fi", systemImage: "wifi") { confirmingWiFi = true }
            } footer: {
                Text("Player version \(setup.version)")
            }
            .confirmationDialog("Move the player to another Wi-Fi?", isPresented: $confirmingWiFi, titleVisibility: .visible) {
                Button("Restart in Wi-Fi setup") { Task { await moveWiFi() } }
            } message: {
                Text("The player restarts and opens its own Wi-Fi network. Your TV and cards stay set up.")
            }
        }
    }

    private func serverSummary(_ server: PlayerStatus.Server) -> String {
        guard let kind = server.kind else { return "None" }
        let name = PlayerLibrary.serverName(kind)
        if server.problem != nil { return "\(name): needs attention" }
        return server.signedIn ? name : "\(name): not signed in"
    }

    private func testTV() async {
        testing = true
        defer { testing = false }
        do {
            try await PlayerAPI.testTV()
        } catch {
            message = ("Couldn't reach the TV", error.localizedDescription)
        }
    }

    private func moveWiFi() async {
        do {
            try await PlayerAPI.restartIntoWiFiSetup()
            message = ("Player restarting", "In a few seconds, open Settings → Wi-Fi on this phone and join \"NFC Movie Player\". A page opens to pick the new Wi-Fi.")
            player.setup = nil
        } catch {
            message = ("Couldn't reach the player", error.localizedDescription)
        }
    }
}

/// The TV's name, address and whether it's ready.
private struct TVRow: View {
    let tv: PlayerStatus.TV

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "tv")
                .font(.title2)
                .foregroundStyle(.tint)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(tv.kind == nil ? "Choose your TV" : tv.name)
                if let ip = tv.ip, tv.kind != nil {
                    Text(ip).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if tv.kind != nil, tv.problem == nil {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
            } else {
                Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange)
            }
        }
    }
}

/// Shown when the app can't reach the player: how to fix it, and how to set up a new one.
private struct NotFoundView: View {
    let retry: () -> Void

    var body: some View {
        ContentUnavailableView {
            Label("Can't find your player", systemImage: "wifi.exclamationmark")
        } description: {
            VStack(alignment: .leading, spacing: 12) {
                Text("**Already set up?** Make sure this phone is on the same Wi-Fi as the player, and the player is plugged in.")
                Text("**New player?** Plug it in, then open Settings → Wi-Fi on this phone and join **NFC Movie Player**. Pick your home Wi-Fi on the page that opens, then come back here.")
            }
            .multilineTextAlignment(.leading)
        } actions: {
            Button("Try again", action: retry).buttonStyle(.borderedProminent)
        }
    }
}

/// Lists the TVs the player finds on the Wi-Fi; tapping one picks it. A Google TV goes on to pairing.
struct ChooseTVView: View {
    @ObservedObject private var player = Player.shared
    @Environment(\.dismiss) private var dismiss
    @State private var found: [FoundTV]?
    @State private var scanning = false
    @State private var saving: String? // IP being saved
    @State private var problem: String?
    @State private var manualKind = "roku"
    @State private var manualIP = ""
    @State private var pairing = false

    var body: some View {
        List {
            Section {
                if scanning {
                    HStack(spacing: 12) {
                        ProgressView()
                        Text("Looking for TVs on your Wi-Fi…").foregroundStyle(.secondary)
                    }
                } else if let found, found.isEmpty {
                    Text("No TVs found. Make sure the TV is on and on the same Wi-Fi as the player, then look again.")
                        .foregroundStyle(.secondary)
                }
                ForEach(found ?? []) { tv in
                    Button {
                        Task { await choose(kind: tv.kind, ip: tv.ip, name: tv.name) }
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "tv").font(.title3).foregroundStyle(.tint).frame(width: 28)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(tv.name).foregroundStyle(.primary)
                                Text("\(kindName(tv.kind)) · \(tv.ip)").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if saving == tv.ip {
                                ProgressView()
                            } else if player.setup?.tv.ip == tv.ip, player.setup?.tv.kind == tv.kind {
                                Image(systemName: "checkmark").foregroundStyle(.tint)
                            }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(saving != nil)
                }
                if !scanning {
                    Button("Look again", systemImage: "arrow.clockwise") { Task { await scan() } }
                }
            } header: {
                Text("TVs on your Wi-Fi")
            } footer: {
                if let problem { Text(problem).foregroundStyle(.red) }
            }

            Section {
                Picker("Type", selection: $manualKind) {
                    ForEach(player.setup?.tvKinds ?? []) { kind in
                        Text(kind.available ? kind.name : "\(kind.name) (coming soon)")
                            .tag(kind.id)
                            .selectionDisabled(!kind.available)
                    }
                }
                TextField("IP address, like 192.168.1.20", text: $manualIP)
                    .keyboardType(.decimalPad)
                Button("Use this TV") {
                    Task { await choose(kind: manualKind, ip: manualIP) }
                }
                .disabled(manualIP.isEmpty || saving != nil)
            } header: {
                Text("Not listed?")
            } footer: {
                Text("Find the IP address in the TV's network settings. On a Roku: Settings → Network → About. On a Google TV: Settings → System → About → Status.")
            }
        }
        .navigationTitle("Choose your TV")
        .navigationDestination(isPresented: $pairing) { PairTVView() }
        .onChange(of: pairing) { _, open in
            if !open, player.setup?.tv.paired == true { dismiss() } // Paired: back to the player settings
        }
        .task { if found == nil { await scan() } }
    }

    private func kindName(_ kind: String) -> String {
        player.setup?.tvKinds.first { $0.id == kind }?.name ?? kind
    }

    private func scan() async {
        scanning = true
        problem = nil
        defer { scanning = false }
        do {
            found = try await PlayerAPI.findTVs()
        } catch {
            problem = error.localizedDescription
        }
    }

    private func choose(kind: String, ip: String, name: String = "") async {
        saving = ip
        problem = nil
        defer { saving = nil }
        do {
            player.setup = try await PlayerAPI.setTV(kind: kind, ip: ip.trimmingCharacters(in: .whitespaces), name: name)
            if kind == "googletv", player.setup?.tv.paired != true {
                pairing = true
            } else {
                dismiss()
            }
        } catch {
            problem = error.localizedDescription
        }
    }
}

/// Pairs the player with a Google TV: the TV shows a code, the user types it here.
struct PairTVView: View {
    private enum Step { case start, code, done }

    @ObservedObject private var player = Player.shared
    @Environment(\.dismiss) private var dismiss
    @State private var step = Step.start
    @State private var code = ""
    @State private var working = false
    @State private var problem: String?
    @FocusState private var codeFocused: Bool

    private var ready: Bool { player.setup?.tv.pairingReady ?? true }

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            switch step {
            case .start where !ready:
                ProgressView()
                Text("Getting ready").font(.title2.bold())
                Text("The player is preparing to talk to Google TV. The first time takes a minute or two.")
            case .start:
                Image(systemName: "tv").font(.system(size: 64)).foregroundStyle(.tint)
                Text("Pair with your TV").font(.title2.bold())
                Text("Turn on the TV, then tap the button. A code appears on the TV screen.")
                Button {
                    Task { await start() }
                } label: {
                    if working { ProgressView() } else { Text("Show code on TV") }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(working)
            case .code:
                Image(systemName: "number.square").font(.system(size: 64)).foregroundStyle(.tint)
                Text("Enter the code on the TV").font(.title2.bold())
                TextField("A1B2C3", text: $code)
                    .font(.system(size: 36, weight: .semibold, design: .monospaced))
                    .multilineTextAlignment(.center)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                    .focused($codeFocused)
                    .onChange(of: code) { _, new in
                        code = String(new.uppercased().filter(\.isHexDigit).prefix(6))
                    }
                    .onSubmit { Task { await finish() } }
                Button {
                    Task { await finish() }
                } label: {
                    if working { ProgressView() } else { Text("Pair") }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(code.count != 6 || working)
            case .done:
                Image(systemName: "checkmark.circle.fill").font(.system(size: 64)).foregroundStyle(.green)
                Text("Paired").font(.title2.bold())
                Text("Cards will now play on your TV.")
                Button("Done") { dismiss() }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
            }
            if let problem {
                Text(problem).foregroundStyle(.red)
            }
            Spacer()
            Spacer()
        }
        .multilineTextAlignment(.center)
        .padding()
        .navigationTitle("Google TV")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            while !ready, !Task.isCancelled { // Check until the player's certificate is made
                try? await Task.sleep(for: .seconds(3))
                await player.check()
            }
        }
        .onDisappear {
            if step == .code { Task { await PlayerAPI.cancelPairing() } }
        }
    }

    private func start() async {
        working = true
        problem = nil
        defer { working = false }
        do {
            try await PlayerAPI.startPairing()
            code = ""
            step = .code
            codeFocused = true
        } catch {
            problem = error.localizedDescription
        }
    }

    private func finish() async {
        guard code.count == 6 else { return }
        working = true
        problem = nil
        defer { working = false }
        do {
            try await PlayerAPI.finishPairing(code: code)
            step = .done
            await player.check()
        } catch {
            problem = error.localizedDescription
            if (try? await PlayerAPI.status())?.tv.pairing == false {
                step = .start // The TV ended the pairing; start over
            }
        }
    }
}

/// Choose and sign in to a media server (Jellyfin or Plex), or none.
struct MediaServerView: View {
    let server: PlayerStatus.Server
    @ObservedObject private var player = Player.shared
    @Environment(\.dismiss) private var dismiss
    @State private var kind: String?
    @State private var url = ""
    @State private var user = ""
    @State private var password = ""
    @State private var saving = false
    @State private var problem: String?

    init(server: PlayerStatus.Server) {
        self.server = server
        _kind = State(initialValue: server.kind)
        _url = State(initialValue: server.url ?? "")
        _user = State(initialValue: server.user ?? "")
    }

    var body: some View {
        Form {
            Section {
                Picker("Server", selection: $kind) {
                    Text("None").tag(String?.none)
                    Text("Jellyfin").tag(String?.some("jellyfin"))
                    Text("Plex").tag(String?.some("plex"))
                }
            } footer: {
                Text("Skip this if you don't run your own media server. Netflix, Disney+ and the rest don't need it.")
            }
            if let kind {
                Section {
                    TextField("Address (found automatically)", text: $url)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField(kind == "plex" ? "Plex email or username" : "Jellyfin username", text: $user)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField(server.signedIn && server.kind == kind ? "Password (signed in)" : "Password", text: $password)
                        .textContentType(.password)
                } footer: {
                    Text(kind == "plex"
                         ? "Your plex.tv account. Two-step verification isn't supported yet."
                         : "The account the Jellyfin app on your TV uses. The player keeps a sign-in key, not your password.")
                }
            }
            if let problem = problem ?? (kind == server.kind ? server.problem : nil) {
                Section {
                    Label(problem, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                }
            }
        }
        .navigationTitle("Media server")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if saving {
                    ProgressView()
                } else {
                    Button("Save") { Task { await save() } }
                }
            }
        }
    }

    private func save() async {
        saving = true
        problem = nil
        defer { saving = false }
        do {
            let status = try await PlayerAPI.setServer(kind: kind, url: url, user: user, password: password)
            player.setup = status
            if let serverProblem = status.server.problem {
                problem = serverProblem
            } else {
                dismiss()
            }
        } catch {
            problem = error.localizedDescription
        }
    }
}
