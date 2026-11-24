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

        XCTAssertTrue(app.descendants(matching: .any)["Online"].firstMatch.waitForExistence(timeout: 10)) // The badge is a button now
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

    /// Setting up the player in the app (docs/images/app-setup-*.png), against a test board that has
    /// no TV chosen yet and can find a Roku. Needs TEST_RUNNER_PLAYER_ADDRESS. With TEST_RUNNER_PAIR_CODE_FILE
    /// (where a fake Google TV at TEST_RUNNER_FAKE_TV_IP writes the code it shows), it also pairs.
    func testPlayerSetupScreenshots() throws {
        let env = ProcessInfo.processInfo.environment
        let app = XCUIApplication()
        app.launchArguments += ["-playerAddress", env["PLAYER_ADDRESS"] ?? ""]
        app.launch()

        // Setup opens by itself while the player has no TV
        let choose = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Choose your TV'")).firstMatch
        XCTAssertTrue(choose.waitForExistence(timeout: 15))
        snap(app, "app-setup-start")
        choose.tap()

        let roku = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Roku ·'")).firstMatch
        XCTAssertTrue(roku.waitForExistence(timeout: 30))
        snap(app, "app-setup-tvs")
        roku.tap()
        XCTAssertTrue(app.buttons["Turn on the TV"].waitForExistence(timeout: 15))
        snap(app, "app-setup-ready")

        guard let codeFile = env["PAIR_CODE_FILE"], let fakeTV = env["FAKE_TV_IP"] else { return }
        app.buttons.matching(NSPredicate(format: "label CONTAINS 'Roku'")).firstMatch.tap()
        app.swipeUp()
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Type'")).firstMatch.tap()
        app.buttons["Google TV"].firstMatch.tap()
        let ip = app.textFields.matching(NSPredicate(format: "placeholderValue BEGINSWITH 'IP address'")).firstMatch
        ip.tap()
        ip.typeText(fakeTV)
        app.buttons["Use this TV"].tap()
        let show = app.buttons["Show code on TV"]
        XCTAssertTrue(show.waitForExistence(timeout: 30))
        snap(app, "app-pair-start")
        try? FileManager.default.removeItem(atPath: codeFile)
        show.tap()
        XCTAssertTrue(app.staticTexts["Enter the code on the TV"].waitForExistence(timeout: 20))
        var code = ""
        for _ in 0..<20 where code.isEmpty {
            code = (try? String(contentsOfFile: codeFile, encoding: .utf8)) ?? ""
            if code.isEmpty { sleep(1) }
        }
        app.textFields.firstMatch.typeText(code)
        snap(app, "app-pair-code")
        app.buttons["Pair"].tap()
        XCTAssertTrue(app.staticTexts["Paired"].waitForExistence(timeout: 20))
        snap(app, "app-pair-done")
        app.buttons["Done"].firstMatch.tap()
        XCTAssertTrue(app.buttons["Turn on the TV"].waitForExistence(timeout: 10)) // Back on the player settings
        snap(app, "app-setup-paired")
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
        XCTAssertTrue(safari.staticTexts["Connect your movie player"].waitForExistence(timeout: 15))
        let close = safari.buttons["Close"]
        if close.waitForExistence(timeout: 3) { close.tap() } // Safari's first-run tip

        let ssid = safari.textFields["Wi-Fi name"]
        if (ssid.value as? String ?? "").isEmpty || ssid.value as? String == "Wi-Fi name" {
            ssid.tap()
            ssid.typeText("BrownHouse")
            safari.staticTexts["Connect your movie player"].tap() // Close the keyboard
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
