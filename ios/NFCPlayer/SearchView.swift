import SwiftUI
import UIKit

/// What was picked in the search results: a TMDB title, a title from the user's own library, or both.
private struct Pick: Hashable {
    var tmdb: TMDBTitle?
    var library: LibraryItem?
    var server: String? // The library's media server, "jellyfin" or "plex"

    var title: String { tmdb?.title ?? library?.title ?? "Untitled" }
    var kind: TMDBTitle.Kind { tmdb?.kind ?? library?.tmdbKind ?? .movie }
    var kindName: String { kind == .movie ? "Movie" : "Show" }
    var year: String? { tmdb?.year ?? library?.year.map(String.init) }
    var posterURL: URL? { tmdb?.posterURL ?? library?.posterURL }
}

/// Search the user's library and TMDB, pick a title, see the card records the lookup can build.
struct SearchView: View {
    @AppStorage("tmdbKey") private var key = "" // Stays on this phone
    @State private var query = ""
    @State private var results: [TMDBTitle] = []
    @State private var library: (server: String, items: [LibraryItem])?
    @State private var libraryProblem: String?
    @State private var searching = false
    @State private var error: String?

    var body: some View {
        List {
            if key.isEmpty {
                Section {
                    SecureField("Paste your TMDB API key", text: $key)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("TMDB key")
                } footer: {
                    Text("Free from themoviedb.org → Settings → API. It's stored only on this phone. Without it, only your own library is searched.")
                }
            }
            if let error {
                Text(error).foregroundStyle(.red)
            }
            if searching {
                ProgressView()
            }
            if let library, !library.items.isEmpty {
                Section("In your \(PlayerLibrary.serverName(library.server))") {
                    ForEach(library.items) { item in
                        NavigationLink(value: Pick(library: item, server: library.server)) {
                            TitleRow(title: item.title, detail: [item.kindName, item.year.map(String.init)], poster: item.posterURL)
                        }
                    }
                }
            }
            if !results.isEmpty {
                Section(library?.items.isEmpty == false ? "Everywhere else" : "Results") {
                    ForEach(results) { title in
                        NavigationLink(value: Pick(tmdb: title, library: libraryMatch(for: title), server: library?.server)) {
                            TitleRow(title: title.title, detail: [title.kindName, title.year], poster: title.posterURL,
                                     inLibrary: libraryMatch(for: title) != nil)
                        }
                    }
                }
            }
            if !(results.isEmpty && library == nil && libraryProblem == nil) {
                Section {
                    if let libraryProblem {
                        Text(libraryProblem).font(.footnote).foregroundStyle(.secondary)
                    }
                    Text(attribution)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .overlay {
            if query.isEmpty, results.isEmpty, library == nil, !key.isEmpty {
                ContentUnavailableView("Find a title for a card", systemImage: "magnifyingglass",
                                       description: Text("Search your library and every streaming service.\n\n\(attribution)"))
            }
        }
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Movie or show")
        .onSubmit(of: .search) { Task { await search() } }
        .navigationDestination(for: Pick.self) { CardOptionsView(pick: $0, key: key) }
    }

    private let attribution = "This product uses the TMDB API but is not endorsed or certified by TMDB. Where-to-watch data from JustWatch. Streaming IDs from Wikidata."

    /// The library copy of a TMDB result, matched by TMDB ID.
    private func libraryMatch(for title: TMDBTitle) -> LibraryItem? {
        library?.items.first { $0.tmdb == String(title.tmdbID) && $0.tmdbKind == title.kind }
    }

    private func search() async {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        searching = true
        defer { searching = false }
        error = nil
        libraryProblem = nil

        async let libraryResult = Result { try await PlayerLibrary.search(text) }
        async let tmdbResult = Result { key.isEmpty ? [] : try await TMDB(key: key).search(text) }
        switch await libraryResult {
        case .success(let found):
            library = found
        case .failure(let failure):
            library = nil
            libraryProblem = failure is URLError
                ? "Couldn't reach the player to search your library. It needs to be on the same Wi-Fi."
                : failure.localizedDescription
        }
        switch await tmdbResult {
        case .success(let found):
            results = found
        case .failure(let failure):
            results = []
            error = failure.localizedDescription
        }
        if error == nil, results.isEmpty, library?.items.isEmpty ?? true {
            error = "Nothing found for \u{201C}\(text)\u{201D}."
        }
    }
}

private extension Result where Failure == Error {
    init(catching body: () async throws -> Success) async {
        do { self = .success(try await body()) } catch { self = .failure(error) }
    }
}

private struct TitleRow: View {
    let title: String
    let detail: [String?]
    let poster: URL?
    var inLibrary = false

    var body: some View {
        HStack(spacing: 12) {
            Poster(url: poster, width: 46)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(detail.compactMap { $0 }.joined(separator: " · "))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if inLibrary {
                    Label("In your library", systemImage: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.green)
                }
            }
        }
    }
}

private struct Poster: View {
    let url: URL?
    let width: CGFloat

    var body: some View {
        AsyncImage(url: url) { image in
            image.resizable().scaledToFill()
        } placeholder: {
            Color.secondary.opacity(0.2)
        }
        .frame(width: width, height: width * 1.5)
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

/// The card records for one title: the user's own server first, then streaming services.
private struct CardOptionsView: View {
    let pick: Pick
    let key: String
    @State private var candidates: [CardCandidate]?
    @State private var providers: [String]?
    @State private var overview = ""
    @State private var problem: String?

    var body: some View {
        List {
            Section {
                HStack(alignment: .top, spacing: 14) {
                    Poster(url: pick.posterURL, width: 80)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(pick.title).font(.title3.bold())
                        Text([pick.kindName, pick.year].compactMap { $0 }.joined(separator: " · "))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Text(overview).font(.footnote).lineLimit(4)
                    }
                }
            }
            if let candidates {
                Section {
                    if candidates.isEmpty {
                        Text("Not in your library, on no streaming service in the US, and no streaming IDs on Wikidata.")
                    }
                    ForEach(candidates) { candidate in
                        CandidateRow(candidate: candidate, records: candidate.records(title: pick.title, kind: pick.kind),
                                     title: pick.title)
                    }
                } header: {
                    Text("Card records")
                } footer: {
                    Text("Write to card sends the title to the player. Then tap a card on the player to save it there.")
                }
                if let problem {
                    Text(problem).font(.footnote).foregroundStyle(.secondary)
                }
                if let providers {
                    Section("TMDB: streams in the US on") {
                        Text(providers.isEmpty ? "No subscription or free service" : providers.joined(separator: ", "))
                    }
                }
            } else {
                ProgressView("Looking up IDs…")
            }
        }
        .navigationTitle(pick.title)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func load() async {
        overview = pick.tmdb?.overview ?? ""
        // A library pick with a TMDB ID can also be looked up on streaming services
        var tmdbTitle = pick.tmdb
        if tmdbTitle == nil, !key.isEmpty, let item = pick.library, let id = item.tmdb.flatMap(Int.init) {
            tmdbTitle = TMDBTitle(kind: item.tmdbKind, tmdbID: id, title: item.title,
                                  year: item.year.map(String.init), posterPath: nil, overview: "")
        }

        var found: [CardCandidate] = []
        if let item = pick.library {
            let server = pick.server ?? "jellyfin"
            found.append(CardCandidate(svc: server, name: "Your \(PlayerLibrary.serverName(server))", contentIDs: [item.id],
                                       available: true, availableText: "In your library"))
        }
        if let tmdbTitle {
            do {
                let lookup = try await CardLookup.candidates(for: tmdbTitle, key: key)
                found += lookup.candidates
                providers = lookup.providers
            } catch {
                problem = "Streaming lookup failed: \(error.localizedDescription)"
            }
        }
        candidates = found
    }
}

private struct CandidateRow: View {
    let candidate: CardCandidate
    let records: [String]
    let title: String
    @State private var writing: String? // The record being written

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(candidate.name).font(.headline)
                Spacer()
                Label(candidate.availableText,
                      systemImage: candidate.available ? "checkmark.circle.fill" : "minus.circle")
                    .font(.caption)
                    .foregroundStyle(candidate.available ? .green : .secondary)
            }
            if !candidate.available {
                Text("Not streaming on \(candidate.name) in the US, so it can't go on a card.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else if candidate.contentIDs.isEmpty {
                Text("No \(candidate.name) ID on Wikidata yet, so this one can't go on a card.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            ForEach(records, id: \.self) { record in
                VStack(alignment: .leading, spacing: 6) {
                    Text(record)
                        .font(.footnote.monospaced())
                        .foregroundStyle(.secondary)
                        .contextMenu {
                            Button("Copy", systemImage: "doc.on.doc") { UIPasteboard.general.string = record }
                        }
                    if candidate.available { // Only services that stream it in the US
                        Button("Write to card", systemImage: "wave.3.right") { writing = record }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.small)
                    }
                }
            }
        }
        .padding(.vertical, 2)
        .sheet(item: $writing) { record in
            WriteCardView(record: record, title: title)
        }
    }
}

extension String: @retroactive Identifiable {
    public var id: String { self }
}
