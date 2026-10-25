import Foundation

// Test lookup for card records: search TMDB, ask TMDB where the title streams
// in the US, then get each streaming service's own ID from Wikidata, looked up
// by the TMDB ID. TMDB doesn't carry streaming-service IDs itself.

struct TMDBTitle: Identifiable, Hashable {
    enum Kind: String {
        case movie, tv
    }

    let kind: Kind
    let tmdbID: Int
    let title: String
    let year: String?
    let posterPath: String?
    let overview: String

    var id: String { "\(kind.rawValue)-\(tmdbID)" }
    var kindName: String { kind == .movie ? "Movie" : "Show" }
    var posterURL: URL? { posterPath.flatMap { URL(string: "https://image.tmdb.org/t/p/w185\($0)") } }
}

/// A streaming service a card can point at. `svc` matches the card format in CLAUDE.md's roadmap.
struct StreamingService {
    let svc: String
    let name: String
    let movieProperty: String // Wikidata property holding the service's movie ID
    let showProperty: String  // ...and its show ID
    let providerPrefixes: [String] // TMDB provider names, lowercased

    static let all = [
        StreamingService(svc: "netflix", name: "Netflix", movieProperty: "P1874", showProperty: "P1874", providerPrefixes: ["netflix"]),
        StreamingService(svc: "disney", name: "Disney+", movieProperty: "P7595", showProperty: "P7596", providerPrefixes: ["disney"]),
        StreamingService(svc: "hulu", name: "Hulu", movieProperty: "P6466", showProperty: "P6467", providerPrefixes: ["hulu"]),
        StreamingService(svc: "prime", name: "Prime Video", movieProperty: "P8055", showProperty: "P8055", providerPrefixes: ["amazon prime video"]),
        StreamingService(svc: "appletv", name: "Apple TV", movieProperty: "P9586", showProperty: "P9751", providerPrefixes: ["apple tv"]),
        StreamingService(svc: "max", name: "Max", movieProperty: "P8298", showProperty: "P8298", providerPrefixes: ["max", "hbo max"]),
    ]

    func property(for kind: TMDBTitle.Kind) -> String {
        kind == .movie ? movieProperty : showProperty
    }

    func isProvider(_ providerName: String) -> Bool {
        let name = providerName.lowercased()
        return providerPrefixes.contains { name.hasPrefix($0) }
    }
}

/// A movie or show on the user's own media server, from the player's /library search.
struct LibraryItem: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let year: Int?
    let kind: String // "movie" or "tv"
    let tmdb: String?
    let poster: String?

    var tmdbKind: TMDBTitle.Kind { kind == "tv" ? .tv : .movie }
    var kindName: String { kind == "tv" ? "Show" : "Movie" }
    var posterURL: URL? { poster.flatMap(URL.init(string:)) }
}

/// One way to write the card: a service, its IDs for the title, and whether it can play it.
struct CardCandidate: Identifiable {
    let svc: String
    let name: String
    let contentIDs: [String]
    let available: Bool
    let availableText: String

    var id: String { svc }

    func records(title: String, kind: TMDBTitle.Kind) -> [String] {
        let type = kind == .movie ? "movie" : "show"
        let name = title.replacingOccurrences(of: ";", with: ",")
        return contentIDs.map { "v1;svc=\(svc);type=\(type);id=\($0);t=\(name)" }
    }
}

enum LookupError: LocalizedError {
    case badKey
    case http(String, Int)
    case player(String)

    var errorDescription: String? {
        switch self {
        case .badKey: return "TMDB didn't accept that key. Check it under Settings → API on themoviedb.org."
        case .http(let site, let code): return "\(site) answered \(code)."
        case .player(let message): return "The player couldn't search your library: \(message)"
        }
    }
}

struct TMDB {
    let key: String

