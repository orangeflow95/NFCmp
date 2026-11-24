import Foundation

/// The NFC player on the home Wi-Fi. It announces itself as nfc-player.local;
/// an address typed in the app (the "playerAddress" setting) overrides that.
/// In the simulator, launch with `-playerAddress http://<mac-ip>:8080/` to use a test server.
@MainActor
final class Player: ObservableObject {
    enum Status {
        case checking, online, offline
    }

    static let shared = Player()
    static let addressKey = "playerAddress"
    static let defaultAddress = "http://nfc-player.local/"

    @Published private(set) var status = Status.checking
    /// The player's setup (TV, pairing, media server), or nil if it isn't reachable
    /// or its firmware is older than the setup API.
    @Published var setup: PlayerStatus?

    nonisolated static var url: URL {
        let typed = UserDefaults.standard.string(forKey: addressKey)?.trimmingCharacters(in: .whitespaces) ?? ""
        let address = typed.isEmpty ? defaultAddress : (typed.hasPrefix("http") ? typed : "http://" + typed)
        return URL(string: address) ?? URL(string: defaultAddress)!
    }

    /// Asks the player's status page whether it's there.
    func check() async {
        status = .checking
        var request = URLRequest(url: Self.url)
        request.timeoutInterval = 4
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            status = (response as? HTTPURLResponse)?.statusCode == 200 ? .online : .offline
        } catch {
            status = .offline
        }
        setup = status == .online ? try? await PlayerAPI.status() : nil
    }

    /// Whether the player still needs something before cards can play: a TV, or Google TV pairing.
    var needsSetup: Bool {
        guard let tv = setup?.tv else { return false }
        return tv.kind == nil || tv.problem != nil
    }
}

/// Writing a card through the player: it writes the record to the next card tapped on it.
enum CardWriter {
    struct State: Decodable {
        let state: String // "idle", "waiting", "written", "failed" or "expired"
        let title: String?
        let error: String?
    }

    static func start(record: String) async throws -> State {
        try await post("record=\(formEncode(record))")
    }

    static func status() async throws -> State {
        var request = URLRequest(url: Player.url.appendingPathComponent("write"))
        request.timeoutInterval = 5
        return try await send(request)
    }

    static func cancel() async {
        _ = try? await post("cancel=1")
    }

    private static func post(_ body: String) async throws -> State {
        var request = URLRequest(url: Player.url.appendingPathComponent("write"))
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data(body.utf8)
        return try await send(request)
    }

    private static func send(_ request: URLRequest) async throws -> State {
        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw LookupError.http("The player", status) }
        return try JSONDecoder().decode(State.self, from: data)
    }

}

/// Percent-encodes everything but unreserved characters; the player reads "+" as a space.
func formEncode(_ text: String) -> String {
    text.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? text
}

// MARK: - Setting up the player

/// GET /api/status: what the setup screens show.
struct PlayerStatus: Decodable {
    struct TV: Decodable {
        let kind: String? // "roku", "googletv", or nil until one is chosen
        let name: String
        let ip: String?
        let paired: Bool? // Google TV only
        let pairingReady: Bool // False while the player makes its Google TV certificate
        let pairing: Bool
        let problem: String?
    }
    struct TVKind: Decodable, Identifiable {
        let id: String
        let name: String
        let available: Bool
    }
    struct Server: Decodable {
        let kind: String? // "jellyfin", "plex" or nil
        let url: String?
        let user: String?
        let signedIn: Bool
        let problem: String?
    }
    let version: String
    let tv: TV
    let tvKinds: [TVKind]
    let server: Server
}

/// A TV the player found on the Wi-Fi.
struct FoundTV: Decodable, Identifiable, Hashable {
    let kind: String
    let name: String
    let ip: String
    var id: String { ip }
}

struct PlayerProblem: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// The player's setup API (api.py on the board): form-encoded POSTs, JSON replies.
/// A reply with "error" becomes a PlayerProblem.
enum PlayerAPI {
    private struct Reply: Decodable {
        let error: String?
    }
    private struct TVList: Decodable {
        let tvs: [FoundTV]
    }

    static func status() async throws -> PlayerStatus {
        try JSONDecoder().decode(PlayerStatus.self, from: await send("api/status"))
    }

    /// Asks the player to look for TVs; takes several seconds.
    static func findTVs() async throws -> [FoundTV] {
        try JSONDecoder().decode(TVList.self, from: await send("api/tvs", timeout: 30)).tvs
    }

    /// Picks the TV. A blank IP makes the player look for that kind of TV.
    static func setTV(kind: String, ip: String = "", name: String = "") async throws -> PlayerStatus {
        try JSONDecoder().decode(PlayerStatus.self, from: await send("api/tv", form: ["kind": kind, "ip": ip, "name": name], timeout: 15))
    }

    /// Turns the TV on.
    static func testTV() async throws {
        _ = try await send("api/tv/test", form: [:], timeout: 15)
    }

    /// Makes the Google TV show a pairing code.
    static func startPairing() async throws {
        _ = try await send("api/pair/start", form: [:], timeout: 20)
    }

    static func finishPairing(code: String) async throws {
        _ = try await send("api/pair/finish", form: ["code": code], timeout: 20)
    }

    static func cancelPairing() async {
        _ = try? await send("api/pair/cancel", form: [:])
    }

    /// Sets the media server and signs in. kind nil turns it off; a blank password keeps the current sign-in.
    static func setServer(kind: String?, url: String, user: String, password: String) async throws -> PlayerStatus {
        let form = ["kind": kind ?? "", "url": url, "user": user, "password": password]
        return try JSONDecoder().decode(PlayerStatus.self, from: await send("api/server", form: form, timeout: 30))
    }

    /// Restarts the player into Wi-Fi setup: it opens its own "NFC Movie Player" network.
    static func restartIntoWiFiSetup() async throws {
        _ = try await send("api/wifi", form: [:])
    }

    /// GET, or POST when form isn't nil. Returns the reply's JSON.
    private static func send(_ path: String, form: [String: String]? = nil, timeout: TimeInterval = 8) async throws -> Data {
        var request = URLRequest(url: Player.url.appendingPathComponent(path))
        request.timeoutInterval = timeout
        if let form {
            request.httpMethod = "POST"
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data(form.map { "\($0.key)=\(formEncode($0.value))" }.joined(separator: "&").utf8)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw LookupError.http("The player", status) }
        if let message = try? JSONDecoder().decode(Reply.self, from: data).error {
            throw PlayerProblem(message: message)
        }
        return data
    }
}
