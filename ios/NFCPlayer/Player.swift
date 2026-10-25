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

    /// Percent-encodes everything but unreserved characters; the player reads "+" as a space.
    private static func formEncode(_ text: String) -> String {
        text.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? text
    }
}
