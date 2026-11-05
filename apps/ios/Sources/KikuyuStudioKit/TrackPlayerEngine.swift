import AVFoundation
import Combine
import Foundation

/// Streams a mastered track from the studio API and plays it through an
/// AVAudioEngine player node, publishing position for SwiftUI scrubbers and
/// cue markers.
///
/// Audio is downloaded to a temp file first (AVAudioFile needs random access);
/// mastered_url is preferred over the raw audio_url.
public final class TrackPlayerEngine: ObservableObject {
    @Published public private(set) var isPlaying = false
    @Published public private(set) var position: TimeInterval = 0
    @Published public private(set) var duration: TimeInterval = 0
    @Published public private(set) var loadedSongId: Int?

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var audioFile: AVAudioFile?
    private var displayTimer: AnyCancellable?
    private var downloadTask: URLSessionDataTask?

    public enum PlayerError: Error {
        case downloadFailed
    }

    public init() {
        engine.attach(player)
        let format = engine.outputNode.inputFormat(forBus: 0)
        engine.connect(player, to: engine.mainMixerNode, format: nil)
        engine.connect(engine.mainMixerNode, to: engine.outputNode, format: format)
        engine.prepare()
    }

    public func load(song: StudioSong) async throws {
        guard let url = song.masteredUrl ?? song.audioUrl else { return }
        stop()

        let (tempURL, response) = try await URLSession.shared.download(from: url)
        guard (response as? HTTPURLResponse).map({ (200..<300).contains($0.statusCode) }) ?? true else {
            throw PlayerError.downloadFailed
        }
        let file = try AVAudioFile(forReading: tempURL)
        audioFile = file
        duration = Double(file.length) / file.processingFormat.sampleRate
        loadedSongId = song.id
        if !engine.isRunning { try engine.start() }
    }

    public func play() {
        guard let file = audioFile, !isPlaying else { return }
        player.scheduleFile(file, at: nil) { [weak self] in
            Task { @MainActor in self?.finish() }
        }
        player.play()
        isPlaying = true
        startPositionTimer()
    }

    public func pause() {
        player.pause()
        isPlaying = false
    }

    public func stop() {
        player.stop()
        isPlaying = false
        position = 0
        downloadTask?.cancel()
    }

    private func finish() {
        isPlaying = false
        position = 0
    }

    private func startPositionTimer() {
        displayTimer = Timer.publish(every: 0.1, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                guard let self,
                      let nodeTime = self.player.lastRenderTime,
                      let playerTime = self.player.playerTime(forNodeTime: nodeTime)
                else { return }
                self.position = min(
                    Double(playerTime.sampleTime) / playerTime.sampleRate,
                    self.duration
                )
            }
    }
}
