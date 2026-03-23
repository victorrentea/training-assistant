// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "EmojiOverlay",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "EmojiOverlay",
            resources: [.copy("Resources")]
        )
    ]
)
