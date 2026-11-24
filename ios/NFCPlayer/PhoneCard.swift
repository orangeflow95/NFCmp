import CoreNFC

/// What the phone found on a card.
struct ScannedCard: Identifiable {
    let uid: String
    let text: String?

    var id: String { uid }
}

/// Reads and writes cards with the iPhone's own NFC reader.
enum PhoneCard {
    /// False on the simulator and on phones without NFC tag reading.
    static var isAvailable: Bool { NFCTagReaderSession.readingAvailable }

    static func read() async throws -> ScannedCard {
        var card: ScannedCard?
        try await CardSession.run(prompt: "Hold a card near the top of your iPhone.", done: "Card read") { tag in
            card = ScannedCard(uid: tag.uid, text: try await CardMemory.read(tag))
        }
        guard let card else { throw CardError.badResponse }
        return card
    }

    static func write(_ record: String, title: String) async throws {
        try await CardSession.run(prompt: "Hold a card near the top of your iPhone to save \(title).", done: "Card ready") { tag in
            try await CardMemory.write(record, to: tag)
        }
    }
}

/// An NTAG card over Core NFC's raw MIFARE commands, the same ones the PN532 sends.
private struct NTAGCard: CardTag {
    let tag: NFCMiFareTag

    var uid: String { tag.identifier.map { String(format: "%02x", $0) }.joined() }

    func readPages(_ page: UInt8) async throws -> [UInt8] {
        let response = try await tag.sendMiFareCommand(commandPacket: Data([0x30, page]))
        guard response.count == 16 else { throw CardError.badResponse }
        return Array(response)
    }

    func writePage(_ page: UInt8, _ bytes: [UInt8]) async throws {
        // Whether every write landed is settled by CardMemory reading the card back
        _ = try await tag.sendMiFareCommand(commandPacket: Data([0xA2, page] + bytes))
    }

    func isNTAG215() async throws -> Bool {
        let version = try await tag.sendMiFareCommand(commandPacket: Data([0x60])) // GET_VERSION
        return version.count == 8 && version[version.startIndex + 2] == 0x04 && version[version.startIndex + 6] == 0x11
    }
}

/// One scan: shows the system's NFC sheet, runs `work` on the first card found, and closes the sheet.
private final class CardSession: NSObject, NFCTagReaderSessionDelegate {
    private static var current: CardSession? // Keeps the session alive while the sheet is up

    private let prompt: String
    private let done: String
    private let work: (NTAGCard) async throws -> Void
    private var continuation: CheckedContinuation<Void, Error>?

    private init(prompt: String, done: String, work: @escaping (NTAGCard) async throws -> Void,
                 continuation: CheckedContinuation<Void, Error>) {
        self.prompt = prompt
        self.done = done
        self.work = work
        self.continuation = continuation
    }

    @MainActor
    static func run(prompt: String, done: String, work: @escaping (NTAGCard) async throws -> Void) async throws {
        guard current == nil else { throw CancellationError() }
        try await withCheckedThrowingContinuation { continuation in
            let scan = CardSession(prompt: prompt, done: done, work: work, continuation: continuation)
            current = scan
            let session = NFCTagReaderSession(pollingOption: .iso14443, delegate: scan, queue: .main)
            session?.alertMessage = prompt
            session?.begin()
            if session == nil { scan.finish(.failure(CardError.badResponse)) }
        }
    }

    private func finish(_ result: Result<Void, Error>) {
        continuation?.resume(with: result)
        continuation = nil
        Self.current = nil
    }

    func tagReaderSessionDidBecomeActive(_ session: NFCTagReaderSession) {}

    func tagReaderSession(_ session: NFCTagReaderSession, didInvalidateWithError error: Error) {
        let cancelled = (error as? NFCReaderError)?.code == .readerSessionInvalidationErrorUserCanceled
        finish(.failure(cancelled ? CancellationError() : Self.friendly(error)))
    }

    func tagReaderSession(_ session: NFCTagReaderSession, didDetect tags: [NFCTag]) {
        guard tags.count == 1 else {
            session.alertMessage = CardError.severalCards.localizedDescription
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                session.alertMessage = self.prompt
                session.restartPolling()
            }
            return
        }
        guard case .miFare(let tag) = tags[0], tag.mifareFamily == .ultralight else {
            fail(session, CardError.notNTAG)
            return
        }
        Task { @MainActor in
            do {
                try await session.connect(to: tags[0])
                try await work(NTAGCard(tag: tag))
                session.alertMessage = done
                session.invalidate()
                finish(.success(()))
            } catch {
                fail(session, Self.friendly(error))
            }
        }
    }

    private func fail(_ session: NFCTagReaderSession, _ error: Error) {
        session.invalidate(errorMessage: error.localizedDescription)
        finish(.failure(error))
    }

    private static func friendly(_ error: Error) -> Error {
        guard (error as? NFCReaderError)?.code == .readerTransceiveErrorTagConnectionLost else { return error }
        return LostCard()
    }

    private struct LostCard: LocalizedError {
        var errorDescription: String? { "The card moved away. Hold it still and try again." }
    }
}
