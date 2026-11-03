import Foundation

public struct CompanionPreferences {
  public let displayName: String
  public let color: String
  public let background: String
  public let scale: Double
  public let animated: Bool

  public init?(message: [String: Any]) {
    guard let rawName = message["displayName"] as? String,
      let color = message["color"] as? String,
      ["teal", "rose", "butter", "peach", "lilac", "blue"].contains(color),
      let background = message["background"] as? String,
      ["white", "black", "navy"].contains(background),
      let scale = message["scale"] as? Double, scale.isFinite, (0.35...0.95).contains(scale),
      let animated = message["animated"] as? Bool
    else { return nil }
    let name = rawName.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !name.isEmpty, name.count <= 24 else { return nil }
    self.displayName = name
    self.color = color
    self.background = background
    self.scale = scale
    self.animated = animated
  }
}
