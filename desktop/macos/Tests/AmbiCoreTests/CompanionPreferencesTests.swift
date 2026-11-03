import XCTest

@testable import AmbiCore

final class CompanionPreferencesTests: XCTestCase {
  private var message: [String: Any] {
    [
      "displayName": "  Milo  ", "color": "rose", "background": "black", "scale": 0.65,
      "animated": false,
    ]
  }

  func testValidPreferencesPreserveChoiceAndTrimName() {
    let value = CompanionPreferences(message: message)
    XCTAssertEqual(value?.displayName, "Milo")
    XCTAssertEqual(value?.animated, false)
    XCTAssertEqual(value?.scale, 0.65)
  }

  func testNavyBackgroundCanBeSaved() {
    var input = message
    input["background"] = "navy"
    input["color"] = "blue"
    XCTAssertEqual(CompanionPreferences(message: input)?.background, "navy")
  }

  func testInvalidWebMessagesAreRejectedBeforePersistence() {
    for (key, invalid) in [
      ("displayName", "" as Any), ("color", "invalid"), ("scale", Double.nan), ("scale", 2.0),
      ("background", "red"),
    ] {
      var value = message
      value[key] = invalid
      XCTAssertNil(CompanionPreferences(message: value), key)
    }
  }
}
