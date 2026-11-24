import UIKit
import UniformTypeIdentifiers

/// The share sheet entry. It collects the link and text a streaming app shares,
/// then opens NFCMP with them (nfcmp://share?text=…), where the card is built.
final class ShareViewController: UIViewController {
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        Task { await handOff() }
    }

    private func handOff() async {
        var pieces: [String] = []
        for item in (extensionContext?.inputItems as? [NSExtensionItem]) ?? [] {
            if let text = item.attributedContentText?.string, !text.isEmpty { pieces.append(text) }
            for provider in item.attachments ?? [] {
                if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
                   let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL {
                    pieces.append(url.absoluteString)
                } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
                          let text = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String {
                    pieces.append(text)
                }
            }
        }
        var unique: [String] = []
        for piece in pieces where !unique.contains(piece) { unique.append(piece) }

        var components = URLComponents()
        components.scheme = "nfcmp"
        components.host = "share"
        components.queryItems = [URLQueryItem(name: "text", value: unique.joined(separator: " "))]
        if let url = components.url { open(url) }
        extensionContext?.completeRequest(returningItems: nil)
    }

    /// Share extensions can't call UIApplication.shared, but the app object is up the responder chain.
    private func open(_ url: URL) {
        var responder: UIResponder? = self
        while let current = responder {
            if let application = current as? UIApplication {
                application.open(url, options: [:], completionHandler: nil)
                return
            }
            responder = current.next
        }
    }
}
