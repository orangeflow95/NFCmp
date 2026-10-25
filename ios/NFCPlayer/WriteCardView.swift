import SwiftUI

/// Sends a card record to the player and waits while the next card tapped on it is written.
struct WriteCardView: View {
    let record: String
    let title: String
    @Environment(\.dismiss) private var dismiss
    @State private var state: CardWriter.State?
    @State private var problem: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Spacer()
                switch state?.state {
                case "written":
                    Image(systemName: "checkmark.circle.fill").font(.system(size: 64)).foregroundStyle(.green)
                    Text("Card ready").font(.title2.bold())
                    Text("Tap it on the player any time to play \(state?.title ?? title).")
                case "waiting":
                    Image(systemName: "wave.3.right.circle").font(.system(size: 64)).foregroundStyle(.tint)
                        .symbolEffect(.pulse)
                    Text("Tap a card on the player").font(.title2.bold())
                    Text("Hold it still for a second while \(state?.title ?? title) is written.")
                    if let error = state?.error {
                        Text(error).foregroundStyle(.orange)
                    }
                case "expired":
                    Image(systemName: "clock.badge.xmark").font(.system(size: 64)).foregroundStyle(.secondary)
                    Text("No card was tapped").font(.title2.bold())
                    Button("Try again") { Task { await run() } }.buttonStyle(.borderedProminent)
                case "failed":
                    Image(systemName: "xmark.octagon.fill").font(.system(size: 64)).foregroundStyle(.red)
                    Text("Couldn't write the card").font(.title2.bold())
                    Text(state?.error ?? "")
                default:
                    if let problem {
                        Image(systemName: "wifi.exclamationmark").font(.system(size: 64)).foregroundStyle(.orange)
                        Text("Couldn't reach the player").font(.title2.bold())
                        Text(problem)
                        Button("Try again") { Task { await run() } }.buttonStyle(.borderedProminent)
                    } else {
                        ProgressView("Sending to the player…")
                    }
                }
                Spacer()
                Text(record).font(.caption.monospaced()).foregroundStyle(.secondary)
            }
            .multilineTextAlignment(.center)
            .padding()
            .navigationTitle("Write to card")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    if state?.state == "written" {
                        Button("Done") { dismiss() }
                    }
                }
                ToolbarItem(placement: .cancellationAction) {
                    if state?.state != "written" {
                        Button("Cancel") {
                            Task { await CardWriter.cancel() }
                            dismiss()
                        }
                    }
                }
            }
        }
        .task { await run() }
    }

    /// Sends the record, then checks every second until the card is written or the wait ends.
    private func run() async {
        problem = nil
        state = nil
        do {
            state = try await CardWriter.start(record: record)
            while state?.state == "waiting", !Task.isCancelled {
                try await Task.sleep(for: .seconds(1))
                state = try await CardWriter.status()
            }
        } catch is CancellationError {
        } catch {
            problem = "Make sure your phone is on the same Wi-Fi as the player. (\(error.localizedDescription))"
        }
    }
}
