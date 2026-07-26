// swift-tools-version: 6.0

import PackageDescription

let package = Package(
  name: "AMTStudioMac",
  platforms: [
    .macOS(.v14)
  ],
  products: [
    .library(name: "AMTStudioCore", targets: ["AMTStudioCore"]),
    .library(name: "AMTStudioUI", targets: ["AMTStudioUI"]),
    .executable(name: "AMTStudio", targets: ["AMTStudio"]),
  ],
  targets: [
    .target(name: "AMTStudioCore"),
    .target(
      name: "AMTStudioUI",
      dependencies: ["AMTStudioCore"]
    ),
    .executableTarget(
      name: "AMTStudio",
      dependencies: ["AMTStudioUI"]
    ),
    .testTarget(
      name: "AMTStudioCoreTests",
      dependencies: ["AMTStudioCore"]
    ),
    .testTarget(
      name: "AMTStudioUITests",
      dependencies: ["AMTStudioCore", "AMTStudioUI"]
    ),
  ]
)
