// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "DesktopOverlay",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "DesktopOverlay",
            resources: [.copy("Resources")]
        ),
        .testTarget(
            name: "DesktopOverlayTests",
            dependencies: ["DesktopOverlay"]
        )
    ]
)
