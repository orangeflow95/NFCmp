import SwiftUI

/// What the phone read from a card.
struct ReadCardView: View {
    let card: ScannedCard
    @Environment(\.dismiss) private var dismiss

    private var record: CardRecord? { card.text.flatMap(CardRecord.init(text:)) }

    var body: some View {
        NavigationStack {
            List {
                if let record {
                    Section {
                        Text(record.title ?? "Untitled").font(.title3.bold())
                        LabeledContent("Service", value: record.serviceName)
                        if let kind = record.kindName {
                            LabeledContent("Type", value: kind)
                        }
                        LabeledContent("ID", value: record.contentID)
                    } footer: {
                        if let problem = record.problem {
                            Text(problem).foregroundStyle(.orange)
                        }
                    }
                } else if let text = card.text {
                    Section {
                        Text(text).font(.footnote.monospaced())
                    } header: {
                        Text("Not a movie card")
                    } footer: {
                        Text("This card holds text the player doesn't understand.")
                    }
                } else {
                    Section {
                        ContentUnavailableView("No movie on this card", systemImage: "wave.3.right.circle",
                                               description: Text("It's blank, or holds something other than a movie card record. Search for a title to write one."))
                    }
                }
                Section {
                    if let text = card.text, record != nil {
                        Text(text).font(.footnote.monospaced()).foregroundStyle(.secondary)
                    }
                    LabeledContent("Card UID", value: card.uid)
                }
            }
            .navigationTitle("Card")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
