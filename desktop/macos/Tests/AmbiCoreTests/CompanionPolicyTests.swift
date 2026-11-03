import XCTest

@testable import AmbiCore

final class CompanionPolicyTests: XCTestCase {
  func testOnlyExactLocalServiceCanNavigate() {
    XCTAssertTrue(
      CompanionPolicy.allowsNavigation(URL(string: "http://127.0.0.1:8765/companion.html")!))
    for value in [
      "https://example.com", "http://127.0.0.1:8888", "http://localhost:8765",
      "file:///tmp/index.html", "http://user@127.0.0.1:8765",
    ] {
      XCTAssertFalse(CompanionPolicy.allowsNavigation(URL(string: value)!), value)
    }
  }

  func testVoiceKeySetupRequiresAnIdleOwnedService() {
    func allowed(_ owned: Bool = true, _ connected: Bool = true, _ status: String = "idle", _ job: Bool = false) -> Bool {
      CompanionPolicy.canConfigureVoice(serviceOwned: owned, connected: connected, status: status, jobRunning: job)
    }
    XCTAssertTrue(allowed())
    XCTAssertTrue(allowed(true, true, "error"))
    XCTAssertTrue(allowed(false, false, "offline"))
    XCTAssertFalse(allowed(false, true)) // Never restart another process's listener.
    XCTAssertFalse(allowed(true, false)) // Wait for the owned service's snapshot.
    XCTAssertFalse(allowed(true, true, "idle", true)) // Includes approval-paused tasks.
    for status in ["connected", "connecting", "stopping", "unknown"] {
      XCTAssertFalse(allowed(true, true, status))
    }
  }

  func testCommandsEncodeUntrustedSuggestionIDsAsData() throws {
    let id = "');window.evil=true;//\n\""
    let call = CompanionPolicy.javascriptCall("command", arguments: ["accept", id])
    let prefix = "window.ambiDesktop?.command(..."
    XCTAssertTrue(call.hasPrefix(prefix))
    let encoded = String(call.dropFirst(prefix.count).dropLast())
    let decoded = try JSONSerialization.jsonObject(with: Data(encoded.utf8)) as? [String]
    XCTAssertEqual(decoded, ["accept", id])
  }
}
