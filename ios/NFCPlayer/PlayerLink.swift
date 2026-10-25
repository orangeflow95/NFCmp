import CoreBluetooth
import Foundation

/// Something the player reported over Bluetooth. Matches the events in phone.py.
struct PlayerEvent: Equatable {
    enum Kind: String {
        case learn   // A blank card was tapped
        case link    // Something is playing in an app that needs a pasted link
        case locked  // The card was linked
        case idle    // Learn mode ended without linking
    }

    let kind: Kind
    let detail: String?

    init?(_ text: String) {
        let parts = text.split(separator: "|", maxSplits: 1).map(String.init)
        guard let first = parts.first, let kind = Kind(rawValue: first) else { return nil }
        self.kind = kind
        detail = parts.count > 1 ? parts[1] : nil
    }
}

/// Bluetooth LE connection to the NFC player.
///
/// iOS keeps the connection alive in the background (the bluetooth-central
/// background mode) and relaunches the app for player events, as long as the
/// app wasn't force-quit. A pending connect never times out, so when the phone
/// leaves the house it reconnects on its own once it's back in range.
final class PlayerLink: NSObject, ObservableObject {
    enum Status {
        case bluetoothOff, searching, outOfRange, connected
    }

    static let shared = PlayerLink()

    static let serviceUUID = CBUUID(string: "512CFDB7-839A-4A3C-9E7D-A94A96583B77")
    static let pageUUID = CBUUID(string: "2B62B7DB-9E60-4101-A213-9914AA996FB4")
    static let eventUUID = CBUUID(string: "9B4F083C-41E6-4022-81F7-CE5C85C6A004")
    private static let restoreID = "NFCPlayerCentral"
    private static let playerKey = "playerIdentifier"
    private static let pageKey = "playerPageURL"

    @Published private(set) var status = Status.searching
    @Published private(set) var pageURL = UserDefaults.standard.url(forKey: pageKey)
    /// Bumped whenever the page should reload: a new event, or a notification was opened.
    @Published private(set) var pageVersion = 0

    var onEvent: ((PlayerEvent) -> Void)?

    private var central: CBCentralManager?
    private var player: CBPeripheral?

    private override init() {
        super.init()
        #if DEBUG
        if let page = Self.demoPage {
            startDemo(page: page)
            return
        }
        #endif
        central = CBCentralManager(delegate: self, queue: nil,
                                   options: [CBCentralManagerOptionRestoreIdentifierKey: Self.restoreID])
    }

    func reloadPage() {
        pageVersion += 1
    }

    /// Drops the saved player and looks for one again.
    func forgetPlayer() {
        if let player { central?.cancelPeripheralConnection(player) }
        player = nil
        UserDefaults.standard.removeObject(forKey: Self.playerKey)
        UserDefaults.standard.removeObject(forKey: Self.pageKey)
        pageURL = nil
        connectOrSearch()
    }

    private func connectOrSearch() {
        guard let central, central.state == .poweredOn else { return }
        if player == nil,
           let saved = UserDefaults.standard.string(forKey: Self.playerKey).flatMap(UUID.init(uuidString:)) {
            player = central.retrievePeripherals(withIdentifiers: [saved]).first
            player?.delegate = self
        }
        if let player {
            if player.state == .connected {
                status = .connected
                player.discoverServices([Self.serviceUUID])
            } else {
                status = .outOfRange
                central.connect(player)
            }
        } else {
            status = .searching
            central.scanForPeripherals(withServices: [Self.serviceUUID])
        }
    }
}

#if DEBUG
extension PlayerLink {
    /// Simulator demo (the simulator has no Bluetooth): launch with `-demoPage <url>`
    /// to fake a connected player and one learn-mode run.
    fileprivate static var demoPage: URL? {
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-demoPage"), i + 1 < args.count else { return nil }
        return URL(string: args[i + 1])
    }

    fileprivate func startDemo(page: URL) {
        status = .connected
        pageURL = page
        for (delay, text) in [(8.0, "learn"), (16.0, "link|Netflix")] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self, let event = PlayerEvent(text) else { return }
                reloadPage()
                onEvent?(event)
            }
        }
    }
}
#endif

extension PlayerLink: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if central.state == .poweredOn {
            connectOrSearch()
        } else {
            status = .bluetoothOff
        }
    }

    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String: Any]) {
        // iOS relaunched the app in the background: pick up the connection it kept
        let restored = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral]
        player = restored?.first
        player?.delegate = self
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        central.stopScan()
        player = peripheral
        peripheral.delegate = self
        UserDefaults.standard.set(peripheral.identifier.uuidString, forKey: Self.playerKey)
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        status = .connected
        peripheral.discoverServices([Self.serviceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        status = .outOfRange
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard peripheral == player else { return }
        status = .outOfRange
        central.connect(peripheral) // Waits until the player is back in range
    }
}

extension PlayerLink: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let service = peripheral.services?.first(where: { $0.uuid == Self.serviceUUID }) else { return }
        peripheral.discoverCharacteristics([Self.pageUUID, Self.eventUUID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        for characteristic in service.characteristics ?? [] {
            if characteristic.uuid == Self.pageUUID {
                peripheral.readValue(for: characteristic)
            } else if characteristic.uuid == Self.eventUUID {
                // Only notifications, not a read: reading would replay an old event as a new alert
                peripheral.setNotifyValue(true, for: characteristic)
            }
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard let data = characteristic.value else { return }
        let text = String(decoding: data, as: UTF8.self)
        if characteristic.uuid == Self.pageUUID, let url = URL(string: text) {
            if url != pageURL {
                pageURL = url
                UserDefaults.standard.set(url, forKey: Self.pageKey)
            }
        } else if characteristic.uuid == Self.eventUUID, let event = PlayerEvent(text) {
            reloadPage()
            onEvent?(event)
        }
    }
}
