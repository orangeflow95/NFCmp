import Foundation

// What a card holds: one NDEF text record with versioned key=value pairs, e.g.
//   v1;svc=netflix;type=show;id=81591296;t=Nobody Wants This
// The Swift twin of the board's card.py. Keep the two in step, so a card written
// by the phone plays on the player and a card written by the player reads here.

/// The card in reach, as NTAG pages of 4 bytes. PhoneCard provides the real one.
protocol CardTag {
    /// Four pages starting at `page` (16 bytes).
    func readPages(_ page: UInt8) async throws -> [UInt8]
    func writePage(_ page: UInt8, _ bytes: [UInt8]) async throws
    func isNTAG215() async throws -> Bool
}

enum CardError: LocalizedError {
    case notFormatted, tooSmall, tooLong, notVerified, badResponse, notNTAG, severalCards

    var errorDescription: String? {
        switch self {
        case .notFormatted: return "This card isn't NDEF-formatted. Use an NTAG215 card."
        case .tooSmall: return "The record doesn't fit on this card. Use an NTAG215."
        case .tooLong: return "This title is too long for one card."
        case .notVerified: return "The card didn't read back what was written. Try again."
        case .badResponse: return "The card didn't answer properly. Try again."
        case .notNTAG: return "That isn't an NTAG card. Use an NTAG215."
        case .severalCards: return "More than one card is in range."
        }
    }
}

/// A v1 card record's fields, and whether the player can play them.
struct CardRecord {
    let fields: [String: String]

    /// Each service the player knows (config.SERVICES) and whether its deep link needs a type.
    private static let services: [String: (name: String, needsType: Bool)] = [
        "netflix": ("Netflix", true), "jellyfin": ("Jellyfin", false), "plex": ("Plex", true),
        "disney": ("Disney+", true), "hulu": ("Hulu", true), "prime": ("Prime Video", true),
        "appletv": ("Apple TV", true), "max": ("Max", true), "youtube": ("YouTube", false),
    ]

    init?(text: String) {
        let parts = text.components(separatedBy: ";")
        guard parts[0] == "v1" else { return nil }
        var fields: [String: String] = [:]
        for part in parts.dropFirst() {
            let pair = part.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            if let key = pair.first, !key.isEmpty {
                fields[String(key)] = pair.count > 1 ? String(pair[1]) : ""
            }
        }
        guard fields["svc"]?.isEmpty == false, fields["id"]?.isEmpty == false else { return nil }
        self.fields = fields
    }

    var service: String { fields["svc"] ?? "" }
    var serviceName: String { Self.services[service]?.name ?? service }
    var contentID: String { fields["id"] ?? "" }
    var title: String? { fields["t"].flatMap { $0.isEmpty ? nil : $0 } }
    var kindName: String? {
        switch fields["type"] {
        case "movie": return "Movie"
        case "show": return "Show"
        case "episode": return "Episode"
        default: return nil
        }
    }

    /// Why the player can't play this record, or nil.
    var problem: String? {
        guard let known = Self.services[service] else { return "The player doesn't know the service \u{201C}\(service)\u{201D}." }
        return known.needsType && fields["type"]?.isEmpty != false ? "The \(service) record is missing its type." : nil
    }
}

enum CardMemory {
    static let firstPage: UInt8 = 4
    static let maxBytes = 512 // NTAG215 has 504 bytes of user memory
    static let blankCC: [UInt8] = [0xE1, 0x10, 0x3E, 0x00] // Capability container of a blank, NDEF-formatted NTAG215

    enum Decoded: Equatable {
        case more
        case done(String?)
    }

    /// The bytes for user memory: an NDEF message TLV holding one text record, then the terminator.
    static func encode(_ text: String) throws -> [UInt8] {
        let payload = [0x02] + Array("en".utf8) + Array(text.utf8) // Status byte (UTF-8, 2-letter language), language, text
        guard payload.count <= 250 else { throw CardError.tooLong }
        let record = [0xD1, 1, UInt8(payload.count), UInt8(ascii: "T")] + payload // Short well-known record, type "T"
        return [0x03, UInt8(record.count)] + record + [0xFE]
    }

