import Foundation

// Turns a link or text shared from a streaming app into a card record. The
// service's own ID is in the link: netflix.com/title/<id>, disneyplus.com/browse/entity-<uuid>,
// hulu.com/series/<slug>-<uuid> and so on. Nothing here talks to the network.

struct SharedTitle: Equatable {
    var svc: String
    var name: String
    var contentID: String
    var kind: TMDBTitle.Kind? // nil when the link doesn't say movie or show
    var title: String?        // From the text shared with the link, if any
    var needsType: Bool       // Whether the player's deep link wants movie/show
    var warning: String? = nil // Why this ID may not play
}

enum ShareLinkParser {
    static func parse(_ text: String) -> SharedTitle? {
        guard let url = firstURL(in: text), let host = url.host?.lowercased() else { return nil }
        let path = url.pathComponents.filter { $0 != "/" }
        let lower = path.map { $0.lowercased() }
        var title = sharedTitle(from: text, url: url)

        func make(_ svc: String, _ name: String, id: String?, kind: TMDBTitle.Kind? = nil, needsType: Bool = true, warning: String? = nil) -> SharedTitle? {
            guard let id, !id.isEmpty else { return nil }
            if title?.isEmpty == true { title = nil }
            return SharedTitle(svc: svc, name: name, contentID: id, kind: kind, title: title, needsType: needsType, warning: warning)
        }
        func isHost(_ names: String...) -> Bool {
            names.contains { host == $0 || host.hasSuffix("." + $0) }
        }

        if isHost("netflix.com") {
            // /title/81591296, /watch/81591296, or either with a language prefix
            let id = lower.firstIndex(where: { $0 == "title" || $0 == "watch" })
                .flatMap { $0 + 1 < path.count ? path[$0 + 1] : nil }
                .flatMap { $0.allSatisfy(\.isNumber) ? $0 : nil }
            return make("netflix", "Netflix", id: id)
        }
        if isHost("disneyplus.com") {
            let kind: TMDBTitle.Kind? = lower.contains("movies") ? .movie : (lower.contains("series") ? .tv : nil)
            // /browse/entity-<uuid>, /play/<uuid>, /video/<uuid> carry a UUID; /movies/<slug>/<code> ends in a short code
            let id = path.compactMap { uuid(in: $0) }.first
                ?? (kind != nil && path.count >= 3 ? path.last : nil)
            // Verified on the TV: a movie's entity ID plays with mediaType=movie (about 30 s to start).
            return make("disney", "Disney+", id: id, kind: kind)
        }
        if isHost("hulu.com") {
            let kind: TMDBTitle.Kind? = lower.contains("movie") ? .movie : (lower.contains("series") ? .tv : nil)
            return make("hulu", "Hulu", id: path.compactMap { uuid(in: $0) }.last, kind: kind)
        }
        if isHost("primevideo.com", "amazon.com", "amazon.co.uk") {
            // /detail/<ASIN>, /dp/<ASIN>, /gp/video/detail/<ASIN>
            let id = lower.firstIndex(where: { $0 == "detail" || $0 == "dp" })
                .flatMap { $0 + 1 < path.count ? path[$0 + 1] : nil }
                .flatMap { $0.count == 10 && $0.allSatisfy({ $0.isLetter || $0.isNumber }) ? $0 : nil }
            return make("prime", "Prime Video", id: id)
        }
        if isHost("tv.apple.com") {
            let kind: TMDBTitle.Kind? = lower.contains("movie") ? .movie : (lower.contains("show") ? .tv : nil)
            return make("appletv", "Apple TV", id: path.first { $0.hasPrefix("umc.cmc.") }, kind: kind)
        }
        if isHost("max.com", "hbomax.com") {
            let kind: TMDBTitle.Kind? = lower.contains("movie") ? .movie : (lower.contains("show") || lower.contains("series") ? .tv : nil)
            return make("max", "Max", id: path.compactMap { uuid(in: $0) }.first, kind: kind)
        }
        if isHost("youtube.com", "youtu.be") {
            let id: String?
            if host == "youtu.be" {
                id = path.first
            } else if let v = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "v" })?.value {
                id = v
            } else {
                id = lower.firstIndex(where: { $0 == "shorts" || $0 == "embed" || $0 == "live" })
                    .flatMap { $0 + 1 < path.count ? path[$0 + 1] : nil }
            }
            return make("youtube", "YouTube", id: id, needsType: false)
        }
        return nil
    }

    /// A short message for a link that parsed as nothing.
    static func problem(for text: String) -> String {
        guard let url = firstURL(in: text) else { return "No link found. Paste the link from the app's Share button." }
        return "NFCMP doesn't know how to read links from \(url.host ?? "that site") yet, or the link has no title ID in it. Short links (like amzn.to) need to be opened first, then shared from the title's page."
    }

    private static func firstURL(in text: String) -> URL? {
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        let range = NSRange(text.startIndex..., in: text)
        return detector?.matches(in: text, range: range).compactMap(\.url).first { $0.scheme?.hasPrefix("http") == true }
    }

    /// The text shared along with the link ("Watch Bluey on Disney+"), cleaned up to just the title.
    private static func sharedTitle(from text: String, url: URL) -> String? {
        var rest = text.replacingOccurrences(of: url.absoluteString, with: "")
        for link in ["https://", "http://"] where rest.contains(link) { return nil } // Another link: ambiguous
        rest = rest.trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: "\u{201C}\u{201D}\"'")))
        let patterns = ["^(Watch|Check out|Stream)\\s+", "\\s+(on|from|\\|)\\s+(Disney\\+|Netflix|Hulu|Max|Prime Video|Apple TV\\+?|YouTube)\\.?$",
                        "\\s*[-–|]\\s*(Disney\\+|Netflix|Hulu|Max|Prime Video|Apple TV\\+?)$"]
        for pattern in patterns {
            rest = rest.replacingOccurrences(of: pattern, with: "", options: [.regularExpression, .caseInsensitive])
        }
        rest = rest.trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: "\u{201C}\u{201D}\"'")))
        return rest.isEmpty || rest.count > 120 ? nil : rest
    }

    /// A UUID inside a path piece such as "entity-3f2c…" or "bluey-3f2c…".
    private static func uuid(in piece: String) -> String? {
        guard let range = piece.range(of: "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                                      options: .regularExpression) else { return nil }
        return String(piece[range]).lowercased()
    }
}

/// The nfcmp://share link the Share Extension uses to hand text to the app.
enum ShareHandoff {
    static let scheme = "nfcmp"

    static func url(for text: String) -> URL? {
        var components = URLComponents()
        components.scheme = scheme
        components.host = "share"
        components.queryItems = [URLQueryItem(name: "text", value: text)]
        return components.url
    }

    static func text(from url: URL) -> String? {
        guard url.scheme == scheme, url.host == "share" else { return nil }
        return URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "text" }?.value
    }
}
