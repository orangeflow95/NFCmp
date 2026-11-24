import SwiftUI

/// Paste (or receive from the share sheet) a link from a streaming app, check what was found, write the card.
struct ShareLinkView: View {
    @Environment(\.dismiss) private var dismiss
    @State var text: String
    @State private var kind: TMDBTitle.Kind = .movie
    @State private var title = ""
    @State private var parsed: SharedTitle?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Paste a share link", text: $text, axis: .vertical)
                        .lineLimit(1...4)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    PasteButton(payloadType: String.self) { strings in
                        if let pasted = strings.first { text = pasted }
                    }
                } footer: {
                    Text("In Disney+, Netflix, Hulu and others, open a title, tap Share, then Copy, or share it straight to NFCMP.")
                }

                if let parsed {
                    Section("Found on \(parsed.name)") {
                        TextField("Title", text: $title)
                        if parsed.needsType {
                            Picker("Type", selection: $kind) {
                                Text("Movie").tag(TMDBTitle.Kind.movie)
                                Text("Show").tag(TMDBTitle.Kind.tv)
                            }
                            .pickerStyle(.segmented)
                        }
                    }
                    if let warning = parsed.warning {
                        Section {
                            Label(warning, systemImage: "exclamationmark.triangle.fill")
                                .font(.footnote)
                                .foregroundStyle(.orange)
                        }
                    }
                    Section {
                        CandidateRow(candidate: CardCandidate(svc: parsed.svc, name: parsed.name, contentIDs: [parsed.contentID],
                                                              available: true, availableText: "From your link"),
                                     records: CardCandidate(svc: parsed.svc, name: parsed.name, contentIDs: [parsed.contentID],
                                                            available: true, availableText: "")
                                         .records(title: displayTitle, kind: kind),
                                     title: displayTitle)
                    } header: {
                        Text("Card record")
                    } footer: {
                        Text("The link's ID goes on the card as is. Whether the TV opens the title depends on the app's deep-link support, so tap the card once to check.")
                    }
                } else if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Section {
                        Text(ShareLinkParser.problem(for: text)).foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Share link")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .onAppear { reparse() }
            .onChange(of: text) { reparse() }
        }
    }

    private var displayTitle: String {
        let trimmed = title.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? "Untitled" : trimmed
    }

    private func reparse() {
        let found = ShareLinkParser.parse(text)
        if found?.contentID != parsed?.contentID || found?.svc != parsed?.svc {
            title = found?.title ?? ""
            kind = found?.kind ?? .movie
        }
        parsed = found
    }
}
