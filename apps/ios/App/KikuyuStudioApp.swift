import SwiftUI

@main
struct KikuyuStudioApp: App {
    @StateObject private var viewModel = StudioViewModel()

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                LibraryView()
                    .environmentObject(viewModel)
            }
            .preferredColorScheme(.dark)
        }
    }
}
