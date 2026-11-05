// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "KikuyuStudioKit",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "KikuyuStudioKit", targets: ["KikuyuStudioKit"]),
    ],
    targets: [
        .target(name: "KikuyuStudioKit"),
        .testTarget(name: "KikuyuStudioKitTests", dependencies: ["KikuyuStudioKit"]),
    ]
)