    /// Accepts either a v3 API key or a v4 read access token (a long token starting with "eyJ").
    private func get(_ path: String, _ query: [URLQueryItem] = []) async throws -> Data {
        var components = URLComponents(string: "https://api.themoviedb.org/3" + path)!
        var items = query
        let usesToken = key.hasPrefix("eyJ")
        if !usesToken { items.append(URLQueryItem(name: "api_key", value: key)) }
        components.queryItems = items
        var request = URLRequest(url: components.url!)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if usesToken { request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization") }
        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 { throw LookupError.badKey }
        guard status == 200 else { throw LookupError.http("TMDB", status) }
        return data
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    func search(_ text: String) async throws -> [TMDBTitle] {
        struct Response: Decodable { let results: [Item] }
        struct Item: Decodable {
            let id: Int
            let mediaType: String
            let title: String?
            let name: String?
            let releaseDate: String?
            let firstAirDate: String?
            let posterPath: String?
            let overview: String?
        }
        let data = try await get("/search/multi", [
            URLQueryItem(name: "query", value: text),
            URLQueryItem(name: "include_adult", value: "false"),
        ])
        return try Self.decoder.decode(Response.self, from: data).results.compactMap { item in
            guard let kind = TMDBTitle.Kind(rawValue: item.mediaType) else { return nil } // Skip people
            let date = item.releaseDate ?? item.firstAirDate ?? ""
            return TMDBTitle(kind: kind, tmdbID: item.id, title: item.title ?? item.name ?? "Untitled",
                             year: date.count >= 4 ? String(date.prefix(4)) : nil,
                             posterPath: item.posterPath, overview: item.overview ?? "")
        }
    }

    /// Names of the services that stream the title in the US (subscription, free or with ads).
    func usProviders(for title: TMDBTitle) async throws -> [String] {
        struct Response: Decodable { let results: [String: Country] }
        struct Country: Decodable { let flatrate: [Provider]?; let free: [Provider]?; let ads: [Provider]? }
        struct Provider: Decodable { let providerName: String }
        let data = try await get("/\(title.kind.rawValue)/\(title.tmdbID)/watch/providers")
        guard let us = try Self.decoder.decode(Response.self, from: data).results["US"] else { return [] }
        let names = (us.flatrate ?? []) + (us.free ?? []) + (us.ads ?? [])
        var unique: [String] = []
        for name in names.map(\.providerName) where !unique.contains(name) { unique.append(name) }
        return unique
    }
}

enum Wikidata {
    /// The streaming-service IDs Wikidata has for the title, by service property.
    static func serviceIDs(for title: TMDBTitle) async throws -> [String: [String]] {
        let tmdbProperty = title.kind == .movie ? "P4947" : "P4983"
        let properties = Array(Set(StreamingService.all.map { $0.property(for: title.kind) })).sorted()
        let optionals = properties.map { "OPTIONAL { ?item wdt:\($0) ?\($0) }" }.joined(separator: " ")
        let query = "SELECT * WHERE { ?item wdt:\(tmdbProperty) \"\(title.tmdbID)\" . \(optionals) } LIMIT 50"

        var components = URLComponents(string: "https://query.wikidata.org/sparql")!
        components.queryItems = [URLQueryItem(name: "query", value: query), URLQueryItem(name: "format", value: "json")]
        var request = URLRequest(url: components.url!)
        request.setValue("NFCPlayer/0.1 (card lookup test)", forHTTPHeaderField: "User-Agent") // Wikidata asks for one
        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw LookupError.http("Wikidata", status) }

        struct Response: Decodable { let results: Results }
        struct Results: Decodable { let bindings: [[String: Value]] }
        struct Value: Decodable { let value: String }
        var ids: [String: [String]] = [:]
        for row in try JSONDecoder().decode(Response.self, from: data).results.bindings {
            for property in properties {
                if let value = row[property]?.value, !(ids[property] ?? []).contains(value) {
                    ids[property, default: []].append(value)
                }
            }
        }
        return ids
    }
}

enum CardLookup {
    /// Every service that either streams the title or has an ID for it, best matches first.
    static func candidates(for title: TMDBTitle, key: String) async throws -> (candidates: [CardCandidate], providers: [String]) {
        async let providers = TMDB(key: key).usProviders(for: title)
        async let ids = Wikidata.serviceIDs(for: title)
        let (providerNames, serviceIDs) = try await (providers, ids)
        let candidates = StreamingService.all.compactMap { service -> CardCandidate? in
            let found = serviceIDs[service.property(for: title.kind)] ?? []
            let streams = providerNames.contains(where: service.isProvider)
            guard streams || !found.isEmpty else { return nil }
            return CardCandidate(svc: service.svc, name: service.name, contentIDs: found, available: streams,
                                 availableText: streams ? "Streams here" : "Not in the US")
        }
        let ranked = candidates.sorted { a, b in
            let score = { (c: CardCandidate) in (c.available ? 2 : 0) + (c.contentIDs.isEmpty ? 0 : 1) }
            return score(a) > score(b)
        }
        return (ranked, providerNames)
    }
}

/// The user's own media server, searched through the player, which holds the sign-in.
enum PlayerLibrary {
    /// Returns nil when the player has no media server signed in.
    static func search(_ text: String) async throws -> (server: String, items: [LibraryItem])? {
        var components = URLComponents(url: Player.url.appendingPathComponent("library"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "q", value: text)]
        var request = URLRequest(url: components.url!)
        request.timeoutInterval = 6
        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw LookupError.http("The player", status) }

        struct Response: Decodable { let server: String?; let items: [LibraryItem]; let error: String? }
        let result = try JSONDecoder().decode(Response.self, from: data)
        if let error = result.error { throw LookupError.player(error) }
        guard let server = result.server else { return nil }
        return (server, result.items)
    }

    static func serverName(_ server: String) -> String {
        server == "plex" ? "Plex" : "Jellyfin"
    }
}