    /// Walks the TLVs in `memory`. `.more` means more memory has to be read first.
    static func decode(_ memory: [UInt8]) -> Decoded {
        var i = 0
        while i < memory.count {
            let tag = memory[i]
            if tag == 0x00 { // Padding
                i += 1
                continue
            }
            if tag == 0xFE { return .done(nil) } // Terminator: no NDEF message
            if i + 2 > memory.count { return .more }
            var length = Int(memory[i + 1])
            var start = i + 2
            if length == 0xFF { // 3-byte length form
                if i + 4 > memory.count { return .more }
                length = Int(memory[i + 2]) << 8 | Int(memory[i + 3])
                start = i + 4
            }
            if start + length > memory.count {
                return start + length <= maxBytes ? .more : .done(nil)
            }
            if tag == 0x03 { return .done(text(in: Array(memory[start..<start + length]))) }
            i = start + length // Skip lock and memory control TLVs
        }
        return .more
    }

    /// The text of the message's first record if it's an NDEF text record, else nil.
    private static func text(in message: [UInt8]) -> String? {
        guard message.count >= 3 else { return nil }
        let header = message[0]
        let typeLength = Int(message[1])
        var payloadLength: Int
        var i: Int
        if header & 0x10 != 0 { // Short record: 1-byte payload length
            payloadLength = Int(message[2])
            i = 3
        } else {
            guard message.count >= 6 else { return nil }
            payloadLength = message[2..<6].reduce(0) { $0 << 8 | Int($1) }
            i = 6
        }
        var idLength = 0
        if header & 0x08 != 0 {
            guard i < message.count else { return nil }
            idLength = Int(message[i])
            i += 1
        }
        guard header & 0x07 == 1, i + typeLength <= message.count, message[i..<i + typeLength].elementsEqual([UInt8(ascii: "T")]) else { return nil }
        i += typeLength + idLength
        guard i < message.count else { return nil }
        payloadLength = min(payloadLength, message.count - i)
        let payload = message[i..<i + payloadLength]
        guard let status = payload.first else { return nil }
        return String(bytes: payload.dropFirst(1 + Int(status & 0x3F)), encoding: .utf8)
    }

    /// The text record on the card, or nil (blank, or not an NDEF text record).
    static func read(_ tag: CardTag) async throws -> String? {
        let cc = try await tag.readPages(3)
        guard cc.first == 0xE1 else { return nil }
        // Stops at the card's own size, so a small card isn't read past its last page
        let capacity = min(Int(cc[2]) * 8, maxBytes)
        var memory: [UInt8] = []
        while memory.count < capacity {
            memory += try await tag.readPages(firstPage + UInt8(memory.count / 4))
            if case .done(let text) = decode(Array(memory.prefix(capacity))) { return text }
        }
        return nil
    }

    /// Writes `text` to the card as its only record, then reads it back to check.
    ///
    /// The first page is blanked first and written last, so a card pulled away
    /// halfway reads as blank rather than as half a record.
    static func write(_ text: String, to tag: CardTag) async throws {
        var cc = Array(try await tag.readPages(3).prefix(4))
        if cc[0] != 0xE1 {
            // The capability container can't be changed once set, so format only a card known to be this size
            guard cc.allSatisfy({ $0 == 0 }), try await tag.isNTAG215() else { throw CardError.notFormatted }
            try await tag.writePage(3, blankCC)
            cc = blankCC
        }
        var data = try encode(text)
        data += [UInt8](repeating: 0, count: (4 - data.count % 4) % 4)
        guard data.count <= Int(cc[2]) * 8 else { throw CardError.tooSmall }
        try await tag.writePage(firstPage, [0x03, 0x00, 0xFE, 0x00]) // Empty NDEF message while writing
        for offset in stride(from: 4, to: data.count, by: 4) {
            try await tag.writePage(firstPage + UInt8(offset / 4), Array(data[offset..<offset + 4]))
        }
        try await tag.writePage(firstPage, Array(data[0..<4]))
        guard try await read(tag) == text else { throw CardError.notVerified }
    }
}
