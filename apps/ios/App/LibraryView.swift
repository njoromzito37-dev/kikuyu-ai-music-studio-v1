import KikuyuStudioKit
import SwiftUI

/// Song library: mastered-state badges, tempo/key/camelot, voice profile.
struct LibraryView: View {
    @EnvironmentObject private var viewModel: StudioViewModel

    var body: some View {
        List(viewModel.songs) { song in
            NavigationLink {
                PlayerView(song: song)
            } label: {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(song.title).font(.headline)
                        Spacer()
                        if song.masteredUrl != nil {
                            Text("MASTERED")
                                .font(.caption2.bold())
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(.green.opacity(0.2))
                                .foregroundStyle(.green)
                                .clipShape(Capsule())
                        }
                    }
                    HStack(spacing: 8) {
                        if let bpm = song.tempoBpm {
                            Label("\(bpm) BPM", systemImage: "metronome")
                        }
                        if !song.camelot.isEmpty {
                            Label(song.camelot, systemImage: "key")
                        }
                        if let voice = song.voice {
                            Label(voice.name, systemImage: "music.mic")
                        }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    Text(song.genre?.name ?? "")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                .padding(.vertical, 2)
            }
        }
        .navigationTitle("Ngoma Library")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await viewModel.refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(viewModel.isLoading)
            }
        }
        .overlay {
            if viewModel.isLoading && viewModel.songs.isEmpty {
                ProgressView("Loading ngoma…")
            } else if let message = viewModel.errorMessage, viewModel.songs.isEmpty {
                ContentUnavailableView(
                    "Studio Offline",
                    systemImage: "network.slash",
                    description: Text(message)
                )
            }
        }
        .task { await viewModel.refresh() }
    }
}
