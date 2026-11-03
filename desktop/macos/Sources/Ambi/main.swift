import AmbiCore
import AppKit
import ApplicationServices
import CoreGraphics
import ScreenCaptureKit
import WebKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate,
  WKScriptMessageHandler, NSMenuDelegate, NSWindowDelegate
{
  private var window: NSWindow!
  private var web: WKWebView!
  private var state: [String: Any] = [:]
  private var service: Process?
  private var serviceLog: FileHandle?
  private var ownsSession = false
  private var ownsJob = false
  private var ownedJobClientId = ""
  private var startingService = false
  private var requestingScreenAccess = false
  private var configuringVoice = false
  private var launchKey: String?
  private var attemptedAutoStart = false
  private var quitting = false
  private var activityExpanded = false
  private var compactFrame: NSRect?
  private var frameBeforeSetup: NSRect?
  private var lastError = ""
  private let screenFrame = ScreenFrame()
  private var characterIcon: NSImage?
  private let defaults = UserDefaults.standard
  private let sessionItem = NSMenuItem(
    title: "Start Session", action: #selector(toggleSession), keyEquivalent: "s")
  private let statusItem = NSMenuItem(
    title: "Connecting to local Ambi…", action: nil, keyEquivalent: "")
  private let taskItem = NSMenuItem(
    title: "Stop Computer Task", action: #selector(stopTask), keyEquivalent: ".")
  private let microphoneItem = NSMenuItem(
    title: "Mute Microphone", action: #selector(toggleMicrophone), keyEquivalent: "m")
  private let focusItem = NSMenuItem(
    title: "Focus Mode", action: #selector(toggleFocus), keyEquivalent: "f")
  private let suggestionItem = NSMenuItem(
    title: "Review Suggestion…", action: #selector(reviewSuggestion), keyEquivalent: "r")
  private let screenItem = NSMenuItem(
    title: "Include Screen Context (Next Session)", action: #selector(toggleScreen),
    keyEquivalent: "")

  func applicationDidFinishLaunching(_ notification: Notification) {
    defaults.register(defaults: [
      "background": "navy", "characterScale": 0.78, "screenContext": false, "alwaysOnTop": false,
      "displayName": "Ambi", "characterColor": "blue", "characterAnimated": true,
      "hasCompletedSetup": false,
    ])
    createMenu()
    characterIcon = NSImage(
      contentsOf: Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/Ambi.icns"))
    if let characterIcon { NSApp.applicationIconImage = characterIcon }
    screenFrame.stop = { [weak self] in self?.stopTask() }
    let controller = WKUserContentController()
    controller.add(self, name: "ambi")
    let config = WKWebViewConfiguration()
    config.userContentController = controller
    config.websiteDataStore = .nonPersistent()
    web = WKWebView(frame: .zero, configuration: config)
    web.navigationDelegate = self
    web.underPageBackgroundColor = backgroundColor
    web.setValue(false, forKey: "drawsBackground")
    window = NSWindow(
      contentRect: NSRect(x: 0, y: 0, width: 560, height: 600),
      styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
      backing: .buffered, defer: false)
    window.title = "Ambi"
    window.delegate = self
    window.titleVisibility = .hidden
    window.titlebarAppearsTransparent = true
    window.isMovableByWindowBackground = true
    window.minSize = NSSize(width: 360, height: 440)
    window.backgroundColor = backgroundColor
    window.level = defaults.bool(forKey: "alwaysOnTop") ? .floating : .normal
    window.contentView = web
    window.setFrameAutosaveName("AmbiCompanion")
    window.center()
    window.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
    reload()
  }

  private var backgroundColor: NSColor {
    switch defaults.string(forKey: "background") {
    case "black": return .black
    case "white": return .white
    default: return NSColor(srgbRed: 13 / 255.0, green: 27 / 255.0, blue: 42 / 255.0, alpha: 1)
    }
  }

  private func createMenu() {
    let bar = NSMenu()
    NSApp.mainMenu = bar
    func addMenu(_ title: String) -> NSMenu {
      let root = NSMenuItem(title: title, action: nil, keyEquivalent: "")
      let menu = NSMenu(title: title)
      menu.autoenablesItems = false
      menu.delegate = self
      root.submenu = menu
      bar.addItem(root)
      return menu
    }
    let app = addMenu("Ambi")
    app.addItem(withTitle: "About Ambi", action: #selector(about), keyEquivalent: "")
    app.addItem(withTitle: "Customize Ambi…", action: #selector(showSetup), keyEquivalent: ",")
      .target = self
    app.addItem(.separator())
    app.addItem(
      withTitle: "Quit Ambi", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    let edit = addMenu("Edit")
    edit.autoenablesItems = true
    edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
    edit.addItem(.separator())
    edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
    edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
    edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
    edit.addItem(
      withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
    let session = addMenu("Session")
    for item in [
      statusItem, .separator(), sessionItem, taskItem, .separator(), microphoneItem, focusItem,
      screenItem, .separator(), suggestionItem,
    ] {
      item.target = self
      session.addItem(item)
    }
    let view = addMenu("View")
    for (title, key, tag, action) in [
      ("White Background", "", 0, #selector(setBackground(_:))),
      ("Black Background", "", 1, #selector(setBackground(_:))),
      ("Navy Background", "", 3, #selector(setBackground(_:))),
      ("Small Window", "1", 260, #selector(setSize(_:))),
      ("Medium Window", "2", 480, #selector(setSize(_:))),
      ("Large Window", "3", 720, #selector(setSize(_:))),
      ("Smaller Character", "-", -1, #selector(scaleCharacter(_:))),
      ("Larger Character", "+", 1, #selector(scaleCharacter(_:))),
      ("Always on Top", "", 2, #selector(toggleTop(_:))),
    ] {
      let item = view.addItem(withTitle: title, action: action, keyEquivalent: key)
      item.tag = tag
      item.target = self
    }
    view.addItem(
      withTitle: "Show or Hide Activity", action: #selector(toggleActivity), keyEquivalent: "d"
    ).target = self
    view.addItem(
      withTitle: "Preview Whole-Screen Frame", action: #selector(previewScreenFrame),
      keyEquivalent: ""
    ).target = self
    let connection = addMenu("Connection")
    connection.addItem(
      withTitle: "Setup & Connections…", action: #selector(showConnections), keyEquivalent: ""
    ).target = self
    connection.addItem(
      withTitle: "Configure API Key for This Launch…", action: #selector(configureAPIKey),
      keyEquivalent: ""
    ).target = self
    connection.addItem(
      withTitle: "Check for Updates…", action: #selector(checkUpdates), keyEquivalent: ""
    ).target = self
    connection.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "l").target =
      self
    connection.addItem(
      withTitle: "Start Local Service", action: #selector(startService), keyEquivalent: ""
    ).target = self
    connection.addItem(
      withTitle: "Open Full Controls in Browser", action: #selector(openControls),
      keyEquivalent: "o"
    ).target = self
    connection.addItem(
      withTitle: "Show Connection Details…", action: #selector(showDetails), keyEquivalent: ""
    ).target = self
  }

  func menuWillOpen(_ menu: NSMenu) {
    for item in menu.items {
      if item.action == #selector(setBackground(_:)) {
        item.state =
          ([0: "white", 1: "black", 3: "navy"][item.tag] == defaults.string(forKey: "background"))
          ? .on : .off
      }
      if item.action == #selector(toggleTop(_:)) {
        item.state = defaults.bool(forKey: "alwaysOnTop") ? .on : .off
      }
    }
    screenItem.state = defaults.bool(forKey: "screenContext") ? .on : .off
  }

  private func applyPreferences() {
    let configuration: [String: Any] = [
      "displayName": defaults.string(forKey: "displayName") ?? "Ambi",
      "color": defaults.string(forKey: "characterColor") ?? "blue",
      "background": defaults.string(forKey: "background") ?? "navy",
      "scale": defaults.double(forKey: "characterScale"),
      "animated": defaults.bool(forKey: "characterAnimated"),
      "needsSetup": !defaults.bool(forKey: "hasCompletedSetup"),
    ]
    web.evaluateJavaScript(
      CompanionPolicy.javascriptCall("configure", arguments: [configuration]),
      completionHandler: nil)
    web.evaluateJavaScript(
      CompanionPolicy.javascriptCall(
        "appearance",
        arguments: [
          defaults.string(forKey: "background")!, defaults.double(forKey: "characterScale"),
        ]), completionHandler: nil)
    web.evaluateJavaScript(
      CompanionPolicy.javascriptCall(
        "screenContext", arguments: [defaults.bool(forKey: "screenContext")]),
      completionHandler: nil)
    window.backgroundColor = backgroundColor
    web.underPageBackgroundColor = backgroundColor
    window.appearance = NSAppearance(
      named: defaults.string(forKey: "background") == "white" ? .aqua : .darkAqua)
  }

  private func command(_ name: String, value: String? = nil) {
    web.evaluateJavaScript(
      CompanionPolicy.javascriptCall("command", arguments: value.map { [name, $0] } ?? [name]),
      completionHandler: nil)
  }

  @objc private func toggleSession() { command("toggle-session") }
  @objc private func stopTask() { command("stop-task") }
  @objc private func toggleMicrophone() { command("microphone") }
  @objc private func toggleFocus() { command("focus") }
  @objc private func toggleScreen() {
    defaults.set(!defaults.bool(forKey: "screenContext"), forKey: "screenContext")
    applyPreferences()
  }
  @objc private func setBackground(_ sender: NSMenuItem) {
    defaults.set([0: "white", 1: "black", 3: "navy"][sender.tag] ?? "navy", forKey: "background")
    applyPreferences()
  }
  @objc private func scaleCharacter(_ sender: NSMenuItem) {
    defaults.set(
      min(0.95, max(0.35, defaults.double(forKey: "characterScale") + Double(sender.tag) * 0.1)),
      forKey: "characterScale")
    applyPreferences()
  }
  @objc private func setSize(_ sender: NSMenuItem) {
    window.setContentSize(NSSize(width: max(360, sender.tag), height: max(440, Int(Double(sender.tag) * 1.05))))
    window.makeKeyAndOrderFront(nil)
  }
  @objc private func toggleTop(_ sender: NSMenuItem) {
    let value = !defaults.bool(forKey: "alwaysOnTop")
    defaults.set(value, forKey: "alwaysOnTop")
    window.level = value ? .floating : .normal
  }
  @objc private func openControls() { NSWorkspace.shared.open(CompanionPolicy.baseURL) }
  @objc private func showSetup() {
    web.evaluateJavaScript(CompanionPolicy.javascriptCall("showSetup"), completionHandler: nil)
  }
  @objc private func toggleActivity() {
    web.evaluateJavaScript(CompanionPolicy.javascriptCall("showActivity"), completionHandler: nil)
  }
  @objc private func showConnections() {
    web.evaluateJavaScript(
      CompanionPolicy.javascriptCall("showConnections"), completionHandler: nil)
  }
  @objc private func checkUpdates() {
    NSWorkspace.shared.open(
      URL(string: "https://github.com/jenniferumoke/ambi-openai-hackathon/releases")!)
  }
  private var voiceSetupAllowed: Bool {
    CompanionPolicy.canConfigureVoice(
      serviceOwned: service?.isRunning == true,
      connected: state["connected"] as? Bool ?? false,
      status: state["status"] as? String ?? "offline",
      jobRunning: state["jobRunning"] as? Bool ?? false)
  }
  @objc private func configureAPIKey() {
    guard !configuringVoice && !startingService else { return }
    guard voiceSetupAllowed else {
      alert("Voice setup is unavailable",
        "End active voice and tasks first. Ambi can reconnect only its own idle service; a service started elsewhere must be managed separately.")
      return
    }
    let prompt = NSAlert()
    prompt.messageText = "Voice API key for this launch"
    prompt.informativeText =
      "Kept in app memory only. Use Key reconnects Ambi’s own idle service; saved conversations are retained."
    let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
    prompt.accessoryView = field
    prompt.addButton(withTitle: "Use Key")
    prompt.addButton(withTitle: "Cancel")
    let accepted = prompt.runModal() == .alertFirstButtonReturn
    let value = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
    field.stringValue = ""
    guard accepted, !value.isEmpty, value.utf16.count <= 512 else { return }
    guard voiceSetupAllowed else {
      alert("Voice setup paused", "A session or task became active. Finish it before changing the voice key.")
      return
    }
    launchKey = value
    restartIdleServiceForSetup()
  }
  private func restartIdleServiceForSetup() {
    guard !configuringVoice && !startingService && voiceSetupAllowed else {
      alert("Driver setup paused", "End active voice and tasks first. Only Ambi’s own idle service can be reconnected.")
      return
    }
    configuringVoice = true
    Task {
      defer { configuringVoice = false }
      if let process = service, process.isRunning {
        process.terminate()
        for _ in 0..<40 {
          if !process.isRunning { break }
          try? await Task.sleep(nanoseconds: 150_000_000)
        }
        guard !process.isRunning else {
          alert("Service is still closing", "Ambi has kept the key in memory. Wait for its own service to close, then use Connection → Start Local Service.")
          return
        }
        service = nil
        try? serviceLog?.close()
        serviceLog = nil
      }
      startService()
    }
  }
  private func chooseWorkspace() {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.allowsMultipleSelection = false
    panel.prompt = "Choose working folder"
    if panel.runModal() == .OK, let path = panel.url?.path {
      web.evaluateJavaScript(
        CompanionPolicy.javascriptCall("selectWorkspace", arguments: [path]), completionHandler: nil
      )
    }
  }
  @objc private func previewScreenFrame() { screenFrame.setPreview(true) }

  private func setActivityExpanded(_ expanded: Bool) {
    guard activityExpanded != expanded else { return }
    activityExpanded = expanded
    let visible = window.screen?.visibleFrame ?? NSScreen.main!.visibleFrame
    window.minSize = expanded ? NSSize(width: 680, height: 440) : NSSize(width: 360, height: 440)
    var target = window.frame
    if expanded {
      compactFrame = window.frame
      target.size = NSSize(
        width: min(940, visible.width), height: min(max(600, target.height), visible.height))
      target.origin.y = window.frame.maxY - target.height
    } else if let previous = compactFrame {
      target.size = previous.size
      target.origin.y = window.frame.maxY - target.height
    }
    target.origin.x = min(max(target.origin.x, visible.minX), visible.maxX - target.width)
    target.origin.y = min(max(target.origin.y, visible.minY), visible.maxY - target.height)
    window.setFrame(target, display: true, animate: true)
  }
  @objc private func about() {
    alert(
      "Ambi for macOS",
      "A local character companion. Use Session → Start Session, or press Space.\n\nThis development build connects to Jennifer’s Ambi service. Codex integration is the next stage."
    )
  }
  @objc private func showDetails() {
    alert(
      "Ambi connection",
      "Service: 127.0.0.1:8765\nMode: \(state["mode"] as? String ?? "unavailable")\nStatus: \(state["status"] as? String ?? "offline")\nAPI key present: \((state["apiConfigured"] as? Bool ?? false) ? "yes" : "no")\n\(screenFrame.summary)\n\n\(lastError)"
    )
  }
  private func alert(_ title: String, _ message: String) {
    let alert = NSAlert()
    if let characterIcon { alert.icon = characterIcon }
    alert.messageText = title
    alert.informativeText = message
    alert.runModal()
  }

  @objc private func reviewSuggestion() {
    guard let suggestion = state["suggestion"] as? [String: String], let id = suggestion["id"]
    else { return }
    let alert = NSAlert()
    alert.messageText = "A thought from Ambi"
    alert.informativeText = suggestion["text"] ?? ""
    alert.addButton(withTitle: "Help Me")
    alert.addButton(withTitle: "Not Now")
    command(alert.runModal() == .alertFirstButtonReturn ? "accept" : "dismiss", value: id)
  }

  @objc private func reload() {
    screenFrame.reset()
    web.load(URLRequest(url: CompanionPolicy.baseURL.appendingPathComponent("companion.html")))
  }

  @objc private func startService() {
    guard !startingService else { return }
    startingService = true
    Task {
      defer { startingService = false }
      if let (data, response) = try? await URLSession.shared.data(
        from: CompanionPolicy.baseURL.appendingPathComponent("api/bootstrap")),
        (response as? HTTPURLResponse)?.statusCode == 200,
        (try? JSONSerialization.jsonObject(with: data)) is [String: Any]
      {
        alert(
          "Ambi service is running",
          "Reload the connection. If this is an older checkout, stop that service before starting this build."
        )
        return
      }
      let bundled = Bundle.main.bundleURL.appendingPathComponent(
        "Contents/Resources/Service/AmbiService")
      let packaged = FileManager.default.isExecutableFile(atPath: bundled.path)
      let directory =
        Bundle.main.object(forInfoDictionaryKey: "AmbiBackendDirectory") as? String ?? ""
      guard service?.isRunning != true,
        packaged || FileManager.default.fileExists(atPath: directory + "/ui/dist/companion.html")
      else {
        alert(
          "Local service unavailable",
          "Reinstall this build, or rebuild the development service. See Connection Details for recovery."
        )
        return
      }
      let process = Process()
      if packaged {
        process.executableURL = bundled
        process.arguments = ["--port", "8765"]
      } else {
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [
          "uv", "run", "--locked", "python", "companion_service.py", "--port", "8765",
        ]
        process.currentDirectoryURL = URL(fileURLWithPath: directory)
      }
      var environment = ProcessInfo.processInfo.environment
      environment["PATH"] =
        "/opt/homebrew/bin:/usr/local/bin:\(NSHomeDirectory())/.local/bin:"
        + (environment["PATH"] ?? "/usr/bin:/bin")
      if let launchKey { environment["OPENAI_API_KEY"] = launchKey }
      environment["AMBI_DATA_DIR"] = NSHomeDirectory() + "/Library/Application Support/Ambi/data"
      environment["AMBI_NATIVE_HOST"] = "1"
      let bundledCodex = Bundle.main.bundleURL.appendingPathComponent(
        "Contents/Resources/Codex/bin/codex")
      if FileManager.default.isExecutableFile(atPath: bundledCodex.path) {
        environment["AMBI_CODEX_BIN"] = bundledCodex.path
      }
      process.environment = environment
      let folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[
        0
      ].appendingPathComponent("Ambi")
      do {
        try FileManager.default.createDirectory(
          at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        if packaged { process.currentDirectoryURL = folder }
        let log = folder.appendingPathComponent("service.log")
        FileManager.default.createFile(
          atPath: log.path, contents: nil, attributes: [.posixPermissions: 0o600])
        serviceLog = try FileHandle(forWritingTo: log)
        process.standardOutput = serviceLog
        process.standardError = serviceLog
        process.standardInput = FileHandle.nullDevice
        try process.run()
        service = process
        for _ in 0..<30 {
          try await Task.sleep(nanoseconds: 300_000_000)
          if let (_, response) = try? await URLSession.shared.data(
            from: CompanionPolicy.baseURL.appendingPathComponent("api/bootstrap")),
            (response as? HTTPURLResponse)?.statusCode == 200
          {
            reload()
            return
          }
          if !process.isRunning { break }
        }
        alert(
          "Service did not become ready",
          "Check ~/Library/Application Support/Ambi/service.log, then use Connection → Start Local Service to try again."
        )
      } catch {
        alert("Could not start Ambi", "Check that uv and the configured checkout are available.")
      }
    }
  }

  func userContentController(
    _ userContentController: WKUserContentController, didReceive message: WKScriptMessage
  ) {
    guard message.frameInfo.isMainFrame, let url = message.frameInfo.request.url,
      CompanionPolicy.allowsNavigation(url), let body = message.body as? [String: Any]
    else { return }
    if body["type"] as? String == "open-codex-login", let value = body["url"] as? String,
      let url = URL(string: value), url.scheme == "https", url.host == "auth.openai.com",
      url.user == nil, url.password == nil
    {
      NSWorkspace.shared.open(url)
      return
    }
    if body["type"] as? String == "copy-diagnostics", let text = body["text"] as? String,
      text.count <= 8000
    {
      NSPasteboard.general.clearContents()
      NSPasteboard.general.setString(text, forType: .string)
      return
    }
    if body["type"] as? String == "browser-chat" {
      guard let provider = body["provider"] as? String,
        let address = ["chatgpt": "https://chatgpt.com/", "claude": "https://claude.ai/", "gemini": "https://gemini.google.com/"][provider],
        let draft = body["draft"] as? String, draft.utf16.count <= 4000,
        let url = URL(string: address)
      else { return }
      if !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(draft, forType: .string)
      }
      NSWorkspace.shared.open(url)
      return
    }
    if body["type"] as? String == "reconnect-driver" {
      guard service?.isRunning == true else {
        alert("Driver is managed elsewhere", "This Ambi window can reconnect only its own service.")
        return
      }
      restartIdleServiceForSetup()
      return
    }
    if body["type"] as? String == "configure-voice" {
      configureAPIKey()
      return
    }
    if body["type"] as? String == "choose-workspace" {
      chooseWorkspace()
      return
    }
    if body["type"] as? String == "request-screen-permission" {
      guard voiceSetupAllowed && !requestingScreenAccess else { return }
      requestingScreenAccess = true
      Task {
        defer { requestingScreenAccess = false }
        if !CGPreflightScreenCaptureAccess() {
          // Request from this signed host, not from the Python helper. Discard
          // the returned window metadata; no stream or screenshots are created.
          _ = try? await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        }
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
      }
      return
    }
    if body["type"] as? String == "open-permissions" {
      // Register this signed app through Apple's public permission request.
      // The asynchronous OS prompt never counts as a successful grant.
      let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
      _ = AXIsProcessTrustedWithOptions(options as CFDictionary)
      NSWorkspace.shared.open(
        URL(
          string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
      return
    }
    if body["type"] as? String == "frame-color", let hex = body["hex"] as? String {
      screenFrame.setColor(hex: hex)
      return
    }
    if body["type"] as? String == "frame-preview", let enabled = body["enabled"] as? Bool {
      screenFrame.setPreview(enabled)
      return
    }
    if body["type"] as? String == "setup-layout" {
      if body["open"] as? Bool == true {
        if frameBeforeSetup == nil { frameBeforeSetup = window.frame }
        let visible = window.screen?.visibleFrame ?? NSScreen.main!.visibleFrame
        var frame = window.frame
        frame.size = NSSize(width: min(980, visible.width), height: min(800, visible.height))
        frame.origin.x = min(max(frame.origin.x, visible.minX), visible.maxX - frame.width)
        frame.origin.y = min(
          max(window.frame.maxY - frame.height, visible.minY), visible.maxY - frame.height)
        window.setFrame(frame, display: true, animate: true)
      } else if let frame = frameBeforeSetup {
        frameBeforeSetup = nil
        window.setFrame(frame, display: true, animate: true)
      }
      return
    }
    if body["type"] as? String == "preferences" {
      guard let value = body["value"] as? [String: Any],
        let preferences = CompanionPreferences(message: value)
      else { return }
      defaults.set(preferences.displayName, forKey: "displayName")
      defaults.set(preferences.color, forKey: "characterColor")
      defaults.set(preferences.background, forKey: "background")
      defaults.set(preferences.scale, forKey: "characterScale")
      defaults.set(preferences.animated, forKey: "characterAnimated")
      defaults.set(true, forKey: "hasCompletedSetup")
      applyPreferences()
      return
    }
    if body["type"] as? String == "layout" {
      setActivityExpanded(body["expanded"] as? Bool ?? false)
      return
    }
    if body["type"] as? String == "error" {
      lastError = body["message"] as? String ?? "Connection error"
      return
    }
    guard body["type"] as? String == "state" else { return }
    state = body
    ownsSession = body["sessionOwned"] as? Bool ?? false
    ownsJob = body["jobOwned"] as? Bool ?? false
    ownedJobClientId = body["ownedJobClientId"] as? String ?? ""
    let connected = body["connected"] as? Bool ?? false
    screenFrame.update(connected: connected, running: body["jobRunning"] as? Bool ?? false)
    let status = body["status"] as? String ?? "offline"
    let active = ["connected", "connecting", "stopping"].contains(status)
    statusItem.title =
      "\(connected ? status.capitalized : "Reconnecting") · \((body["mode"] as? String) == "ellis_demo" ? "Ellis demo" : "Personal memory")"
    sessionItem.title = active ? "End Session" : "Start Session"
    sessionItem.isEnabled = connected && status != "stopping"
    taskItem.isEnabled = connected && (body["jobRunning"] as? Bool ?? false)
    microphoneItem.isEnabled = connected
    microphoneItem.title =
      (body["microphoneEnabled"] as? Bool ?? true) ? "Mute Microphone" : "Unmute Microphone"
    focusItem.isEnabled = connected
    focusItem.state = (body["focus"] as? Bool ?? false) ? .on : .off
    suggestionItem.isEnabled = connected && body["suggestion"] is [String: Any]
    if let error = body["error"] as? String, !error.isEmpty { lastError = error }
    applyPreferences()
  }

  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { applyPreferences() }
  func webView(
    _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
    decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
  ) {
    decisionHandler(
      navigationAction.request.url.map(CompanionPolicy.allowsNavigation) == true ? .allow : .cancel)
  }
  func webView(
    _ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
    withError error: Error
  ) {
    screenFrame.reset()
    lastError = "Local service unavailable. Use Connection → Start Local Service."
    statusItem.title = "Service offline"
    let page =
      "<html><body style='margin:0;display:grid;place-items:center;height:100vh;background:\(defaults.string(forKey: "background") == "white" ? "white;color:black" : "#0d1b2a;color:white");font:13px -apple-system;text-align:center'><p>Start Ambi’s local service from the Connection menu.</p></body></html>"
    web.loadHTMLString(page, baseURL: CompanionPolicy.baseURL)
    if !attemptedAutoStart {
      attemptedAutoStart = true
      startService()
    }
  }
  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
  func windowWillClose(_ notification: Notification) { screenFrame.reset() }
  func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
    screenFrame.reset()
    if quitting { return .terminateNow }
    quitting = true
    guard ownsSession || ownsJob else {
      if service?.isRunning == true { service?.terminate() }
      return .terminateNow
    }
    Task {
      do {
        let (data, _) = try await URLSession.shared.data(
          from: CompanionPolicy.baseURL.appendingPathComponent("api/bootstrap"))
        let body = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        if let token = body?["token"] as? String {
          let actions = (ownsJob ? ["stop-task"] : []) + (ownsSession ? ["stop"] : [])
          for action in actions {
            var request = URLRequest(
              url: CompanionPolicy.baseURL.appendingPathComponent("api/" + action),
              timeoutInterval: 8)
            request.httpMethod = "POST"
            request.httpBody = try JSONSerialization.data(
              withJSONObject: action == "stop-task" ? ["client_id": ownedJobClientId] : [:])
            request.setValue(token, forHTTPHeaderField: "X-Ambi-Token")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            _ = try await URLSession.shared.data(for: request)
          }
        }
      } catch {
        alert(
          "Check your Ambi session",
          "The service could not confirm shutdown. Use End session in the full controls if it is still running."
        )
      }
      if service?.isRunning == true { service?.terminate() }
      NSApp.reply(toApplicationShouldTerminate: true)
    }
    return .terminateLater
  }

  func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
    screenFrame.reset()
  }
}

MainActor.assumeIsolated {
  let app = NSApplication.shared
  let delegate = AppDelegate()
  app.delegate = delegate
  app.setActivationPolicy(.regular)
  app.run()
}
