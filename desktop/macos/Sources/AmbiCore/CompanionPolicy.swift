import Foundation

public enum CompanionPolicy {
  public static let baseURL = URL(string: "http://127.0.0.1:8765")!

  // API setup may restart only an idle service owned by this app.
  public static func canConfigureVoice(serviceOwned: Bool, connected: Bool, status: String, jobRunning: Bool) -> Bool {
    guard !jobRunning else { return false }
    if !serviceOwned && !connected { return ["offline", "idle", "error"].contains(status) }
    return serviceOwned && connected && ["idle", "error"].contains(status)
  }

  public static func allowsNavigation(_ url: URL) -> Bool {
    url.scheme == "http" && url.host == "127.0.0.1" && url.port == 8765
      && url.user == nil && url.password == nil
  }

  public static func javascriptCall(_ method: String, arguments: [Any] = []) -> String {
    precondition(
      [
        "appearance", "screenContext", "command", "showActivity", "configure", "showSetup",
        "showConnections", "selectWorkspace",
      ].contains(
        method))
    let data = try! JSONSerialization.data(withJSONObject: arguments, options: [.fragmentsAllowed])
    return "window.ambiDesktop?.\(method)(...\(String(decoding: data, as: UTF8.self)))"
  }
}
