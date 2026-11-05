import KikuyuStudioKit
import SwiftUI

/// Mastered-track player: waveform strip, transport, auto-cue chips,
/// and one-tap Master/Analyze actions backed by the Celery pipeline.
struct PlayerView: View {
    let song: StudioSong
    @EnvironmentObject private var viewModel: StudioViewModel

    private var isThisLoaded: Bool { viewModel.player.loadedSongId == song.id }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                waveformStrip
                transport
                if !song.cuePoints.isEmpty { cueChips }
                actions
            }
            .padding()
        }
        .navigationTitle(song.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var header: some View {
        HStack(spacing: 12) {
            if let bpm = song.tempoBpm { stat("\(bpm)", "BPM") }
            if !song.musicalKey.isEmpty { stat(song.musicalKey, "Key") }
            if !song.camelot.isEmpty { stat(song.camelot, "Camelot") }
            if let voice = song.voice { stat(voice.name, "Voice") }
        }
    }

    private func stat(_ value: String, _ label: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(.callout.bold())
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(8)
        .background(.quaternary)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var waveformStrip: some View {
        let peaks = song.waveform.isEmpty ? Array(repeating: 0.2, count: 48) : song.waveform
        let progress = viewModel.player.duration > 0
            ? viewModel.player.position / viewModel.player.duration
            : 0
        return HStack(alignment: .center, spacing: 2) {
            ForEach(Array(peaks.enumerated()), id: \.offset) { index, peak in
                let played = Double(index) / Double(peaks.count) <= progress
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(played ? Color.green : Color.gray.opacity(0.4))
                    .frame(width: 3, height: max(4, CGFloat(peak) * 56))
            }
        }
        .frame(height: 60)
        .accessibilityLabel("Waveform")
    }

    private var transport: some View {
        HStack(spacing: 24) {
            Text(time(viewModel.player.position))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            Button {
                Task {
                    if isThisLoaded {
                        viewModel.player.isPlaying ? viewModel.player.pause() : viewModel.player.play()
                    } else {
                        await viewModel.play(song)
                    }
                }
            } label: {
                Image(systemName: viewModel.player.isPlaying && isThisLoaded ? "pause.circle.fill" : "play.circle.fill")
                    .font(.system(size: 56))
            }
            Text(time(viewModel.player.duration))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private var cueChips: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Hot Cues").font(.headline)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 90))], spacing: 8) {
                ForEach(song.cuePoints, id: \.time) { cue in
                    HStack(spacing: 4) {
                        Circle().fill(color(for: cue.label)).frame(width: 8, height: 8)
                        Text(cue.label).font(.caption.bold())
                        Text(time(cue.time)).font(.caption2.monospacedDigit())
                    }
                    .padding(.horizontal, 8).padding(.vertical, 6)
                    .background(.quaternary)
                    .clipShape(Capsule())
                }
            }
        }
    }

    private var actions: some View {
        HStack(spacing: 12) {
            Button {
                Task { await viewModel.master(song) }
            } label: {
                Label(song.masteredUrl == nil ? "Master (−14 LUFS)" : "Remaster", systemImage: "waveform.badge.plus")
            }
            .buttonStyle(.borderedProminent)

            Button {
                Task { await viewModel.analyze(song) }
            } label: {
                Label("Analyze", systemImage: "waveform.path.ecg")
            }
            .buttonStyle(.bordered)
        }
    }

    private func color(for label: String) -> Color {
        switch label {
        case "drop": return .green
        case "breakdown": return .orange
        case "verse": return .cyan
        case "outro": return .purple
        default: return .gray
        }
    }

    private func time(_ seconds: Double) -> String {
        guard seconds.isFinite else { return "0:00" }
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return String(format: "%d:%02d", mins, secs)
    }
}
