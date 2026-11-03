// swift-tools-version: 5.9
import PackageDescription

let package = Package(
  name: "AmbiDesktop",
  platforms: [.macOS(.v14)],
  products: [.executable(name: "Ambi", targets: ["Ambi"])],
  targets: [
    .target(name: "AmbiCore"),
    .executableTarget(name: "Ambi", dependencies: ["AmbiCore"]),
    .testTarget(name: "AmbiCoreTests", dependencies: ["AmbiCore"]),
  ]
)
