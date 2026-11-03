import AppKit

// These panels never become the keyboard target. Only the small stop panel
// accepts clicks; the transparent display-sized frame passes everything through.
private final class FramePanel: NSPanel {
  override var canBecomeKey: Bool { false }
  override var canBecomeMain: Bool { false }
}

private final class ScreenEdgeView: NSView {
  var accent = NSColor.systemTeal
  override func draw(_ dirtyRect: NSRect) {
    let teal = accent
    let depth = min(72.0, min(bounds.width, bounds.height) / 4)
    NSGraphicsContext.saveGraphicsState()
    NSBezierPath(roundedRect: bounds, xRadius: 14, yRadius: 14).addClip()
    // A translucent wash fades inward; the centre remains fully transparent.
    if let glow = NSGradient(
      starting: teal.withAlphaComponent(0.46), ending: teal.withAlphaComponent(0))
    {
      glow.draw(in: NSRect(x: 0, y: 0, width: bounds.width, height: depth), angle: 90)
      glow.draw(
        in: NSRect(x: 0, y: bounds.height - depth, width: bounds.width, height: depth),
        angle: 270)
      glow.draw(in: NSRect(x: 0, y: 0, width: depth, height: bounds.height), angle: 0)
      glow.draw(
        in: NSRect(x: bounds.width - depth, y: 0, width: depth, height: bounds.height),
        angle: 180)
    }
    let bloom = NSShadow()
    bloom.shadowColor = teal.withAlphaComponent(0.8)
    bloom.shadowBlurRadius = 16
    bloom.shadowOffset = .zero
    bloom.set()
    teal.withAlphaComponent(0.9).setStroke()
    let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 2, dy: 2), xRadius: 14, yRadius: 14)
    path.lineWidth = 3
    path.stroke()
    NSGraphicsContext.restoreGraphicsState()
  }
}

@MainActor
final class ScreenFrame {
  private var colorHex = "#5b8def"
  private var accent = NSColor(srgbRed: 91 / 255.0, green: 141 / 255.0, blue: 239 / 255.0, alpha: 1)
  private var panels: [NSPanel] = []
  private var active = false
  private var preview = false
  private var lastHeartbeat = Date.distantPast
  private var timer: Timer?
  private var screenObserver: NSObjectProtocol?
  var stop: (() -> Void)?
  var summary: String {
    let mode = active ? "active task" : preview ? "preview" : "off"
    return
      "Display frame: \(mode), colour \(colorHex); \(panels.filter { $0.isVisible }.count) visible panels across \(NSScreen.screens.count) display(s)."
  }

  func setColor(hex: String) {
    guard hex.count == 7, hex.first == "#", let value = UInt32(hex.dropFirst(), radix: 16),
      hex.lowercased() != colorHex
    else { return }
    colorHex = hex.lowercased()
    accent = NSColor(
      srgbRed: Double((value >> 16) & 255) / 255,
      green: Double((value >> 8) & 255) / 255,
      blue: Double(value & 255) / 255, alpha: 1)
    rebuild()
  }

  init() {
    screenObserver = NotificationCenter.default.addObserver(
      forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main
    ) { [weak self] _ in
      MainActor.assumeIsolated { self?.rebuild() }
    }
    timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
      MainActor.assumeIsolated {
        guard let self, self.active, Date().timeIntervalSince(self.lastHeartbeat) > 3 else {
          return
        }
        self.reset()
      }
    }
  }

  func update(connected: Bool, running: Bool) {
    lastHeartbeat = Date()
    let next = connected && running
    if !connected { preview = false }
    guard next != active || (!connected && !panels.isEmpty) else { return }
    active = next
    preview = false
    rebuild()
  }

  func setPreview(_ enabled: Bool) {
    guard preview != enabled else { return }
    preview = enabled
    rebuild()
  }

  func reset() {
    active = false
    preview = false
    rebuild()
  }

  private func panel(_ frame: NSRect, clickThrough: Bool) -> NSPanel {
    let panel = FramePanel(
      contentRect: frame, styleMask: [.borderless, .nonactivatingPanel],
      backing: .buffered, defer: false)
    panel.isOpaque = false
    panel.backgroundColor = .clear
    panel.hasShadow = false
    panel.ignoresMouseEvents = clickThrough
    panel.level = .screenSaver
    panel.collectionBehavior = [
      .canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle,
    ]
    panel.hidesOnDeactivate = false
    panel.isReleasedWhenClosed = false
    panel.sharingType = .none
    return panel
  }

  private func rebuild() {
    for panel in panels { panel.close() }
    panels.removeAll()
    guard active || preview else { return }
    for screen in NSScreen.screens {
      let edge = panel(screen.frame, clickThrough: true)
      let edgeView = ScreenEdgeView(frame: NSRect(origin: .zero, size: screen.frame.size))
      edgeView.accent = accent
      edge.contentView = edgeView
      edge.orderFrontRegardless()
      panels.append(edge)

      let visible = screen.visibleFrame
      let width = min(420.0, visible.width - 24)
      let control = panel(
        NSRect(x: visible.midX - width / 2, y: visible.maxY - 46, width: width, height: 36),
        clickThrough: false)
      control.title = active ? "Ambi computer-use controls" : "Ambi screen-frame preview"
      let surface = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 36))
      surface.wantsLayer = true
      surface.layer?.backgroundColor = accent.blended(withFraction: 0.12, of: .white)?.cgColor
      surface.layer?.cornerRadius = 9
      let label = NSTextField(
        labelWithString:
          active ? "Ambi is working" : "Ambi screen-frame preview")
      label.font = .systemFont(ofSize: 12, weight: .medium)
      label.textColor = NSColor(calibratedRed: 0.06, green: 0.17, blue: 0.15, alpha: 1)
      label.frame = NSRect(x: 12, y: 10, width: width - 134, height: 17)
      surface.addSubview(label)
      let button = NSButton(
        title: active ? "Stop task" : "Close preview", target: self,
        action: #selector(pressed))
      button.bezelStyle = .rounded
      button.frame = NSRect(x: width - 117, y: 4, width: 110, height: 28)
      surface.addSubview(button)
      control.contentView = surface
      control.orderFrontRegardless()
      panels.append(control)
    }
  }

  @objc private func pressed() {
    if active { stop?() } else { setPreview(false) }
  }
}
