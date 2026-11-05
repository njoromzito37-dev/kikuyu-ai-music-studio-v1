import Foundation
import KikuyuStudioKit

/// Drives the library, playback, and studio actions (master / analyze / mix).
@MainActor
final class StudioViewModel: ObservableObject {
    @Published var songs: [StudioSong] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    let player = TrackPlayerEngine()
    let client: APIClient

    override init() {
        // Configure via Info.plist (STUDIO_API_URL, STUDIO_API_USER, STUDIO_API_PASSWORD)
        // or fall back to the local dev defaults.
        let bundle = Bundle.main
        let urlString = bundle.object(forInfoDictionaryKey: "STUDIO_API_URL") as? String
            ?? "http://127.0.0.1:8001/api"
        let user = bundle.object(forInfoDictionaryKey: "STUDIO_API_USER") as? String ?? "studio"
        let password = bundle.object(forInfoDictionaryKey: "STUDIO_API_PASSWORD") as? String ?? ""
        client = APIClient(
            configuration: APIClient.Configuration(
                baseURL: URL(string: urlString)!,
                username: user,
                password: password
            )
        )
    }

    func refresh() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            songs = try await client.fetchSongs()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func play(_ song: StudioSong) async {
        do {
            try await player.load(song: song)
            player.play()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Queue mastering, then poll until the mastered file lands.
    func master(_ song: StudioSong) async {
        do {
            try await client.requestMaster(songId: song.id)
            for _ in 0..<120 { // ~4 minutes max
                try await Task.sleep(nanoseconds: 2_000_000_000)
                let updated = try await client.fetchSong(id: song.id)
                if let index = songs.firstIndex(where: { $0.id == updated.id }) {
                    songs[index] = updated
                }
                if updated.masteredUrl != nil || updated.status == "FAILED" { break }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func analyze(_ song: StudioSong) async {
        do {
            try await client.requestAnalysis(songId: song.id)
            try await Task.sleep(nanoseconds: 3_000_000_000)
            let updated = try await client.fetchSong(id: song.id)
            if let index = songs.firstIndex(where: { $0.id == updated.id }) {
                songs[index] = updated
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
