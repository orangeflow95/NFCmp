import XCTest

/// Walks through the app and saves screenshots for the README (docs/images/app-*.png).
/// Run with TEST_RUNNER_PLAYER_ADDRESS (a test board's page) and TEST_RUNNER_TMDB_KEY set;
/// a simulated card must be tapped on the test board while the write screen waits.
final class ScreenshotTests: XCTestCase {
    func testReadmeScreenshots() throws {
        let env = ProcessInfo.processInfo.environment
        let app = XCUIApplication()
        app.launchArguments += ["-playerAddress", env["PLAYER_ADDRESS"] ?? "", "-tmdbKey", env["TMDB_KEY"] ?? ""]
        app.launch()

        XCTAssertTrue(app.staticTexts["Online"].waitForExistence(timeout: 10))
        snap(app, "app-home")

        let search = app.searchFields.firstMatch
        search.tap()
        search.typeText("frozen\n")
        XCTAssertTrue(app.staticTexts["In your Jellyfin"].waitForExistence(timeout: 15))
        sleep(2) // Let the posters load
        snap(app, "app-results")

        app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Frozen, Movie · 2013'")).firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Your Jellyfin"].waitForExistence(timeout: 20))
        sleep(2)
        snap(app, "app-card-options")

        app.buttons["Write to card"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Tap a card on the player"].waitForExistence(timeout: 10))
        snap(app, "app-write-waiting")

        XCTAssertTrue(app.staticTexts["Card ready"].waitForExistence(timeout: 60))
        snap(app, "app-write-done")
    }

    /// The board's setup page in Safari (docs/images/setup-*.png). Needs TEST_RUNNER_PORTAL_URL;
    /// TEST_RUNNER_SHOT names the screenshot, taken after scrolling down when TEST_RUNNER_SCROLL is set.
    func testSetupPageScreenshots() throws {
        let env = ProcessInfo.processInfo.environment
        guard let address = env["PORTAL_URL"], let url = URL(string: address) else {
            throw XCTSkip("Set TEST_RUNNER_PORTAL_URL to a running setup page")
        }
        let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        XCUIDevice.shared.system.open(url)
        XCTAssertTrue(safari.staticTexts["Set up your movie player"].waitForExistence(timeout: 15))
        let close = safari.buttons["Close"]
        if close.waitForExistence(timeout: 3) { close.tap() } // Safari's first-run tip

        let ssid = safari.textFields["Wi-Fi name"]
        if (ssid.value as? String ?? "").isEmpty || ssid.value as? String == "Wi-Fi name" {
            ssid.tap()
            ssid.typeText("BrownHouse")
            safari.staticTexts["Set up your movie player"].tap() // Close the keyboard
        }
        if env["SCROLL"] != nil {
            safari.swipeUp()
            sleep(1)
        }
        snap(safari, env["SHOT"] ?? "setup")
    }

    private func snap(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }
}
